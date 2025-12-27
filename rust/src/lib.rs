use pyo3::prelude::*;

mod indexed_ordered_dict;
mod definition_tree;
mod paradox_parser;
use indexed_ordered_dict::IndexedOrderedDict;
use definition_tree::{NodeType, ParadoxModDefinitionTree, DefinitionNode};

/// A Python module implemented in Rust.
#[pymodule]
// #[pyo3(name = "__init__")]
fn paradox(py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<IndexedOrderedDict>()?;
    m.add_class::<DefinitionNode>()?;
    m.add_class::<ParadoxModDefinitionTree>()?;
    m.add_class::<NodeType>()?;
    
    let submod = PyModule::new(py, "paradox_parser")?;
    paradox_parser::paradox_parser(py, &submod)?;
    m.add_submodule(&submod)?;

    Ok(())
}