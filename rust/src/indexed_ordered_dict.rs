use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hash, Hasher};

use indexmap::IndexMap;

use pyo3::exceptions::{PyKeyError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyIterator, PyList, PyTuple, PyType};

/// Internal, pure-Rust ordered map.
///
/// This lets other Rust code work with an indexed ordered map without being
/// forced into PyO3/Python types. The PyO3 `IndexedOrderedDict` wrapper below
/// is just a specialization of this container.
#[derive(Clone)]
pub struct IndexedOrderedMap<K, V, S = RandomState> {
    pub map: IndexMap<K, V, S>,
}

impl<K, V, S> Default for IndexedOrderedMap<K, V, S>
where
    S: BuildHasher + Default,
{
    fn default() -> Self {
        Self {
            map: IndexMap::with_hasher(S::default()),
        }
    }
}

impl<K, V> IndexedOrderedMap<K, V, RandomState>
where
    K: Eq + Hash,
{
    pub fn new() -> Self {
        Self {
            map: IndexMap::with_hasher(RandomState::new()),
        }
    }
}

impl<K, V, S> IndexedOrderedMap<K, V, S>
where
    K: Eq + Hash,
    S: BuildHasher,
{
    pub fn len(&self) -> usize {
        self.map.len()
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }

    pub fn clear(&mut self) {
        self.map.clear();
    }

    pub fn insert(&mut self, key: K, value: V) {
        self.map.insert(key, value);
    }

    pub fn get(&self, key: &K) -> Option<&V> {
        self.map.get(key)
    }

    pub fn get_mut(&mut self, key: &K) -> Option<&mut V> {
        self.map.get_mut(key)
    }

    pub fn shift_remove(&mut self, key: &K) -> Option<V> {
        self.map.shift_remove(key)
    }
    pub fn first(&self) -> Option<(&K, &V)> {
        self.map.first()
    }
    pub fn last(&self) -> Option<(&K, &V)> {
        self.map.last()
    }
    pub fn keys(&self) -> impl Iterator<Item = &K> {
        self.map.keys()
    }
    pub fn values(&self) -> impl Iterator<Item = &V> {
        self.map.values()
    }
    pub fn iter(&self) -> impl Iterator<Item = (&K, &V)> {
        self.map.iter()
    }
    pub fn update(&mut self, other: &IndexedOrderedMap<K, V, S>)
    where
        K: Clone,
        V: Clone,
        S: Clone,
    {
        for (k, v) in &other.map {
            self.map.insert(k.clone(), v.clone());
        }
    }
}

/// A wrapper around Py<PyAny> to implement Hash and Eq
pub struct KeyWrapper(Py<PyAny>);

impl KeyWrapper {
    fn clone_ref(&self, py: Python<'_>) -> Self {
        KeyWrapper(self.0.clone_ref(py))
    }
}

impl PartialEq for KeyWrapper {
    fn eq(&self, other: &Self) -> bool {
        Python::attach(|py| {
            // check if self.0 == other.0 in Python
            self.0.bind(py).eq(other.0.bind(py)).unwrap_or(false)
        })
    }
}
impl Eq for KeyWrapper {}
impl Hash for KeyWrapper {
    fn hash<H: Hasher>(&self, state: &mut H) {
        Python::attach(|py| {
            // use the hash of the PyObject in Python
            let h = self.0.bind(py).hash().unwrap_or(0);
            h.hash(state);
        })
    }
}

#[pyclass(module = "mod_analyzer.mod.paradox", subclass)]
pub struct IndexedOrderedDict {
    pub map: IndexedOrderedMap<KeyWrapper, Py<PyAny>, RandomState>,
}

impl Default for IndexedOrderedDict {
    fn default() -> Self {
        Self {
            map: IndexedOrderedMap::new(),
        }
    }
}

