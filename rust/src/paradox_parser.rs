use std::time;
use std::path::{PathBuf};
use std::sync::{Arc, RwLock};
use std::collections::{HashMap,HashSet};
use pyo3::prelude::*;
use pyo3::types::PyModule;
use log::info;
use regex::Regex;
use rayon::prelude::*;
use tree_sitter_paradox;
use crate::definition_tree::{Arena, NodeId, ModData, ParadoxModDefinitionTree, DefinitionNode};

fn get_file_name(file: &PathBuf) -> String {
    file.file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string()
}

fn get_rel_dir(file: &PathBuf, workshop_dir: &PathBuf, mods_dir: &PathBuf) -> PathBuf {
    if let Ok(rel_path) = file.strip_prefix(workshop_dir) {
        // further strip the first component (the workshop ID)
        let mut components = rel_path.components();
        components.next();
        components.as_path().to_path_buf()
    } else if let Ok(rel_path) = file.strip_prefix(mods_dir) {
        // further strip the first component (the workshop ID)
        let mut components = rel_path.components();
        components.next();
        components.as_path().to_path_buf()
    } else {
        PathBuf::from(get_file_name(file))
    }
}

static CHECK_LOC_CONFLICTS: bool = false;
// This should be kept true for now,
// since even showing conflicts using the paradox's conflict logs rely on the <def> node sources,
// which requires the conflict checking for now.
static CHECK_SCRIPT_CONFLICTS: bool = true; 
#[pyclass]
struct DefinitionExtractor{
    #[pyo3(get, set)]
    workshop_dir: PathBuf,
    #[pyo3(get, set)]
    mods_dir: PathBuf,
    #[pyo3(get, set)]
    language: Option<String>,
    // #[pyo3(get)]
    conflicts: HashSet<PathBuf>,
    arena: Arc<RwLock<Arena>>,
    #[pyo3(get, set)]
    check_loc_conflicts: bool,
    #[pyo3(get, set)]
    check_script_conflicts: bool,
    // flat mappings for easy access, collisions are likely occurred, used for error tracking when only the identifier name is given
    // see mod_analyzer.error.analyzer for usage
}
#[pymethods]
impl DefinitionExtractor {
    #[new]
    #[pyo3(signature = (workshop_dir, mods_dir, language=None))]
    pub fn new(workshop_dir: PathBuf, mods_dir: PathBuf, language: Option<String>) -> Self {
        // default language is English
        let language = language.or(Some("english".to_string()));
        let mut arena = Arena::new();
        arena.new_node("<root>".to_string(), PathBuf::from(".\\"), None);
        DefinitionExtractor {
            workshop_dir: workshop_dir,
            mods_dir: mods_dir,
            language: language,
            conflicts: HashSet::new(),
            arena: Arc::new(RwLock::new(arena)),
            check_loc_conflicts: CHECK_LOC_CONFLICTS,
            check_script_conflicts: CHECK_SCRIPT_CONFLICTS,
        }
    }
    #[getter]
    fn get_tree(&self) -> ParadoxModDefinitionTree {
        ParadoxModDefinitionTree {
            arena: self.arena.clone(),
            root:0
        }
    }
    
