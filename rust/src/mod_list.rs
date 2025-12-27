use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use pyo3::exceptions::{PyKeyError, PyIndexError};
use std::collections::HashMap;
use indexmap::IndexMap;

#[pyclass(subclass)]
pub struct BaseNode {
    #[pyo3(get, set)]
    name: String,
    #[pyo3(get, set)]
    rel_dir: String,
    #[pyo3(get, set)]
    sources: HashMap<String, PyObject>,
    #[pyo3(get, set)]
    parent: Option<PyObject>,
    
    // High-performance internal storage
    // Using String keys avoids GIL overhead during lookups/hashing
    children: IndexMap<String, PyObject>,
    
}

#[pymethods]
impl BaseNode {
    #[new]
    fn new(name: String, rel_dir: String) -> Self {
        BaseNode {
            name,
            rel_dir,
            children: IndexMap::new(),
            sources: HashMap::new(),
            parent: None,
        }
    }

    // --- Dict Protocol Implementation ---    
    fn __getitem__(&self, key: &str) -> PyResult<PyObject> {
        match self.children.get(key) {
            Some(val) => Ok(val.clone()),
            None => Err(PyKeyError::new_err(key.to_string())),
        }
    }

    fn __setitem__(mut slf: PyRefMut<Self>, key: String, value: PyObject) -> PyResult<()> {
        let py = slf.py();
        
        // 1. Validate and borrow child (ensure it's a BaseNode)
        // We hold this borrow until the end to set the parent
        let mut child: PyRefMut<BaseNode> = value.extract(py).map_err(|_| {
            pyo3::exceptions::PyTypeError::new_err("Value must be a BaseNode instance")
        })?;

        // 2. Insert into children
        // We clone value (PyObject) to keep a reference in the map
        slf.children.insert(key, value.clone());

        // 3. Get self object (consumes slf borrow)
        let self_obj = slf.into_py(py);

        // 4. Set parent
        child.parent = Some(self_obj);

        Ok(())
    }
    fn __delitem__(&mut self, key: &str) -> PyResult<()> {
        match self.children.shift_remove(key) {
            Some(_) => Ok(()),
            None => Err(PyKeyError::new_err(key.to_string())),
        }
    }
    fn __len__(&self) -> usize {
        self.children.len()
    }

    fn __contains__(&self, key: &str) -> bool {
        self.children.contains_key(key)
    }
    
    fn keys(&self) -> Vec<String> {
        self.children.keys().cloned().collect()
    }
    
    fn values(&self) -> Vec<PyObject> {
        self.children.values().cloned().collect()
    }
    
    fn items(&self) -> Vec<(String, PyObject)> {
        self.children.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
    }

    fn __iter__(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let keys: Vec<String> = self.children.keys().cloned().collect();
            let list = PyList::new(py, keys);
            let iter = list.as_ref().iter()?;
            Ok(iter.to_object(py))
        })
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!(
            "BaseNode(name='{}', rel_dir='{}', children_count={})",
            self.name,
            self.rel_dir,
            self.children.len()
        ))
    }
}

impl BaseNode {
    // Optional: Helper to get children as a Rust reference for internal processing
    // (Not exposed to Python)
    pub fn get_children_internal(&self) -> &IndexMap<String, PyObject> {
        &self.children
    }
}

