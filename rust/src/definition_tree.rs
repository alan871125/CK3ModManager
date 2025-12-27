use pyo3::prelude::*;
use pyo3::intern;
use pyo3::basic::CompareOp;
use pyo3::types::{PyAny, PyList, PyModule};
use pyo3::exceptions::PyKeyError;
use indexmap::{IndexMap, IndexSet};
use core::hash;
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::{Arc, RwLock};
use log::warn;

use crate::indexed_ordered_dict::IndexedOrderedMap;
pub type NodeId = u32;

const NON_CONFLICTING_KEYWORDS: [&str; 1] = [
    "namespace"
];
pub struct BaseNodeDraft{ // NOT USED NOW
    name: String,
    rel_dir: PathBuf,
    value: Option<String>,
    node_type: NodeType,
    sources: IndexSet<NodeId>,
}
#[derive(Clone)]
pub struct BaseNode {
    id: NodeId,
    parent: Option<NodeId>,
    // children: Vec<NodeId>,
    children: IndexMap<String, NodeId>,
    node_type: NodeType,
    value: Option<String>,
    // conflict: bool,
    sources: Arc<RwLock<IndexSet<NodeId>>>,    
    name: Arc<RwLock<String>>,
    rel_dir: Arc<RwLock<PathBuf>>,
    start_point: Option<(usize,usize)>,
}
impl BaseNode {
    pub fn get(&self, key: &str) -> Option<NodeId> {
        self.children.get(key).cloned()
    }
    