    #[getter]
    fn get_root(&self) -> DefinitionNode {
        DefinitionNode {
            arena: self.arena.clone(),
            id: 0,
        }
    }
    #[getter]
    fn get_conflict_identifiers(&self) -> Vec<DefinitionNode> {
        self.conflicts.iter().map(|path| {
            let node_id = self.get_root().get_by_dir(path.clone(), None)
                .map(|node| node.id)
                .unwrap_or(0);
            DefinitionNode {
                arena: self.arena.clone(),
                id: node_id,
            }
        }).collect()
    }
    fn get_conflicts_by_mod(&self) -> HashMap<String, Vec<DefinitionNode>> {
        let mut mod_conflicts: HashMap<String, Vec<DefinitionNode>> = HashMap::new();
        for conflict_dir in &self.conflicts {
            let conflict_node = match self.get_root().get_by_dir(conflict_dir.clone(), None){
                Some(node) => node,
                None => continue,
            };
            let sources = conflict_node.get_mod_sources();
            for source in sources {
                let mod_data = self.arena.read().unwrap().mod_data.get(&source.id).cloned();
                if let Some(mod_data) = mod_data {
                    mod_conflicts.entry(mod_data.name.clone())
                        .or_default()
                        .push(conflict_node.clone());
                }
            }
        }
        mod_conflicts
    }
    fn enroll_mods(&mut self, mod_list: Vec<Bound<'_, PyAny>>){
        // The PyAny is expected to have 'name', 'enabled', 'load_order' attributes
        let mut arena = self.arena.write().unwrap();
        for mod_info in mod_list {
            let name: String = mod_info.getattr("name")
                .and_then(|v| v.extract())
                .unwrap_or_else(|_| String::from("unknown"));
            let enabled: bool = mod_info.getattr("enabled")
                .and_then(|v| v.extract())
                .unwrap_or(false);
            let load_order: u32 = mod_info.getattr("load_order")
                .and_then(|v| v.extract())
                .unwrap_or(0);
            let path: PathBuf = mod_info.getattr("path")
                .and_then(|v| v.extract())
                .unwrap_or(PathBuf::from(".\\"));
            arena.new_mod(name, enabled, load_order, path);
        }
    }
    fn get_node_by_name(&self, name: String) -> Option<Vec<DefinitionNode>> {
        if let Some(node_ids) = self.arena.read().unwrap().get_by_name(name) {
            Some(node_ids.iter().map(|id| DefinitionNode {
                arena: self.arena.clone(),
                id: *id,
            }).collect())
        } else {
            None
        }
    }
    fn get_mod_node_by_name(&self, name: String) -> Option<DefinitionNode> {
        let arena = self.arena.read().unwrap();
        for (mod_id, mod_data) in arena.mod_data.iter() {
            if mod_data.name == name {
                return Some(DefinitionNode {
                    arena: self.arena.clone(),
                    id: *mod_id,
                });
            }
        }
        None
    }
    // #[pyfunction(signature = (desc_files, max_depth=-1))]
    fn extract_definitions(&mut self, py: Python<'_>, max_depth: i32) -> PyResult<DefinitionNode> {
        // desc_files: list of (enabled: bool, PathBuf)

        // get files to process
        let now = time::Instant::now();
        // let mod_files = self.collect_mod_files(desc_files);
        let mod_files = self.collect_mod_files_multithread(py);
        let file_num: usize = mod_files.values().map(|v| v.0.len()).sum();
        info!("Collected {} mod files in {:?}.", file_num, now.elapsed());
        // will be returned as the mod_manager's definition tree
        // let mut root = BaseNode::new_node("<root>".to_string(), PathBuf::from("./"));
        // let mut root = root.clone();
        // process txt files
        // let mut conflict_identifiers: Vec<PathBuf> = Vec::new();
        
        if let Some((mod_node_ids, txt_files)) = mod_files.get("txt"){
            let now = time::Instant::now();
            let txt_definitions = self._extract_definitions_multiprocess(py, txt_files, max_depth);
            info!("Extracted {} TXT definitions in {:?}.", txt_definitions.len(), now.elapsed());
            for (mod_id,arena) in mod_node_ids.iter().zip(txt_definitions) {
                let txt_root = self.arena.read().unwrap().len() as usize;
                self.get_mut_arena().extend(&arena);
                let txt_root_id = txt_root as u32;
                self.arena.write().unwrap().set_source(txt_root_id, *mod_id);
                
                // Get data we need without holding PyNode references
                let rel_dir = self.arena.read().unwrap().get(txt_root_id).get_rel_dir();
                if let Some(parent_rel_dir) = rel_dir.parent() {
                    let def_path = parent_rel_dir.join("<def>");
                    let mut root = DefinitionNode {
                        arena: self.arena.clone(),
                        id: 0,
                    };
                    root.setdefault_by_dir(
                        def_path.clone(),
                        "<def>".to_string(),
                    );
                    if let Some(mut def_node) = root.get_by_dir(def_path, None) {
                        let node = DefinitionNode {
                            arena: self.arena.clone(),
                            id: txt_root_id,
                        };
                        let mod_data = self.arena.read().unwrap().mod_data.get(mod_id).cloned();
                        if mod_data.unwrap().enabled == false {
                            // def_node.update(node);
                            // don't add the disabled mod's definitions to <def>
                        }else if self.check_script_conflicts == false {
                            def_node.update(node);
                        }else{                            
                            let conflicts = def_node.update_with_conflict_check(&node);
                            if !conflicts.is_empty() {
                                self.conflicts.extend(conflicts);
                            }
                        }
                    }
                }
                // Set by dir in separate scope
                {
                    let mut root = DefinitionNode {
                        arena: self.arena.clone(),
                        id: 0,
                    };
                    // If a file node already exists at this path (same rel_dir across mods),
                    // merge children into the existing file node so identifiers are not orphaned
                    // (otherwise `identifier.parent.parent` can become None).
                    if let Some(mut existing_file_node) = root.get_by_dir(rel_dir.clone(), None) {
                        self.arena.write().unwrap().set_source(existing_file_node.id, *mod_id);
                        existing_file_node.update(DefinitionNode {
                            arena: self.arena.clone(),
                            id: txt_root_id,
                        });
                    } else {
                        root.set_by_dir(
                            rel_dir,
                            DefinitionNode {
                                arena: self.arena.clone(),
                                id: txt_root_id,
                            },
                        );
                    }
                } // All PyNode refs dropped here
                
            }
        }
        // process yml files
            
        if let Some((mod_node_ids,yml_files)) = mod_files.get("yml") {
            let now = time::Instant::now();
            let yml_definitions = self._extract_definitions_multiprocess(py, yml_files, max_depth);
            info!("Extracted {} yml definitions in {:?}.", yml_definitions.len(), now.elapsed());
            for (mod_id,arena) in mod_node_ids.iter().zip(yml_definitions) {
                let yml_root = self.arena.read().unwrap().len() as usize;
                self.get_mut_arena().extend(&arena);
                let yml_root_id = yml_root as u32;
                self.arena.write().unwrap().set_source(yml_root_id, *mod_id);
                
                // Get data we need without holding PyNode references
                let rel_dir = self.arena.read().unwrap().get(yml_root_id).get_rel_dir();
                if let Some(parent_rel_dir) = rel_dir.parent() {
                    let loc_path = parent_rel_dir.join("<loc>");
                    let mut root = DefinitionNode {
                        arena: self.arena.clone(),
                        id: 0,
                    };
                    root.setdefault_by_dir(
                        loc_path.clone(), "<loc>".to_string()
                    );
                    if let Some(mut loc_node) = root.get_by_dir(loc_path, None) {
                        let node = DefinitionNode {
                            arena: self.arena.clone(),
                            id: yml_root_id,
                        };
                        if self.check_loc_conflicts == false {
                            // update the <loc> node directly
                            loc_node.update(node);
                        }
                        else{
                            // update the <loc> node with conflict checking (off by default)
                            let conflicts = loc_node.update_with_conflict_check(&node);
                            if !conflicts.is_empty() {
                                self.conflicts.extend(conflicts);
                            }
                        }
                    }
                }
                
                // Set by dir in separate scope
                {
                    let mut root = DefinitionNode {
                        arena: self.arena.clone(),
                        id: 0,
                    };
                    // If a file node already exists at this path (same rel_dir across mods),
                    // merge children into the existing file node so identifiers are not orphaned.
                    if let Some(mut existing_file_node) = root.get_by_dir(rel_dir.clone(), None) {
                        self.arena.write().unwrap().set_source(existing_file_node.id, *mod_id);
                        existing_file_node.update(DefinitionNode {
                            arena: self.arena.clone(),
                            id: yml_root_id,
                        });
                    } else {
                        root.set_by_dir(
                            rel_dir,
                            DefinitionNode {
                                arena: self.arena.clone(),
                                id: yml_root_id,
                            },
                        );
                    }
                } // root dropped here
            }
        }
        // process other files
        if let Some((mod_node_ids,other_files)) = mod_files.get("other") { 
            // don't extract definitions, just build the file tree
            // TODO: process gui files
            for (mod_id, file) in mod_node_ids.iter().zip(other_files){
                let file_name = get_file_name(&file);
                let rel_dir = self.get_rel_dir(file.clone());
                // Set by dir in separate scope to drop PyNode refs before next iteration.
                // If a node already exists at this path, just add this mod as a source.
                {
                    let mut root = DefinitionNode {
                        arena: self.arena.clone(),
                        id: 0,
                    };
                    if let Some(existing_file_node) = root.get_by_dir(rel_dir.clone(), None) {
                        self.arena.write().unwrap().set_source(existing_file_node.id, *mod_id);
                    } else {
                        let file_node_id = self.get_mut_arena().new_node(
                            file_name, rel_dir.clone(), None,
                        );
                        root.set_by_dir(
                            rel_dir,
                            DefinitionNode { arena: self.arena.clone(), id: file_node_id },
                        );
                        self.arena.write().unwrap().set_source(file_node_id, *mod_id);
                    }
                } // root dropped here
            }
        }
        
        // Create final root to return
        let root = DefinitionNode {
            arena: self.arena.clone(),
            id: 0,
        };
        Ok(root)
    }
}
impl DefinitionExtractor {
    // internal methods
    fn get_mut_arena(&self) -> std::sync::RwLockWriteGuard<'_, Arena> {
        self.arena.write().expect("Failed to acquire write lock on Arena")
    }
    pub fn get_rel_dir(&self, abs_path: PathBuf)-> PathBuf {
        // try to get relative path from WORKSHOP_DIR or MODS_DIR
        get_rel_dir(&abs_path, &self.workshop_dir, &self.mods_dir)
    }
    pub fn collect_mod_files(&self) -> HashMap<String, Vec<PathBuf>> {
        let mut results:HashMap<String, Vec<PathBuf>> = HashMap::new();
        let mod_data = self.arena.read().unwrap().mod_data.clone();
        for data in mod_data.values() {
            let file_map = _collect_mod_files(data.clone(), self.language.clone());
            for (key, files) in file_map {
                results.entry(key).or_default().extend(files);
            }
        }
        results
    }
    fn _collect_mod_files(&self, mod_data: ModData) -> HashMap<String, (Vec<NodeId>, Vec<PathBuf>)> {
        let mod_dir = mod_data.path;
        let mut file_map: HashMap<String, (Vec<NodeId>, Vec<PathBuf>)> = HashMap::new();
        
        for entry in walkdir::WalkDir::new(&mod_dir) {
            let entry = match entry {
                Ok(entry) => entry,
                Err(e) => {
                    eprintln!("Error reading entry: {}", e);
                    continue;
                }
            };
            let rel_path = entry.path().strip_prefix(&mod_dir).unwrap_or(entry.path());
            let depth = rel_path.components().count();
            if depth <= 1 {
                continue;
            }
            // Check first component safely
            if let Some(first_component) = rel_path.components().nth(0) {
                if [".git", "src", ".vscode"]
                    .iter()
                    .any(|&name| first_component.as_os_str() == name) {
                    continue;
                }
            } else {
                continue;
            }
            let path = entry.path();
            if !path.is_file() {
                continue;
            }

            let file_type = path.extension().and_then(|s| s.to_str());
            let is_localization = rel_path.components().nth(0)
                .map(|c| c.as_os_str().to_str() == Some("localization"))
                .unwrap_or(false);
            let key = if is_localization {
                match file_type {
                    Some("yml") => {
                        if let Some(language) = &self.language {
                            // !!!! noticed that some localization files are deeply nested, like localization/some_folder/english/file.yml
                            // use rel_path to check instead of file_name ({lang})
                            // check if {language} in the path
                            if rel_path.to_str().unwrap_or("").to_lowercase().contains(&language.to_lowercase()) {
                                "yml"
                            } else {
                                "other"
                            }
                        } else {
                            "yml"
                        }
                    }
                    _ => continue,
                }
            } else {
                match file_type {
                    Some("txt") => "txt",
                    _ => "other",
                }
            };
            
            let entry = file_map.entry(key.to_string()).or_insert((Vec::new(), Vec::new()));
            entry.0.push(mod_data.node_id);
            entry.1.push(path.to_path_buf());
        }
        file_map
    }

    pub fn collect_mod_files_multithread(&mut self, py: Python<'_>) -> HashMap<String, (Vec<NodeId>, Vec<PathBuf>)> {
        let mod_data_list = self.arena.read().unwrap().mod_data.values()
            .cloned()
            .collect::<Vec<_>>();
        
        let results = py.detach(|| {
            mod_data_list
                .into_par_iter()
                .map(|mod_data| self._collect_mod_files(mod_data))
                .reduce(HashMap::new, |mut acc, map| {
                    for (key, (ids, paths)) in map {
                        let entry = acc.entry(key).or_insert((Vec::new(), Vec::new()));
                        entry.0.extend(ids);
                        entry.1.extend(paths);
                    }
                    acc
                })
        });
        results
    }
    fn _extract_definitions_multiprocess(&self, py: Python, files: &Vec<PathBuf>, max_depth: i32) -> Vec<Arena> {
        // Avoid sharing the pyclass instance across Rayon threads.
        let workshop_dir = self.workshop_dir.clone();
        let mods_dir = self.mods_dir.clone();

        py.detach(|| {
            files
                .into_par_iter()
                .map(|file_path| extract_definitions_worker(file_path, &workshop_dir, &mods_dir, max_depth))
                .collect()
        })
    }
}