#[pymethods]
impl IndexedOrderedDict {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn __new__(
        _args: &Bound<'_, PyTuple>,
        _kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Self> {
        Ok(IndexedOrderedDict {
            map: IndexedOrderedMap::<KeyWrapper, Py<PyAny>, RandomState>::new(),
        })
    }
    #[pyo3(signature = (*args, **kwargs))]
    fn __init__(&mut self,_py: Python<'_>, args: &Bound<'_, PyTuple>, kwargs: Option<&Bound<'_, PyDict>>) -> PyResult<()> {
        let map = &mut self.map;
        
        if args.len() > 1 {
            return Err(PyTypeError::new_err(format!("IndexedOrderedDict expected at most 1 arguments, got {}", args.len())));
        }

        if let Ok(arg) = args.get_item(0) {
            if let Ok(dict) = arg.cast::<PyDict>() {
                for (k, v) in dict.iter() {
                    map.map.insert(KeyWrapper(k.unbind()), v.unbind());
                }
            } else if let Ok(iter) = (&arg).try_iter() {
                 for item in iter {
                     let item = item?;
                     if let Ok(tuple) = item.cast::<PyTuple>() {
                         if tuple.len() == 2 {
                             let k = tuple.get_item(0)?.unbind();
                             let v = tuple.get_item(1)?.unbind();
                             map.map.insert(KeyWrapper(k), v);
                         }
                     } else if let Ok(list) = item.cast::<PyList>() {
                          if list.len() == 2 {
                             let k = list.get_item(0)?.unbind();
                             let v = list.get_item(1)?.unbind();
                             map.map.insert(KeyWrapper(k), v);
                         }
                     }
                 }
            }
        }

        if let Some(kw) = kwargs {
            for (k, v) in kw.iter() {
                map.map.insert(KeyWrapper(k.unbind()), v.unbind());
            }
        }
        Ok(())
    }

    fn __len__(&self) -> usize {
        self.map.len()
    }

    fn __getitem__(&self, py: Python<'_>, key: Py<PyAny>) -> PyResult<Py<PyAny>> {
        match self.map.get(&KeyWrapper(key.clone_ref(py))) {
            Some(val) => Ok(val.clone_ref(py)),
            None => Err(PyKeyError::new_err(key)),
        }
    }

    fn __setitem__(&mut self, key: Py<PyAny>, value: Py<PyAny>) {
        self.map.insert(KeyWrapper(key), value);
    }

    fn __delitem__(&mut self, py: Python<'_>, key: Py<PyAny>) -> PyResult<()> {
        match self.map.shift_remove(&KeyWrapper(key.clone_ref(py))) {
            Some(_) => Ok(()),
            None => Err(PyKeyError::new_err(key)),
        }
    }

    fn __contains__(&self, key: Py<PyAny>) -> bool {
        self.map.map.contains_key(&KeyWrapper(key))
    }   

    fn __iter__(&self) -> PyResult<Py<PyIterator>> {
        Python::attach(|py| {
            let keys: Vec<Py<PyAny>> = self.map.map.keys().map(|k| k.0.clone_ref(py)).collect();
            let list = PyList::new(py, &keys)?;
            let iter = list.try_iter()?;
            Ok(iter.unbind())
        })
    }
    fn __eq__(&self, other: Py<PyAny>) -> PyResult<bool> {
        self.compare_with(other, |a, b| a.eq(b), true)
    }
    fn __ne__(&self, other: Py<PyAny>) -> PyResult<bool> {
        self.compare_with(other, |a, b| a.ne(b), true).map(|eq| !eq)
    }
    fn __or__(&self, value: Py<PyAny>) -> PyResult<IndexedOrderedDict> {
        Python::attach(|py| {
            let mut new_dict = self.copy();
            if let Ok(other_dict) = value.extract::<PyRef<IndexedOrderedDict>>(py) {
                for (k, v) in &other_dict.map.map {
                    new_dict.map.map.insert(k.clone_ref(py), v.clone_ref(py));
                }
                Ok(new_dict)
            } else if let Ok(other_dict) = value.bind(py).cast::<PyDict>() {
                for (k, v) in other_dict.iter() {
                    new_dict.map.map.insert(KeyWrapper(k.unbind()), v.unbind());
                }
                Ok(new_dict)
            } else {
                let type_name = value.bind(py).get_type();
                Err(PyTypeError::new_err(format!("unsupported operand type(s) for |: 'IndexedOrderedDict' and {}", type_name)))
            }
        })
    }
    fn __ior__(&mut self, m: &Bound<'_, PyDict>){
        for (k, v) in m.iter() {
            self.map.map.insert(KeyWrapper(k.unbind()), v.unbind());
        }
    }
    fn __reversed__(&self)-> PyResult<Py<PyIterator>> {
        Python::attach(|py| {
            let keys: Vec<Py<PyAny>> = self.map.map.keys().rev().map(|k| k.0.clone_ref(py)).collect();
            let list = PyList::new(py, &keys)?;
            let iter = list.try_iter()?;
            Ok(iter.unbind())
        })
    }
    fn update(&mut self, m: Py<PyAny>){
        Python::attach(|py| {
            if let Ok(other_dict) = m.extract::<PyRef<IndexedOrderedDict>>(py) {
                for (k, v) in &other_dict.map.map {
                    self.map.map.insert(k.clone_ref(py), v.clone_ref(py));
                }
            } else if let Ok(other_dict) = m.bind(py).cast::<PyDict>() {
                for (k, v) in other_dict.iter() {
                    self.map.map.insert(KeyWrapper(k.unbind()), v.unbind());
                }
            }
        });
    }
    fn keys(slf: PyRef<Self>) -> PyResult<Py<PyList>> {
        let py = slf.py();
        let keys: Vec<Py<PyAny>> = slf.map.map.keys().map(|k| k.0.clone_ref(py)).collect();
        PyList::new(py, &keys).map(|l| l.unbind())
    }

    fn values(slf: PyRef<Self>) -> PyResult<Py<PyList>> {
        let py = slf.py();
        let values: Vec<Py<PyAny>> = slf.map.map.values().map(|v| v.clone_ref(py)).collect();
        PyList::new(py, &values).map(|l| l.unbind())
    }

    fn items(slf: PyRef<Self>) -> PyResult<Py<PyList>> {
        let py = slf.py();
        let items: Vec<(Py<PyAny>, Py<PyAny>)> = slf
            .map
            .map
            .iter()
            .map(|(k, v)| (k.0.clone_ref(py), v.clone_ref(py)))
            .collect();
        PyList::new(py, &items).map(|l| l.unbind())
    }    
    fn clear(&mut self) {
        self.map.clear();
    }
    
    fn copy(&self) -> Self {
        Python::attach(|py| {
            let mut new_map = IndexedOrderedMap::<KeyWrapper, Py<PyAny>, RandomState>::new();
            for (k, v) in &self.map.map {
                new_map.map.insert(k.clone_ref(py), v.clone_ref(py));
            }
            IndexedOrderedDict { map: new_map }
        })
    }
    #[pyo3(signature = (key, default=None))]
    fn get(&self, py: Python<'_>, key: Py<PyAny>, default: Option<Py<PyAny>>) -> Option<Py<PyAny>> {
        match self.map.get(&KeyWrapper(key)) {
            Some(val) => Some(val.clone_ref(py)),
            None => default,
        }
    }

    #[pyo3(signature = (key, default=None))]
    fn pop(&mut self, py: Python<'_>, key: Py<PyAny>, default: Option<Py<PyAny>>) -> PyResult<Py<PyAny>> {
        match self.map.shift_remove(&KeyWrapper(key.clone_ref(py))) {
            Some(val) => Ok(val),
            None => {
                if let Some(d) = default {
                    Ok(d)
                } else {
                    Err(PyKeyError::new_err(key))
                }
            }
        }
    }

    #[pyo3(signature = (last=true))]
    fn popitem(&mut self, last: bool) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
        if self.map.is_empty() {
            return Err(PyKeyError::new_err("dictionary is empty"));
        }
        
        let (k, v) = if last {
            self.map.map.pop().unwrap()
        } else {
            self.map.map.shift_remove_index(0).unwrap()
        };
        Ok((k.0, v))
    }