    pub fn get_name(&self) -> String {
        self.name.read().unwrap().clone()
    }
    pub fn get_rel_dir(&self) -> PathBuf {
        self.rel_dir.read().unwrap().clone()
    }
    pub fn has_conflict(&self)-> bool {
        self.sources.read().unwrap().len() > 1
    }
}
#[derive(Clone)]
pub struct ModData {
    pub load_order: u32,
    pub enabled: bool,
    pub name: String,
    pub node_id: NodeId,
    pub path: PathBuf,
}
pub struct Arena {
    nodes: Vec<BaseNode>,
    library: IndexMap<String, Vec<NodeId>>, // name to NodeId mapping
    pub mod_data: IndexedOrderedMap<NodeId, ModData>, // placeholder for future mod-related data
    // mod_name: (enabled, load_order, NodeId)
}
impl Arena{
    pub fn new() -> Self {
        Arena {
            nodes: Vec::new(),
            library: IndexMap::default(),
            mod_data: IndexedOrderedMap::default(),
        }
    }
    pub fn new_node(&mut self, name:String, rel_dir:PathBuf, value:Option<String>)-> NodeId {
        let node_id = self.nodes.len() as NodeId;
        let node_type = get_node_type(name.clone(), rel_dir.clone(), &value, None);
        let node = BaseNode {
            id: node_id,
            name: Arc::new(RwLock::new(name.clone())),
            rel_dir: Arc::new(RwLock::new(rel_dir)),
            node_type,
            value,
            parent: None,
            children: IndexMap::new(),
            sources: Arc::new(RwLock::new(IndexSet::new())),
            start_point: None,
        };
        if self.library.contains_key(&name){
            self.library.get_mut(&name).unwrap().push(node_id);
        } else {
            self.library.insert(name, vec![node_id]);
        }
        self.nodes.push(node);
        node_id
    }
    fn new_typed_node(&mut self, name:String, rel_dir:PathBuf, value:Option<String>, node_type:NodeType)-> NodeId {
        let node_id = self.nodes.len() as NodeId;
        let node = BaseNode {
            id: node_id,
            name: Arc::new(RwLock::new(name)),
            rel_dir: Arc::new(RwLock::new(rel_dir)),
            node_type,
            value,
            parent: None,
            children: IndexMap::new(),
            sources: Arc::new(RwLock::new(IndexSet::new())),
            start_point: None,
        };
        self.nodes.push(node);
        node_id
    }
    pub fn add_draft_node(&mut self, draft:BaseNodeDraft) -> NodeId {
        let node_id = self.nodes.len() as NodeId;
        let node = BaseNode {
            id: node_id,
            name: Arc::new(RwLock::new(draft.name)),
            rel_dir: Arc::new(RwLock::new(draft.rel_dir)),
            node_type: draft.node_type,
            value: draft.value,
            parent: None,
            children: IndexMap::new(),
            sources: Arc::new(RwLock::new(draft.sources)),
            start_point: None,
        };
        self.nodes.push(node);
        node_id
    }
    pub fn new_mod(&mut self, name:String, enabled:bool, load_order:u32, path:PathBuf){
        let node_id = self.new_typed_node(
            name.clone(),
            PathBuf::new(), 
            None,
            NodeType::Mod,
        );
        let mod_data = ModData{
            load_order,
            enabled,
            name: name.clone(),
            node_id,
            path,
        };
        self.mod_data.insert(node_id, mod_data);
    }
    pub fn get(&self, id:NodeId) -> &BaseNode {
        &self.nodes[id as usize]
    }
    pub fn get_mut(&mut self, id:NodeId) -> &mut BaseNode {
        &mut self.nodes[id as usize]
    }
    pub fn get_by_name(&self, name:String) -> Option<&Vec<NodeId>> {
        self.library.get(&name)
    }
    pub fn set_source(&mut self, id:NodeId, source_id: NodeId){
        // let source_name = self.nodes[source_id as usize].get_name();
        let node: &mut BaseNode = &mut self.nodes[id as usize];
        node.sources.write().unwrap().insert(source_id);
    }
    pub fn set_parent(&mut self, id:NodeId, parent_id: NodeId){
        let node: &mut BaseNode = &mut self.nodes[id as usize];
        node.parent = Some(parent_id);
    }
    pub fn set_child(&mut self, parent:NodeId, key: String, value: NodeId, set_source:bool){
        let parent_node:&BaseNode=self.get(parent);
        let value_node: &BaseNode=self.get(value);
        assert!(
            parent_node.node_type==NodeType::Virtual||
            value_node.node_type==NodeType::Virtual||
            parent_node.node_type>=value_node.node_type, 
            "Parent node type({}) must be >= child node type({})\nParent: {:?}\nChild: {:?}", 
            parent_node.node_type.as_str(), value_node.node_type.as_str(), 
            parent_node.get_rel_dir().join(parent_node.get_name()), 
            value_node.get_rel_dir().join(value_node.get_name())
        );
        
        let should_set_source = set_source 
            && value_node.node_type <= NodeType::File
            &&(parent_node.node_type == NodeType::Mod 
            || parent_node.node_type == NodeType::File);
        let should_set_parent = parent_node.node_type!=NodeType::Virtual;        
        if should_set_source {
            // only Mod/File nodes can be sources,
            // Sources are used to track which mod/file a node comes from
            self.set_source(value.clone(), parent.clone());
        }
        if should_set_parent {
            self.set_parent(value, parent);
        }
        
           
        self.nodes[parent as usize].children.insert(key, value);
    }
    pub fn set_node_start_point(&mut self, id:NodeId, line: usize, col:usize){
        let node: &mut BaseNode = &mut self.nodes[id as usize];
        node.start_point = Some((line, col));
    }
    pub fn extend(&mut self, other: &Arena){
        let base_len = self.nodes.len() as NodeId;
        for _node in &other.nodes {
            let mut node = _node.clone();
            node.id += base_len;
            if let Some(parent_id) = node.parent {
                node.parent = Some(parent_id + base_len);
            }
            for (_, child_id) in node.children.iter_mut() {
                *child_id += base_len;
            }
            {
                let old_sources = node.sources.read().unwrap().clone();
                let mut new_sources = IndexSet::new();
                for source_id in old_sources.iter() {
                    new_sources.insert(*source_id + base_len);
                }
                node.sources = Arc::new(RwLock::new(new_sources));
            }
            self.library.entry(node.get_name()).or_default().push(node.id);
            self.nodes.push(node);
        }
    }
    pub fn len(&self) -> usize {
        self.nodes.len()
    }
    
}