fn extract_array_vals(node: tree_sitter::Node, source_bytes: &[u8]) -> Vec<String> {
    let mut values = Vec::new();
    for child in node.children(&mut node.walk()) {
        if child.kind() == "simple_value" {
            values.push(child.utf8_text(source_bytes).unwrap().to_string());
        }
    }   
    values
}

fn parse_paradox_script(source_code: &str) -> Option<tree_sitter::Tree> {
    let mut parser = tree_sitter::Parser::new();
    let language = tree_sitter_paradox::LANGUAGE;
    parser
        .set_language(&language.into())
        .expect("Error loading Paradox parser");
    let tree = parser.parse(source_code, None).unwrap();
    // assert!(!tree.root_node().has_error());
    Some(tree)
}
fn _extract_loc_definitions(loc_txt: &str, arena: &mut Arena){
    let pattern = Regex::new(
        r#"(?m)^\s*(?P<key>[A-Za-z0-9_.-]+):(?:\d+)?\s*"(?P<value>[^\r\n]*)"\s*(?:#.*)?$"#,
    )
    .unwrap();
    // iterate through lines instead of using captures_iter
    for (line_number, line) in loc_txt.lines().enumerate() {
        if let Some(caps) = pattern.captures(line) {
            let key = caps.name("key").unwrap().as_str().to_string();
            let value = caps.name("value").unwrap().as_str().to_string();
            let root_rel_dir = arena.get(0).get_rel_dir();
            let value_node = arena.new_node(
                key.clone(), root_rel_dir, Some(value)
            );
            arena.set_node_start_point(value_node, line_number, 0);
            arena.set_child(0, key, value_node, true);
        }
    }


    // for m in pattern.captures_iter(loc_txt) {
    //     let key = m.name("key").unwrap().as_str().to_string();
    //     let value = m.name("value").unwrap().as_str().to_string();
    //     let root_rel_dir = arena.get(0).get_rel_dir();
    //     let value_node = arena.new_node(
    //         key.clone(), root_rel_dir, Some(value)
    //     );

    //     let start_byte = m.get(0).unwrap().start();
    //     let line_number = loc_txt.as_bytes()[..start_byte].iter().filter(|&&c| c == b'\n').count();

    //     arena.set_node_start_point(value_node, line_number, 0);
    //     // root.children.insert(key, Box::new(value_node));
    //     arena.set_child(0, key, value_node, true);
    // }
}
fn _extract_script_definitions(arena: &mut Arena, ts_node: tree_sitter::Node, root_node:NodeId, source_code: &str, max_depth: i32, depth: i32) {
    // max_depth <= 0 means "no limit" (matches Python-side usage).
    if max_depth > 0 && depth > max_depth {
        return;
    }
    // ts_node's type not in '{}'
    if "{}".contains(ts_node.kind()) {
        return;
    }
    // elif type == statement
    else if ts_node.kind() == "statement" {
        for child in ts_node.children(&mut ts_node.walk()) {
            if child.kind() == "simple_value" {
                let name = child.utf8_text(source_code.as_bytes()).unwrap().to_string();
                let value = child.utf8_text(source_code.as_bytes()).unwrap().to_string();
                // value_node is a BaseNode with value
                // let value_node = PyNode::new_typed_node(name.clone(), root.rel_dir_pathbuf(), Some(value), None );
                let value_node = arena.new_node(
                    name.clone(), arena.get(root_node).get_rel_dir(), Some(value)
                );
                let start_point = child.start_position();
                arena.set_node_start_point(value_node, start_point.row, start_point.column);
                arena.set_child(root_node, name, value_node, true);
            }else{ // recurse into child nodes
                _extract_script_definitions(arena, child, root_node, source_code, max_depth, depth + 1);
            }
        }   
    }else if ["source_file", "map"].contains(&ts_node.kind()) {
        // this is a intermediate node, just recurse into children
        for child in ts_node.children(&mut ts_node.walk()) {
            _extract_script_definitions(arena, child, root_node, source_code, max_depth, depth + 1);
        }   
    }else if ["assignment", "typed_assignment"].contains(&ts_node.kind()) {
        let ts_key_node = ts_node.child_by_field_name("key").unwrap();
        let ts_value_node = ts_node.child_by_field_name("value").unwrap();
        let key = ts_key_node.utf8_text(source_code.as_bytes()).unwrap().to_string();
        
        match ts_value_node.kind() {
            "simple_value" => {
                let value = ts_value_node.utf8_text(source_code.as_bytes()).unwrap().to_string();
                let value_node = arena.new_node(
                    key.clone(), arena.get(root_node).get_rel_dir(), Some(value)
                );
                arena.set_child(root_node, key, value_node, true);
            },
            "array" => {
                let values = extract_array_vals(ts_value_node, source_code.as_bytes());
                let value = format!("{:?}", values);
                let value_node = arena.new_node(
                    key.clone(), arena.get(root_node).get_rel_dir(), Some(value)
                );
                arena.set_child(root_node, key, value_node, true);
            },
            "tagged_array" => {
                let tag_node = ts_value_node.child_by_field_name("tag").unwrap();
                let tag = tag_node.utf8_text(source_code.as_bytes()).unwrap().to_string();
                let _value_node = ts_value_node.child_by_field_name("value").unwrap();
                let values = extract_array_vals(_value_node, source_code.as_bytes());
                let value = format!("{}{:?}", tag, values);
                let value_node = arena.new_node(
                    key.clone(), arena.get(root_node).get_rel_dir(), Some(value)
                );
                arena.set_child(root_node, key, value_node, true);
            },
            _ => {// nested block, go deeper
                let child_node = arena.new_node(
                    key.clone(), arena.get(root_node).get_rel_dir(), None
                );
                _extract_script_definitions(arena, ts_value_node, child_node, source_code, max_depth, depth + 1);
                // root.children.insert(key, Box::new(child_node));
                arena.set_child(root_node, key, child_node, true);
            }
        }
        
        let start_point = ts_key_node.start_position();
        arena.set_node_start_point(root_node, start_point.row, start_point.column);
    }
}