    #[pyo3(signature = (key, default=None))]
    fn setdefault(&mut self, py: Python<'_>, key: Py<PyAny>, default: Option<Py<PyAny>>) -> Py<PyAny> {
        if let Some(val) = self.map.get(&KeyWrapper(key.clone_ref(py))) {
            return val.clone_ref(py);
        }
        let val = default.unwrap_or_else(|| py.None());
        self.map.insert(KeyWrapper(key), val.clone_ref(py));
        val
    }

    #[pyo3(signature = (key, last=true))]
    fn move_to_end(&mut self, py: Python<'_>, key: Py<PyAny>, last: bool) -> PyResult<()> {
        if let Some(index) = self.map.map.get_index_of(&KeyWrapper(key.clone_ref(py))) {
            if last {
                let new_index = self.map.len() - 1;
                self.map.map.move_index(index, new_index);
            } else {
                self.map.map.move_index(index, 0);
            }
            Ok(())
        } else {
            Err(PyKeyError::new_err(key))
        }
    }

    #[pyo3(signature = (*, key=None, reverse=false))]
    fn sort(mut slf: PyRefMut<Self>, py: Python<'_>, key: Option<Py<PyAny>>, reverse: bool) -> PyResult<()> {
        let keys: Vec<Py<PyAny>> = slf.map.map.keys().map(|k| k.0.clone_ref(py)).collect();
        let py_keys = PyList::new(py, &keys)?;
        
        let kwargs = PyDict::new(py);
        if let Some(k) = key {
            kwargs.set_item("key", k)?;
        }
        kwargs.set_item("reverse", reverse)?;

        // Use Python's sort to use custom key functions
        py_keys.call_method("sort", (), Some(&kwargs))?; 
        
        let mut new_map = IndexMap::with_capacity_and_hasher(slf.map.len(), RandomState::new());
        for key_obj in py_keys.iter() {
            let key_wrapper = KeyWrapper(key_obj.unbind());
            if let Some(value) = slf.map.map.swap_remove(&key_wrapper) {
                new_map.insert(key_wrapper, value);
            }
        }        
        slf.map.map = new_map;
        Ok(())
    }