#[pyclass(module = "mod_analyzer.mod.paradox")]
#[derive(Clone, PartialEq, PartialOrd)]
pub enum NodeType{
    Value, // the node that holds a value (or array) as a string
    Identifier, // nodes extracted from files
    File,
    Directory,
    Mod, // a mod is a super type of directory
    Virtual, // a node that doesn't correspond to a file or directory, ex: <root>, <def>, <loc>
}
impl NodeType {
    pub fn as_str(&self) -> &str {
        match self {
            NodeType::Virtual => "Virtual",
            NodeType::Mod => "Mod",
            NodeType::Directory => "Directory",
            NodeType::File => "File",
            NodeType::Identifier => "Identifier",
            NodeType::Value => "Value",
        }
    }
}

#[pymethods]
impl NodeType {
    fn __repr__(&self) -> String {
        format!("NodeType.{}", self.as_str())
    }

    fn __str__(&self) -> &str {
        self.as_str()
    }

    fn __richcmp__(&self, other: &Self, op: CompareOp) -> PyResult<bool> {
        match op {
            CompareOp::Eq => Ok(self == other),
            CompareOp::Ne => Ok(self != other),
            CompareOp::Lt => Ok(self < other),
            CompareOp::Le => Ok(self <= other),
            CompareOp::Gt => Ok(self > other),
            CompareOp::Ge => Ok(self >= other),
        }
    }

    fn __hash__(&self) -> u64 {
        match self {
            NodeType::Value => 0,
            NodeType::Identifier => 1,
            NodeType::File => 2,
            NodeType::Directory => 3,
            NodeType::Mod => 4,
            NodeType::Virtual => 5,
        }
    }
}
fn get_node_type(name:String, rel_dir:PathBuf, value: &Option<String>, node_type: Option<String>) -> NodeType{
    if value.is_some(){ // node with value is always ValueNode
        return NodeType::Value
    }
    if let Some(ntype_str) = node_type{
        return match ntype_str.as_str(){
            "Virtual"   => NodeType::Virtual,
            "Mod"       => NodeType::Mod,
            "Directory" => NodeType::Directory,
            "File"      => NodeType::File,
            "Identifier"=> NodeType::Identifier,
            "Value"     => NodeType::Value,
            _           => NodeType::Identifier,
        }
    }

    // NOTE: This tree is often virtual and doesn't necessarily correspond to real filesystem paths.
    // Avoid Path::is_dir/is_file (which hits the filesystem and is non-deterministic).
    if name.starts_with('<') && name.ends_with('>'){ // ex: <root>, <def>, <loc>
        return NodeType::Virtual;
    }
    // Treat the root with empty rel_dir as a virtual root.
    if rel_dir.as_os_str().is_empty() {
        return NodeType::Virtual;
    }
    // If the name has a well-known file extension, treat it as a File node.
    // (Identifiers in CK3 frequently contain dots, e.g. capital_county.culture, so we must not
    // classify all dotted names as File.)
    if let Some(ext) = PathBuf::from(&name).extension().and_then(|e| e.to_str()) {
        let ext = ext.to_ascii_lowercase();
        if matches!(ext.as_str(), "txt" | "yml" | "yaml" | "gui" | "csv" | "dds" | "json" | "mod") {
            return NodeType::File;
        }
    }
    // If rel_dir points to a file (has an extension):
    // - the node whose name equals the file name is the File node
    // - everything beneath that is an Identifier/Value hierarchy under that file
    if let Some(ext) = PathBuf::from(&rel_dir).extension().and_then(|e| e.to_str()) {
        let ext = ext.to_ascii_lowercase();
        if matches!(ext.as_str(), "txt" | "yml" | "yaml" | "gui" | "csv" | "dds" | "json" | "mod") {
            return NodeType::Identifier;
        }
    }
    // if rel_dir.extension().is_some() {
    //     let rel_file_name = rel_dir
    //         .file_name()
    //         .and_then(|s| s.to_str())
    //         .unwrap_or("");
    //     if rel_file_name == name {
    //         return NodeType::File;
    //     }
    //     return NodeType::Identifier;
    // }

    // Default: Directory-like node.
    NodeType::Directory
}