fn _collect_mod_files(mod_data: ModData, language:Option<String>) -> std::collections::HashMap<String, Vec<PathBuf>> {
    // walk through mod_dir and collect all files based on file type
    // return a mapping of files {'txt': [file1, file2], 'yml': [file3, file4], 'other': [file5, file6]}
    let mod_dir = mod_data.path;
    let mut file_map: std::collections::HashMap<String, Vec<PathBuf>> = std::collections::HashMap::new();
    for entry in walkdir::WalkDir::new(&mod_dir) {
        let entry = match entry {
            Ok(entry) => entry,
            Err(e) => {
                eprintln!("Error reading entry: {}", e);
                continue;
            }
        };

        let rel_path = entry.path().strip_prefix(&mod_dir).unwrap_or(entry.path());
        let depth = rel_path.components().count();
        if depth <= 1 {
            continue;
        }
        
        // Check first component safely
        if let Some(first_component) = rel_path.components().nth(0) {
            if [".git", "src", ".vscode"]
                .iter()
                .any(|&name| first_component.as_os_str() == name) {
                continue;
            }
        } else {
            continue;
        }

        let path = entry.path();
        if path.is_file() {
            let file_type = path.extension().and_then(|s| s.to_str());
            // Check if second component is "localization" safely
            let is_localization = rel_path.components().nth(0)
                .map(|c| c.as_os_str().to_str() == Some("localization"))
                .unwrap_or(false);
            // println!("{:?}", rel_path.components().nth(0));
            let path_buf = path.parent().unwrap_or(path).to_path_buf();
            if is_localization {
                match file_type {
                    Some("yml") => { // localization only take yml files                    
                        // if language is None, collect all yml files
                        if let Some(lang) = &language {
                            let suffix = format!("{lang}.yml");
                            // Check if the file NAME (not path) ends with the suffix
                            let file_name = path.file_name().unwrap().to_str().unwrap_or("");                            
                            if file_name.ends_with(&suffix) {
                                file_map.entry("yml".to_string()).or_default().push(path_buf);
                            } else {
                                file_map.entry("other".to_string()).or_default().push(path_buf);
                            }
                        } else {
                            file_map.entry("yml".to_string()).or_default().push(path_buf);
                        }
                    }
                    _ => continue // skip non-yml files in localization
                }
            }else{
                match file_type {
                    Some("txt") => {
                        file_map.entry("txt".to_string()).or_default().push(path_buf);
                    }                    
                    _ => {
                        file_map.entry("other".to_string()).or_default().push(path_buf);
                    }
                }

            }
            
        }
    }
    file_map
}

