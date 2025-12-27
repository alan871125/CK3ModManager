use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::PathBuf;
use std::collections::HashMap;
use std::fs;
use std::io::Write;

/// Represents a CK3 mod with metadata.
/// See https://ck3.paradoxwikis.com/Mod_structure for details
#[pyclass]
#[derive(Clone, Debug)]
pub struct Mod {
    #[pyo3(get, set)]
    pub load_order: i32,
    
    #[pyo3(get, set)]
    pub enabled: bool,
    
    #[pyo3(get, set)]
    pub name: String,
    
    #[pyo3(get, set)]
    pub version: String,
    
    #[pyo3(get, set)]
    pub path: PathBuf,
    
    #[pyo3(get, set)]
    pub tags: Vec<String>,
    
    #[pyo3(get, set)]
    pub supported_version: Option<String>,
    
    #[pyo3(get, set)]
    pub remote_file_id: Option<String>,
    
    #[pyo3(get, set)]
    pub picture: Option<PathBuf>,
    
    #[pyo3(get, set)]
    pub replace_path: Option<PathBuf>,
    
    #[pyo3(get, set)]
    pub replaces: Vec<String>,
    
    #[pyo3(get, set)]
    pub dependencies: Vec<String>,
    
    #[pyo3(get, set)]
    pub file: Option<PathBuf>,
    
    // Internal fields
    enabled_first: bool,
    sort_index: i32,
    dup_id: i32,
}