    #[classmethod]
    #[pyo3(signature = (iterable, value=None))]
    fn fromkeys(_cls: &Bound<'_, PyType>, iterable: &Bound<'_, PyAny>, value: Option<Py<PyAny>>) -> PyResult<Self> {
        let py = iterable.py();
        let mut map = IndexedOrderedMap::<KeyWrapper, Py<PyAny>, RandomState>::new();
        for item in iterable.try_iter()? {
            let key = item?.unbind();
            let val = value.as_ref().map(|v| v.clone_ref(py)).unwrap_or_else(|| py.None());
            map.map.insert(KeyWrapper(key), val);
        }
        Ok(IndexedOrderedDict { map })
    }
    fn __getstate__(&self) -> PyResult<Py<PyTuple>> {
        Python::attach(|py| {
            let items: Vec<(Py<PyAny>, Py<PyAny>)> = self
                .map
                .map
                .iter()
                .map(|(k, v)| (k.0.clone_ref(py), v.clone_ref(py)))
                .collect();
            PyTuple::new(py, &items).map(|t| t.unbind())
        })
    }
    fn __setstate__(&mut self, state: &Bound<'_, PyAny>) -> PyResult<()> {
        let items = state.cast::<PyTuple>()?;
        self.map.clear();
        for item in items.iter() {
            let tuple = item.cast::<PyTuple>()?;
            if tuple.len() != 2 {
                return Err(PyTypeError::new_err("invalid state"));
            }
            let k = tuple.get_item(0)?.unbind();
            let v = tuple.get_item(1)?.unbind();
            self.map.insert(KeyWrapper(k), v);
        }
        Ok(())
    }


    // // Index access methods for Views    
    // fn get_item_by_index(&self, index: isize) -> PyResult<(PyObject, PyObject)> {
    //     let len = self.map.len();
    //     let idx = if index < 0 {
    //         len as isize + index
    //     } else {
    //         index
    //     };