#[pyclass]
pub struct ParadoxModDefinitionTree {
    pub arena: Arc<RwLock<Arena>>,
    pub root: NodeId,
}
#[pymethods]
impl ParadoxModDefinitionTree{
    #[new]
    pub fn new()-> Self {
        let mut arena = Arena::new();
        let root_id = arena.new_node("<root>".to_string(), PathBuf::new(), None);
        ParadoxModDefinitionTree {
            arena: Arc::new(RwLock::new(arena)),
            root: root_id,
        }        
    }
    fn get_node_num(&self) -> usize {
        self.arena.read().unwrap().nodes.len()
    }
    #[getter]
    pub fn get_root(&self) -> DefinitionNode {
        DefinitionNode {
            arena: self.arena.clone(),
            id: self.root,
        }
    }
    #[pyo3(signature = (name, rel_dir, value=None))]
    pub fn new_node(&mut self, name:String, rel_dir:PathBuf, value:Option<String>)-> DefinitionNode {
        let mut arena = self.arena.write().unwrap();
        let node_id = arena.new_node(name, rel_dir, value);
        DefinitionNode {
            arena: self.arena.clone(),
            id: node_id,
        }
    }
    pub fn get_node(&self, id:NodeId) -> DefinitionNode {
        DefinitionNode {
            arena: self.arena.clone(),
            id,
        }
    }
}
#[pyclass(module = "mod_analyzer.mod.paradox", subclass)]
#[derive(Clone)]
pub struct DefinitionNode {    
    pub arena: Arc<RwLock<Arena>>,
    #[pyo3(get)]
    pub id: NodeId,
}
#[pymethods]
impl DefinitionNode {    
    // This struct should only be created via PyTree methods
    