#[pymethods]
impl Mod {
    #[new]
    #[pyo3(signature = (
        load_order=-1,
        enabled=false,
        name=String::new(),
        version=String::new(),
        path=None,
        tags=None,
        supported_version=None,
        remote_file_id=None,
        picture=None,
        replace_path=None,
        replaces=None,
        dependencies=None,
        file=None,
        enabled_first=false
    ))]
    fn new(
        load_order: i32,
        enabled: bool,
        name: String,
        version: String,
        path: Option<PathBuf>,
        tags: Option<Vec<String>>,
        supported_version: Option<String>,
        remote_file_id: Option<String>,
        picture: Option<PathBuf>,
        replace_path: Option<PathBuf>,
        replaces: Option<Vec<String>>,
        dependencies: Option<Vec<String>>,
        file: Option<PathBuf>,
        enabled_first: bool,
    ) -> Self {
        let sort_index = if enabled && enabled_first { 0 } else { 1 };
        Mod {
            load_order,
            enabled,
            name,
            version,
            path: path.unwrap_or_default(),
            tags: tags.unwrap_or_default(),
            supported_version,
            remote_file_id,
            picture,
            replace_path,
            replaces: replaces.unwrap_or_default(),
            dependencies: dependencies.unwrap_or_default(),
            file,
            enabled_first,
            sort_index,
            dup_id: 0,
        }
    }
    
    /// Set enabled status and update sort index
    #[setter]
    fn set_enabled(&mut self, value: bool) {
        self.enabled = value;
        if self.enabled_first {
            self.sort_index = if value { 0 } else { 1 };
        }
    }
    
    /// Get the duplicate ID
    #[getter]
    fn get_dup_id(&self) -> i32 {
        self.dup_id
    }
    
    /// Set the duplicate ID
    #[setter]
    fn set_dup_id(&mut self, value: i32) {
        self.dup_id = value;
    }
    
    /// Get the mod name with duplicate suffix if applicable
    #[getter]
    fn dup_name(&self) -> String {
        if self.dup_id > 0 {
            format!("{}#{}", self.name, self.dup_id)
        } else {
            self.name.clone()
        }
    }
    
    /// Convert to dictionary representation
    fn as_dict(&self) -> HashMap<String, String> {
        let mut dict = HashMap::new();
        dict.insert("load_order".to_string(), self.load_order.to_string());
        dict.insert("enabled".to_string(), self.enabled.to_string());
        dict.insert("name".to_string(), self.name.clone());
        dict.insert("version".to_string(), self.version.clone());
        dict.insert("path".to_string(), self.path.display().to_string());
        // Add more fields as needed
        dict
    }
    
    /// Check if the mod is outdated compared to the current game version
    fn is_outdated(&self, current_version: String) -> PyResult<bool> {
        if self.supported_version.is_none() {
            return Ok(false);
        }
        
        let supported = self.supported_version.as_ref().unwrap();
        let supported_parts: Vec<&str> = supported.trim().split('.').collect();
        let current_parts: Vec<&str> = current_version.split('.').collect();
        
        for (part0, part1) in supported_parts.iter().zip(current_parts.iter()) {
            match (part0.parse::<i32>(), part1.parse::<i32>()) {
                (Ok(num0), Ok(num1)) => {
                    if num0 < num1 {
                        return Ok(true);
                    } else if num0 > num1 {
                        return Ok(false);
                    }
                }
                _ => return Ok(false),
            }
        }
        
    
    fn __richcmp__(&self, other: &Self, op: pyo3::basic::CompareOp) -> PyResult<bool> {
        use pyo3::basic::CompareOp;
        
        // First compare by sort_index
        if self.sort_index != other.sort_index {
            return match op {
                CompareOp::Lt => Ok(self.sort_index < other.sort_index),
                CompareOp::Le => Ok(self.sort_index <= other.sort_index),
                CompareOp::Eq => Ok(false),
                CompareOp::Ne => Ok(true),
                CompareOp::Gt => Ok(self.sort_index > other.sort_index),
                CompareOp::Ge => Ok(self.sort_index >= other.sort_index),
            };
        }
        
        // If sort_index is equal, compare by load_order
        match op {
            CompareOp::Lt => Ok(self.load_order < other.load_order),
            CompareOp::Le => Ok(self.load_order <= other.load_order),
            CompareOp::Eq => Ok(self.load_order == other.load_order && self.sort_index == other.sort_index),
            CompareOp::Ne => Ok(self.load_order != other.load_order || self.sort_index != other.sort_index),
            CompareOp::Gt => Ok(self.load_order > other.load_order),
            CompareOp::Ge => Ok(self.load_order >= other.load_order),
        }
    }
    
    /// Save mod info to a descriptor file
    fn save_to_descriptor(&self, path: &str) -> PyResult<()> {
        let mut lines = Vec::new();
        
        lines.push(format!("name = \"{}\"", self.name));
        lines.push(format!("version = \"{}\"", self.version));
        lines.push(format!("path = \"{}\"", self.path.display().to_string().replace('\\', "/")));
        
        if !self.tags.is_empty() {
            let tags_str = self.tags.join("\", \"");
            lines.push(format!("tags={{\"{}\"}}",  tags_str));
        }
        
        if let Some(ref sv) = self.supported_version {
            lines.push(format!("supported_version = {}", sv));
        }
        
        if let Some(ref rfid) = self.remote_file_id {
            if !rfid.is_empty() {
                lines.push(format!("remote_file_id = \"{}\"", rfid));
            }
        }
        
        if let Some(ref pic) = self.picture {
            if pic.as_os_str().len() > 0 {
                lines.push(format!("picture = \"{}\"", pic.display().to_string().replace('\\', "/")));
            }
        }
        
        if let Some(ref rp) = self.replace_path {
            if rp.as_os_str().len() > 0 {
                lines.push(format!("replace_path = \"{}\"", rp.display().to_string().replace('\\', "/")));
            }
        }
        
        if !self.replaces.is_empty() {
            let replaces_str = self.replaces.join("\", \"");
            lines.push(format!("replaces = {{\"{}\"}}",  replaces_str));
        }
        
        if !self.dependencies.is_empty() {
            let deps_str = self.dependencies.join("\", \"");
            lines.push(format!("dependencies = {{\"{}\"}}",  deps_str));
        }
        
        let content = lines.join("\n");
        let mut file = fs::File::create(path)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Failed to create file: {}", e)))?;
        file.write_all(content.as_bytes())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(format!("Failed to write file: {}", e)))?;
        
        Ok(())
    }
    
    /// Load mod info from a descriptor file
    /// 
    /// Note: This is a simplified version. For full functionality,
    /// you may want to call the Python mod_loader.get_mod_info function
    fn load_from_descriptor(&mut self, py: Python, path: &str) -> PyResult<()> {
        // Import the Python module and call get_mod_info
        let mod_loader = py.import("mod_analyzer.mod.mod_loader")?;
        let get_mod_info = mod_loader.getattr("get_mod_info")?;
        
        let path_obj = PyModule::import(py, "pathlib")?.getattr("Path")?.call1((path,))?;
        let data: &PyDict = get_mod_info.call1((path_obj,))?.downcast()?;
        
        // Update fields from returned dictionary
        if let Ok(name) = data.get_item("name") {
            if let Some(name) = name {
                self.name = name.extract()?;
            }
        }
        if let Ok(version) = data.get_item("version") {
            if let Some(version) = version {
                self.version = version.extract()?;
            }
        }
        if let Ok(path) = data.get_item("path") {
            if let Some(path) = path {
                self.path = path.extract()?;
            }
        }
        if let Ok(tags) = data.get_item("tags") {
            if let Some(tags) = tags {
                self.tags = tags.extract()?;
            }
        }
        if let Ok(sv) = data.get_item("supported_version") {
            if let Some(sv) = sv {
                self.supported_version = sv.extract()?;
            }
        }
        if let Ok(rfid) = data.get_item("remote_file_id") {
            if let Some(rfid) = rfid {
                self.remote_file_id = rfid.extract()?;
            }
        }
        if let Ok(pic) = data.get_item("picture") {
            if let Some(pic) = pic {
                self.picture = pic.extract()?;
            }
        }
        if let Ok(rp) = data.get_item("replace_path") {
            if let Some(rp) = rp {
                self.replace_path = rp.extract()?;
            }
        }
        if let Ok(replaces) = data.get_item("replaces") {
            if let Some(replaces) = replaces {
                self.replaces = replaces.extract()?;
            }
        }
        if let Ok(deps) = data.get_item("dependencies") {
            if let Some(deps) = deps {
                self.dependencies = deps.extract()?;
            }
        }
        
        self.file = Some(PathBuf::from(path));
        
        // Check if path needs adjustment (relative path starting with "mod")
        if self.path.starts_with("mod") {
            let home = std::env::var("USERPROFILE")
                .or_else(|_| std::env::var("HOME"))
                .unwrap_or_default();
            let ck3_doc_dir = PathBuf::from(home)
                .join("Documents")
                .join("Paradox Interactive")
                .join("Crusader Kings III");
            self.path = ck3_doc_dir.join(&self.path);
            self.save_to_descriptor(path)?;
        }
        
        Ok(())
    }
        Ok(false)
    }
    
    fn __repr__(&self) -> String {
        format!(
            "Mod(load_order={}, enabled={}, name='{}', version='{}')",
            self.load_order, self.enabled, self.name, self.version
        )
    }
    
    fn __str__(&self) -> String {
        self.__repr__()
    }
    
    fn __hash__(&self) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        
        let mut hasher = DefaultHasher::new();
        self.name.hash(&mut hasher);
        self.path.hash(&mut hasher);
        hasher.finish()
    }
}