    //     if idx < 0 || idx >= len as isize {
    //          return Err(PyIndexError::new_err("index out of range"));
    //     }

    //     let (k, v) = self.map.get_index(idx as usize).unwrap();
    //     Ok((k.0.clone(), v.clone()))
    // }

    // fn get_key_by_index(&self, index: isize) -> PyResult<PyObject> {
    //     let (k, _) = self.get_item_by_index(index)?;
    //     Ok(k)
    // }

    // fn get_value_by_index(&self, index: isize) -> PyResult<PyObject> {
    //     let (_, v) = self.get_item_by_index(index)?;
    //     Ok(v)
    // }
    
    fn index_of(&self, py: Python<'_>, key: Py<PyAny>) -> PyResult<usize> {
        match self.map.map.get_index_of(&KeyWrapper(key.clone_ref(py))) {
            Some(i) => Ok(i),
            None => Err(PyValueError::new_err(format!("{:?} is not in list", key))),
        }
    }
        
    fn __repr__(&self) -> PyResult<String> {
        let mut items = Vec::new();
        for (k, v) in &self.map.map {
            let k_repr = Python::attach(|py| k.0.bind(py).repr().unwrap().to_string());
            let v_repr = Python::attach(|py| v.bind(py).repr().unwrap().to_string());
            items.push(format!("{}: {}", k_repr, v_repr));
        }
        Ok(format!("IndexedOrderedDict({{{}}})", items.join(", ")))
    }
}

impl IndexedOrderedDict {
    // --- Rust-friendly helpers for other PyO3 code ---
    // These are intended for internal Rust use (your other `#[pyclass]` impls).
    // They let you work with *typed* keys/values at the boundary and keep the
    // storage as `PyObject`.    
    pub fn insert_py(&mut self, _py: Python<'_>, key: &Bound<'_, PyAny>, value: &Bound<'_, PyAny>) {
        self.map.insert(KeyWrapper(key.clone().unbind()), value.clone().unbind());
    }

    pub fn get_as<'a, 'py: 'a, T>(&'a self, py: Python<'py>, key: &Bound<'py, PyAny>) -> Option<T>
    where
        T: FromPyObject<'a, 'py>,
    {
        match self.map.get(&KeyWrapper(key.clone().unbind())) {
            Some(val) => val.bind(py).extract().ok(),
            None => None,
        }
    }

    pub fn get_value(&self, py: Python<'_>, key: Py<PyAny>) -> Option<Py<PyAny>> {
        self.map.get(&KeyWrapper(key)).map(|v| v.clone_ref(py))
    }

    pub fn insert_item(&mut self, key: Py<PyAny>, value: Py<PyAny>) {
        self.map.insert(KeyWrapper(key), value);
    }

    pub fn first(&self) -> Option<(&Py<PyAny>, &Py<PyAny>)> {
        self.map.map.first().map(|(k, v)| (&k.0, v))
    }

    pub fn last(&self) -> Option<(&Py<PyAny>, &Py<PyAny>)> {
        self.map.map.last().map(|(k, v)| (&k.0, v))
    }

    fn compare_with<F>(&self, other: Py<PyAny>, op: F, check_len: bool) -> PyResult<bool>
    where
        F: Fn(&Bound<'_, PyAny>, &Bound<'_, PyAny>) -> PyResult<bool>,
    {
        Python::attach(|py| {
            if let Ok(other_dict) = other.extract::<PyRef<IndexedOrderedDict>>(py) {
                if check_len && self.map.len() != other_dict.map.len() {
                    return Ok(false);
                }
                for (k, v) in &self.map.map {
                    match other_dict.map.get(k) {
                        Some(ov)=>{
                            if !op(&v.bind(py), &ov.bind(py))? {
                                return Ok(false);
                            }
                        }
                        None => return Ok(false),
                    }
                }
                Ok(true)
            } else {
                Ok(false)
            }
        })
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn iod(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<IndexedOrderedDict>()?;
    Ok(())
}