#[pyfunction(signature = (source_code, max_depth=-1))]
fn extract_script_definitions(source_code: &str, max_depth: i32) -> PyResult<DefinitionNode> {
    let ts_tree = parse_paradox_script(source_code).expect("Failed to parse source code");
    let mut tree = ParadoxModDefinitionTree {
        arena: Arc::new(RwLock::new(Arena::new())),
        root: 0,
    };
    tree.new_node("<root>".to_string(), PathBuf::from(".\\"), None);
    let mut arena = tree.arena.write().unwrap();
    
    _extract_script_definitions(&mut arena, ts_tree.root_node(), 0, source_code, max_depth, 0);
    drop(arena);
    let root_node = DefinitionNode {
        arena: tree.arena.clone(),
        id: 0,
    };
    Ok(root_node)
}


#[pyfunction(signature = (loc_txt))]
fn extract_loc_definitions(loc_txt: &str) -> PyResult<DefinitionNode> {
    let mut tree = ParadoxModDefinitionTree {
        arena: Arc::new(RwLock::new(Arena::new())),
        root: 0,
    };
    tree.new_node("<root>".to_string(), PathBuf::from(".\\"), None);
    let mut arena = tree.arena.write().unwrap();
    
    _extract_loc_definitions(loc_txt, &mut arena);
    drop(arena);
    let root_node: DefinitionNode = DefinitionNode {
        arena: tree.arena.clone(),
        id: 0,
    };
    Ok(root_node)
}
// #[pyfunction]
// fn collect_mod_files(mod_dir: PathBuf, language:Option<String>) -> PyResult<std::collections::HashMap<String, Vec<PathBuf>>> {
//     let file_map = _collect_mod_files(mod_dir, language);
//     Ok(file_map)
// }
// #[pyfunction]
// fn batch_collect_mod_files(mod_dirs: Vec<PathBuf>, language: Option<String>) -> PyResult<std::collections::HashMap<String, Vec<PathBuf>>> {
//     let mut results:HashMap<String, Vec<PathBuf>> = HashMap::new();
//     for mod_dir in mod_dirs {
//         let file_map = _collect_mod_files(mod_dir, language.clone());
//         for (key, files) in file_map {
//             results.entry(key).or_default().extend(files);
//         }
//     }
//     Ok(results)
// }
// #[pyfunction]
// fn collect_mod_files_multithread(py: Python<'_>, mod_dirs: Vec<PathBuf>, language: Option<String>)
//     -> PyResult<HashMap<String, Vec<PathBuf>>>
// {
//     // Release the GIL while Rust is working
//     let results = py.detach(|| {
//         mod_dirs
//             .par_iter() // ← PARALLEL
//             .map(|mod_dir| _collect_mod_files(mod_dir.clone(), language.clone()))
//             .reduce(HashMap::new, |mut acc, map| {
//                 for (key, files) in map {
//                     acc.entry(key).or_default().extend(files);
//                 }
//                 acc
//             })
//     });
//     Ok(results)
// }