    #[getter(name)]
    fn get_name(&self) -> String {
        self.with_base_node(|node| node.name.read().unwrap().clone())
    }
    #[setter(name)]
    fn set_name(&mut self, name: String) -> PyResult<()> {
        let arena = self.arena.read().unwrap();
        *arena.get(self.id).name.write().unwrap() = name;
        Ok(())
    }
    #[getter]
    fn get_type(&self) -> NodeType {
        self.with_base_node(|node| node.node_type.clone())
    }
    #[getter]
    fn get_parent(&self) -> Option<DefinitionNode> {
        self.with_base_node(|node| {
            node.parent.as_ref().map(|parent_id| DefinitionNode {
                arena: self.arena.clone(),
                id: *parent_id,
            })
        })
    }
    #[getter]
    pub fn get_value(&self) -> Option<String> {
        self.with_base_node(|node| node.value.clone())
    }
    #[getter(rel_dir)]
    fn py_get_rel_dir<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let rel_dir_str = self.get_rel_dir().to_string_lossy().to_string();
        let pathlib = PyModule::import(py, intern!(py, "pathlib"))?;
        let path_cls = pathlib.getattr(intern!(py, "Path"))?;
        let path_obj = path_cls.call1((rel_dir_str,))?;
        Ok(path_obj)
    }
    #[getter(full_path)]
    fn py_get_full_path<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let arena = self.arena.read().unwrap();
        let source = self.get_super_source_by_type(NodeType::Mod).unwrap();
        // let mod_data = arena.mod_data.get(&source.id).unwrap();
        let mod_path = arena.mod_data.get(&source.id).unwrap().path.clone();
        let full_path = mod_path
                                    .join(self.get_rel_dir())
                                    .join(self.get_name());
        let pathlib = PyModule::import(py, intern!(py, "pathlib"))?;
        let path_cls = pathlib.getattr(intern!(py, "Path"))?;
        let path_obj = path_cls.call1((full_path.to_string_lossy().to_string(),))?;
        if self.get_sources().len()>1{
            warn!("[{}.get_full_path] Node has multiple sources (conflict): {:?}, sources: {:?}", 
                self.__repr__()?,
                full_path,
                self.get_sources().iter().map(|s| s.get_rel_dir().join(s.get_name())).collect::<Vec<PathBuf>>(),
            );
        }
        Ok(path_obj)
    }

    pub fn get_rel_dir(&self) -> PathBuf {
        self.with_base_node(|node| node.rel_dir.read().unwrap().clone())
    }    
    #[setter(rel_dir)]
    pub fn set_rel_dir(&mut self, rel_dir: &Bound<'_, PyAny>) -> PyResult<()> {
        let py = rel_dir.py();
        let pathlib = PyModule::import(py, intern!(py, "pathlib"))?;
        let path_cls = pathlib.getattr(intern!(py, "Path"))?;
        let path_obj = path_cls.call1((rel_dir,))?;
        let os_path = path_obj.call_method0(intern!(py, "as_posix"))?;
        let os_path_str: String = os_path.extract()?;
        let arena = self.arena.read().unwrap();
        *arena.get(self.id).rel_dir.write().unwrap() = PathBuf::from(os_path_str);
        Ok(())
    }    
    #[getter]
    pub fn get_start_point(&self)-> Option<(usize,usize)>{
        self.with_base_node(|node| node.start_point)
    }
    #[getter]
    pub fn get_line(&self) -> Option<usize>{
        self.with_base_node(|node| {
            match node.start_point {
                Some((line, _col)) => Some(line),
                None => None,
            }
        })
    }
    #[getter] // return the last ordered source
    pub fn get_source(&self) -> Option<DefinitionNode> {
        self.with_base_node(|node| {
            let sources = node.sources.read().unwrap();
            if sources.is_empty(){
                return None;
            }
            let source_id = sources.last().unwrap();
            Some(DefinitionNode {
                arena: self.arena.clone(),
                id: *source_id,
            })
        })
    }
    #[getter]
    pub fn get_sources(&self) -> Vec<DefinitionNode> {
        // self.with_base_node(|node| node.sources.map.keys().cloned().collect())
        self.with_base_node(|node| {
            let sources = node.sources.read().unwrap();
            sources.iter().map(|source_id| DefinitionNode {
                arena: self.arena.clone(),
                id: *source_id,
            }).collect()
        })
    }
    #[getter]
    pub fn get_mod_sources(&self) -> Vec<DefinitionNode> {
        // Gets the (unique) super sources of type Mod.
        // A node can have multiple sources (conflicts). Each source might be a File/Directory/etc;
        // we walk up its source chain until we hit the owning Mod.
        let mut seen: HashSet<NodeId> = HashSet::new();
        let mut mods: Vec<DefinitionNode> = Vec::new();

        for source in self.get_sources() {
            let mod_sources = if source.get_type() == NodeType::Mod {
                match Some(source) {
                    Some(m) => vec![m],
                    None => vec![]
                }
            } else {
                source.get_super_sources_by_type(NodeType::Mod)
            };
            for mod_source in mod_sources {
                if !seen.contains(&mod_source.id) {
                    seen.insert(mod_source.id);
                    mods.push(mod_source);
                }
            }
        }
        mods
    }
    pub fn get_super_source_by_type(&self, source_type: NodeType) -> Option<DefinitionNode> {
        // Recursively check sources for a source of the given type
        let source_obj = self.get_source();
        let source = match source_obj {
            Some(obj) => obj,
            _=>return None, // no source to add, no conflict
        };        
        if source.get_type() == source_type {
            Some(source)
        } else {
            source.get_super_source_by_type(source_type)
        } // check sources recursively
    }
    pub fn get_super_sources_by_type(&self, source_type: NodeType) -> Vec<DefinitionNode> {
        // Recursively check sources for sources of the given type
        let mut results: Vec<DefinitionNode> = Vec::new();
        for source in self.get_sources() {
            if source.get_type() == source_type {
                results.push(source);
            } else {
                let mut super_sources = source.get_super_sources_by_type(source_type.clone());
                results.append(&mut super_sources);
            }
        }
        results
    }
    pub fn set_source(&mut self, source: DefinitionNode){
        let source_type = source.get_type();
        let self_type = self.get_type();
        assert!(source.get_type() != NodeType::Virtual, "Cannot set source to Virtual node");
        // Some call sites may attach sources at different granularities (e.g. file, identifier, value).
        // Don't panic in production if the ordering doesn't match expectations; log and continue.
        if !(source_type <= self_type) {
            eprintln!(
                "[BaseNode.set_source] unexpected type order: source={} target={}; source_name={} target_name={}",
                source_type.as_str(),
                self_type.as_str(),
                source.get_name(),
                self.get_name(),
            );
        }
        let mut arena = self.arena.write().unwrap();
        arena.set_source(self.id, source.id);
    }
    pub fn has_conflict(&self)-> bool {
        self.with_base_node(|node| node.sources.read().unwrap().len() > 1)
    }
    #[pyo3(signature = (key, default=None))]
    pub fn get(&self, key: &str, default: Option<DefinitionNode>) -> Option<DefinitionNode> {
        self.with_base_node(|node| {
            match node.children.get(key) {
                Some(id) => Some(DefinitionNode {
                    arena: self.arena.clone(),
                    id: *id,
                }),
                None => default,
            }
        })
    }
    #[pyo3(signature = (dir, default=None))]
    pub fn get_by_dir(&self, dir:PathBuf, default: Option<DefinitionNode>)-> Option<DefinitionNode>{
        let mut curr_id = self.id;
        let arena = self.arena.read().unwrap();
        for part in dir.iter(){
            // skip "./"
            if part == "."{
                continue;
            }
            let current:&BaseNode = &arena.nodes[curr_id as usize];
            let part_str = part.to_string_lossy();
            if current.children.get(part_str.as_ref()).is_none(){
                return default;
            }else{
                curr_id = current.children.get(part_str.as_ref()).unwrap().clone();
            }
        }
        Some(DefinitionNode{
            arena: self.arena.clone(),
            id: curr_id,
        })
    }

    // --- Dict Protocol Implementation ---    
    fn __getitem__(&self, key: &str) -> PyResult<DefinitionNode> {
        self.with_base_node(|node| {
            match node.children.get(key) {
                Some(id) => Ok(DefinitionNode {
                    arena: self.arena.clone(),
                    id: *id,
                }),
                None => Err(PyKeyError::new_err(key.to_string())),
            }
        })
    }

    fn __setitem__(&mut self, key: String, value: DefinitionNode) -> PyResult<()> {
        self.set(key, value, true);
        Ok(())
    }
    // fn __delitem__(&mut self, key: &str) -> PyResult<()> {
    //     match self.children.shift_remove(key) {
    //         Some(_) => Ok(()),
    //         None => Err(PyKeyError::new_err(key.to_string())),
    //     }
    // }
    fn __len__(&self) -> usize {
        self.with_base_node(|node| node.children.len())
    }

    fn __contains__(&self, key: &str) -> bool {
        self.with_base_node(|node| node.children.contains_key(key))
    }
    fn __hash__(&self) -> u64 {
        let name = self.get_name();
        let value = self.get_value().unwrap_or_default();
        let rel_dir = self.get_rel_dir().to_string_lossy().to_string();
        let mut h = std::collections::hash_map::DefaultHasher::new();
        // Combine relevant fields into the hash
        let hash_input = format!("{}|{}|{}", name, rel_dir, value);
        hash::Hash::hash(&hash_input, &mut h);
        hash::Hasher::finish(&h)
    }
    fn __bool__(&self) -> bool {
        true // All DefinitionNode instances are considered True
    }

    fn __eq__(&self, other: &DefinitionNode) -> bool {
        self.id == other.id && Arc::ptr_eq(&self.arena, &other.arena)
    }
    
    fn keys(&self) -> Vec<String> {
        // this is for Python only, use  
        self.with_base_node(|node| node.children.keys().cloned().collect())
    }
    
    fn values(&self) -> Vec<DefinitionNode> {
        self.with_base_node(|node| {
            node.children.iter().map(|(_, v)| DefinitionNode {
                arena: self.arena.clone(),
                id: *v,
            }).collect()
        })            
    }
    
    fn items(&self) -> Vec<(String, Py<PyAny>)> {
        Python::attach(|py| {
            self.with_base_node(|node| {
                node.children.iter().map(|(k, v)| {
                    let node_ref = DefinitionNode {
                        arena: self.arena.clone(),
                        id: *v,
                    };
                    let node_obj = Py::new(py, node_ref).unwrap();
                    (k.clone(), node_obj.into_any())
                }).collect()
            })
        })
    }
    #[pyo3(signature = (key, default=None))]
    pub fn setdefault(&mut self, key: String, default: Option<DefinitionNode>) -> DefinitionNode {
        let arena = self.arena.read().unwrap();
        if let Some(existing) = arena.get(self.id).get(&key) {
            DefinitionNode {
                arena: self.arena.clone(),
                id: existing,
            }
        } else {
            drop(arena); // Release read lock before acquiring write lock
            let id = self.id;
            let mut arena = self.arena.write().unwrap();
            let value:NodeId = match default {
                Some(d) => {
                    d.id
                },
                None => {
                    let rel_dir = arena.get(id).get_rel_dir(); // prevent borrowing issues
                    arena.new_node(
                        key.clone(), rel_dir.join(&key), None,
                    )
                }
            };
            arena.set_child(self.id, key.clone(), value, true);
            DefinitionNode {
                arena: self.arena.clone(),
                id: value,
            }
        }
    }
    pub fn setdefault_by_dir(&mut self,  dir: PathBuf, default_name:String) -> DefinitionNode {
        let parts: Vec<String> = dir
            .iter()
            .map(|c| c.to_string_lossy().to_string())
            .collect();

        if parts.is_empty() {
            return self.clone();
        }
        let mut curr_id = self.id;
        let mut arena = self.arena.write().unwrap();
        for (i, key) in parts.iter().enumerate() {
            let is_last = i == parts.len() - 1;
            let existing_child = arena.get(curr_id).children.get(key).cloned();

            let next_id = match existing_child {
                Some(child_id) => child_id,
                None => {
                    let current_rel_dir = arena.get(curr_id).get_rel_dir();
                    let node_name = if is_last {
                        default_name.clone()
                    } else {
                        key.clone()
                    };
                    let node_id = arena.new_node(node_name, current_rel_dir.join(key), None);
                    arena.set_child(curr_id, key.clone(), node_id, true);
                    node_id
                }
            };

            curr_id = next_id;
        }
        DefinitionNode {
            arena: self.arena.clone(),
            id: curr_id,
        }
    }
    pub fn set_by_dir(&mut self,  dir: PathBuf, value: DefinitionNode){
        let parts: Vec<String> = dir
            .iter()
            .map(|c| c.to_string_lossy().to_string())
            .collect();

        if parts.is_empty() {
            return;
        }
        let mut curr_id = self.id;
        let mut arena = self.arena.write().unwrap();
        for (i, key) in parts.iter().enumerate() {
            let is_last = i == parts.len() - 1;
            let existing_child = arena.get(curr_id).children.get(key).cloned();

            let next_id = match existing_child {
                Some(child_id) => child_id,
                None => {
                    let node_id = if is_last {
                        value.id
                    } else {
                        let current_rel_dir = arena.get(curr_id).get_rel_dir();
                        arena.new_node(key.clone(), current_rel_dir.join(key), None)
                    };
                    arena.set_child(curr_id, key.clone(), node_id, true);
                    node_id
                }
            };
            curr_id = next_id;
        }
    }

    // fn __or__(&self, value: PyNode) -> PyNode{
    // Probably want to avoid this operator since it creates a new node
    // }
    
    fn __ior__(&mut self, value: DefinitionNode) -> PyResult<()> {
        self.update(value);
        Ok(())
    }
    pub fn update(&mut self, other: DefinitionNode){
        // Get other's children first while holding its read lock
        let other_children: Vec<(String, NodeId)> = other.with_base_node(|node| {
            node.children.iter().map(|(k, v)| (k.clone(), *v)).collect()
        });
        
        // Now acquire write lock on self's arena
        let mut arena = self.arena.write().unwrap();
        for (key, val) in other_children {
            arena.set_child(self.id, key, val, true);
        }
    }
    pub fn update_with_conflict_check(&mut self, other: &DefinitionNode)->HashSet<PathBuf>{
        // This method is used to merge two BaseNodes, and check for conflicts
        // updates the current node with another node's children,
        // update the sources as well
        // 
        // Returns: HashSet<NodeId> - the IDs of the nodes that were in conflict
        let id = self.id;
        let mut conflicts: HashSet<PathBuf> = HashSet::new();  
        
        // Get other's children first while holding its read lock
        let other_children: Vec<(String, NodeId)> = other.with_base_node(|node| {
            node.children.iter().map(|(k, v)| (k.clone(), *v)).collect()
        });

        let mut arena = self.arena.write().unwrap();

        for (key, other_id) in other_children {
            let existing_child_id = arena.get(id).children.get(&key).cloned();
            if let Some(exist_id) = existing_child_id {
                if exist_id != other_id {
                    let exist_sources_lock = arena.get(exist_id).sources.clone();
                    let other_sources_lock = arena.get(other_id).sources.clone();

                    if !Arc::ptr_eq(&exist_sources_lock, &other_sources_lock) {
                        let mut existing_sources = exist_sources_lock.write().unwrap();
                        let new_sources = other_sources_lock.read().unwrap();

                        if *existing_sources != *new_sources && !NON_CONFLICTING_KEYWORDS.contains(&key.as_str()) {
                            // conflict detected
                            
                            let rel_dir = arena.get(id).get_rel_dir();
                            conflicts.insert(rel_dir.join(&key));
                            // println!("{}", rel_dir.join(&key).display());
                            
                            existing_sources.extend(new_sources.iter());
                            drop(existing_sources);
                            drop(new_sources);
                            
                            // Share the sources lock
                            arena.get_mut(other_id).sources = exist_sources_lock;

                            let child: &BaseNode = arena.get(exist_id);
                            let other_child: &BaseNode = arena.get(other_id);
                            assert!(child.has_conflict()&&other_child.has_conflict(), 
                                "Conflict expected but not found for node: {:?}, sources: {:?}", 
                                child.get_rel_dir().join(&child.get_name()),
                                child.sources.read().unwrap().iter().collect::<Vec<&NodeId>>(),
                            );
                        }
                    }
                }

            }
            arena.set_child(id, key, other_id, true);
        }
        conflicts
    }
    fn __iter__(&self) -> PyResult<Py<PyAny>> {
        Python::attach(|py| {
            let keys: Vec<String> = self.keys();
            let list = PyList::new(py, keys).unwrap();
            // Get iterator by calling __iter__ on the list
            let iter_bound = list.call_method0("__iter__")?;
            Ok(iter_bound.unbind())
        })
    }
    
    fn __getnewargs__(&self) -> PyResult<(String, String)> {
        Ok((self.get_name(), self.get_rel_dir().to_string_lossy().to_string()))
    }
    fn __getstate__(&self, _py: Python){
        
    }

    fn __setstate__(&mut self, _py: Python) -> PyResult<()> {
        Ok(())
    }
    fn __repr__(&self) -> PyResult<String> {
        let name = self.get_name();
        let rel_dir = self.get_rel_dir();
        Ok(format!(
            "{}Node(name='{}', rel_dir='{}', #children={})",
            self.get_type().as_str(),
            name,
            rel_dir.display(), // rel_dir to string
            self.__len__()
        ))
    }   

    #[pyo3(signature = (indent=0))]
    pub fn pretty_print(&self, indent: usize){
        if self.get_type() == NodeType::Value {
            println!("{}", self.get_value().unwrap_or_default());
            return;
        }
        println!();
        let children_vec: Vec<(String, NodeId)> = self.with_base_node(|node| {
            node.children.iter().map(|(k, v)| (k.clone(), *v)).collect()
        });
        for (key, child_id) in children_vec {
            let child_node = DefinitionNode {
                arena: self.arena.clone(),
                id: child_id,
            };
            print!("{}", "    ".repeat(indent));
            print!("{}: ", key);
            child_node.pretty_print(indent + 1);
        }
    }
}
impl DefinitionNode {
    fn with_base_node<F, R>(&self, f: F) -> R 
    where F: FnOnce(&BaseNode) -> R
    {
        let arena = self.arena.read().unwrap();
        f(arena.get(self.id))
    }
    pub fn set(&mut self, key: String, value: DefinitionNode, set_source:bool){
        let mut arena = self.arena.write().unwrap();
        arena.set_child(self.id, key, value.id, set_source);
    }
}