fn extract_definitions_worker(
    file: &PathBuf,
    workshop_dir: &PathBuf,
    mods_dir: &PathBuf,
    max_depth: i32,
) -> Arena {
    let file_type = file.extension().and_then(|s| s.to_str());
    let source_code = std::fs::read_to_string(file).unwrap_or_default();
    let file_name = get_file_name(file);

    let rel_dir = get_rel_dir(file, workshop_dir, mods_dir);
    
    let mut arena = Arena::new();
    arena.new_node(file_name, rel_dir, None); // the root node
    match file_type {
        Some("txt") => {
            if let Some(tree) = parse_paradox_script(&source_code) {
                _extract_script_definitions(&mut arena, tree.root_node(), 0, &source_code, max_depth, 0);
            }
            arena
        }
        Some("yml") => {
            _extract_loc_definitions(&source_code, &mut arena);
            arena
        }
        _ => arena,
    }
}

#[pymodule]
pub fn paradox_parser(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Initialize pyo3-log to bridge Rust logging to Python logging
    pyo3_log::init();
    
    m.add_function(wrap_pyfunction!(extract_script_definitions, m)?)?;
    m.add_function(wrap_pyfunction!(extract_loc_definitions, m)?)?;
    // m.add_function(wrap_pyfunction!(collect_mod_files, m)?)?;
    // m.add_function(wrap_pyfunction!(batch_collect_mod_files, m)?)?;
    // m.add_function(wrap_pyfunction!(batch_collect_mod_files_multithread, m)?)?;
    m.add_class::<DefinitionExtractor>()?;
    Ok(())
}

