"""
error_model.py - Lazy loading model for error tree view
"""

import os
import re
from typing import Any, Dict, Optional
from pathlib import Path
from PyQt5.QtCore import Qt, QAbstractItemModel, QModelIndex, QVariant

from mod_analyzer.error.source import ErrorSource
from mod_analyzer.error.analyzer import ErrorAnalyzer, ParsedError
from mod_analyzer.mod.paradox import DefinitionNode, NodeType
from .tree_nodes import ErrorTreeNode
import logging
logger = logging.getLogger(__name__)
class ErrorTreeModel(QAbstractItemModel):
    """Model for lazy-loading error tree"""
    _columns = ["File / Folder", "Related Object", "Error Type", "Line", "Log Line"]
    def __init__(self, error_analyzer: ErrorAnalyzer, parent=None):
        super().__init__(parent)
        self.analyzer:ErrorAnalyzer = error_analyzer
        self.root_node = ErrorTreeNode("root", None, node_type=NodeType.Virtual)
        self.filtered_error_types = None  # None means show all, set() means show none, set with types means filter
        
        # Cache all mod nodes once (with ALL errors)
        self._all_mod_nodes: list[ErrorTreeNode] = []
        self._build_all_root_nodes()
        
    # @property
    # def error_sources(self) -> Dict[int, list[SourceEntry]]:
    #     return self.analyzer.error_sources
    
    @property
    def errors(self) -> list[ParsedError]:
        return self.analyzer.errors
    
    def set_filter(self, error_types: set):
        """Set which error types to show. None = show all, empty set = show none"""
        old_filter = self.filtered_error_types
        self.filtered_error_types = error_types
        
        # Only reset if filter actually changed
        if old_filter != error_types:
            # Clear lazy-loaded children to force rebuild with new filter
            for mod_node in self._all_mod_nodes:
                mod_node._children_loaded = False
                mod_node.children.clear()
            
            # Rebuild visible mod list
            self.beginResetModel()
            self._update_visible_mods_fast()
            self.endResetModel()
    
    def _update_visible_mods_fast(self):
        """Update which mods are visible in root based on filter - optimized version"""
        self.root_node.children.clear()
        
        # If showing all, add all mods
        if self.filtered_error_types is None:
            for mod_node in self._all_mod_nodes:
                self.root_node.add_child(mod_node)
            return        
        # If showing none, don't add any mods
        if len(self.filtered_error_types) == 0:
            return
        # Add only mods that have at least one visible error
        for mod_node in self._all_mod_nodes:
            # Quick check: does this mod have any errors of the selected types?
            has_visible = False
            visible_count = 0
            if mod_node.error_data is None:
                continue
            for err, _ in mod_node.error_data.items():
                error_type = err.type
                if error_type and error_type in self.filtered_error_types:
                    has_visible = True
                    visible_count += 1
            
            if has_visible:
                mod_node.error_count = visible_count
                self.root_node.add_child(mod_node)
    
    def _should_include_error(self, err_id: int) -> bool:
        """Check if an error should be included based on current filter"""
        if self.filtered_error_types is None:
            return True  # Show all
        
        if len(self.filtered_error_types) == 0:
            return False  # Show none
        
        # Find the error in analyzer
        error = next((e for e in self.analyzer.errors if e.id == err_id), None)
        if not error:
            return False
        
        # Check if error type is in filtered set
        return error.type in self.filtered_error_types

    def _build_all_root_nodes(self):
        """Build the root level (mods) with ALL errors - called once at initialization"""
        for mod_name in sorted(self.analyzer.error_by_mod.keys()):
            mod = self.analyzer.mod_manager.mod_list.get(mod_name)
            mod_node = ErrorTreeNode(mod_name, self.root_node, NodeType.Mod, path = mod.path if mod else None)
            mod_node.error_count = len(self.analyzer.error_by_mod[mod_name])
            mod_node.error_data = self.analyzer.error_by_mod[mod_name]
            self._all_mod_nodes.append(mod_node)
        
        # Update visible mods based on current filter
        self._update_visible_mods_fast()
    
    def _load_mod_children(self, mod_node: ErrorTreeNode):
        """Lazy load: Build folder/file/error hierarchy under a mod"""
        if mod_node._children_loaded or mod_node.error_data is None:
            return
        
        node_map:dict[str, ErrorTreeNode] = {}  # {path: node} for reusing nodes
        
        for err, source in mod_node.error_data.items():
            # Apply filter
            err_id = err.id
            if not self._should_include_error(err_id):
                continue
                
            # Get file path and make it relative to mod root if possible
            for mod in source.mod_sources:
                if source.file is None:
                    file_path = Path("Unknown")
                    rel_path = Path("Unknown")
                elif source.file.exists():
                    file_path = source.file
                    rel_path = file_path.relative_to(mod.path)
                else:
                    file_path = mod.path/source.file
                    rel_path = source.file
            
                # Build path parts
                parts = rel_path.parts
                # Build hierarchy
                parent = mod_node
                full_path = ""                
                for i, part in enumerate(parts):

                    full_path = os.path.join(full_path, part) if full_path else part
                    
                    if full_path not in node_map:
                        if is_file := (i == len(parts) - 1):
                            node_type = NodeType.File
                        else:
                            node_type = NodeType.Directory
                        
                        # Determine the actual filesystem path for this node
                        node_path = None
                        if is_file:
                            # For file nodes, use the absolute file path
                            node_path = file_path
                        else:
                            # For folder nodes, navigate up from file to get folder path

                            levels_from_file = len(parts) - i - 1
                            node_path = file_path
                            for _ in range(levels_from_file):
                                node_path = node_path.parent
                        
                        node = ErrorTreeNode(part, parent, node_type, path=node_path)
                        
                        if is_file:
                            # Store list of errors for this file
                            node.error_data = {}
                        
                        # parent.add_child(node) # Already added in __init__
                        node_map[full_path] = node
                    
                    parent = node_map[full_path]
                
                # Add error as child of file node
                if full_path in node_map:
                    file_node = node_map[full_path]
                    if isinstance(file_node.error_data, dict):
                        file_node.error_data[err] = source
                        file_node.error_count = len(file_node.error_data)
            
        # Now create error nodes under each file
        self._create_error_nodes(mod_node)
        
        mod_node._children_loaded = True
    
    def _create_error_nodes(self, parent_node: ErrorTreeNode):
        """Recursively create error nodes under file nodes"""
        for child in parent_node.children:
            if child.type == NodeType.File and child.error_data:
                # Create error nodes for this file
                for err, source in child.error_data.items():
                    # Get file path for error node
                    error_file_path = source.file or Path("Unknown")
                    
                    error_node = ErrorTreeNode(
                        f"Error #{err.id}",
                        child,
                        NodeType.Virtual,
                        path=error_file_path
                    )
                    error_node.error_data = {err: source}
                    # child.add_child(error_node) # Already added in __init__
                # Mark as loaded
                child._children_loaded = True
            elif child.type == NodeType.Directory:
                # Recursively process folders
                self._create_error_nodes(child)
    
    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        """Create index for given row, column, parent"""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node = parent.internalPointer()
        
        # Lazy load children if needed
        if parent_node.type == NodeType.Mod and not parent_node._children_loaded:
            self._load_mod_children(parent_node)
        
        child_node = parent_node.child(row)
        if child_node:
            return self.createIndex(row, column, child_node)
        
        return QModelIndex()
    
    def parent(self, child: QModelIndex) -> QModelIndex:  # type: ignore
        """Get parent index"""
        if not child.isValid():
            return QModelIndex()
        
        child_node = child.internalPointer()
        parent_node = child_node.parent
        
        if parent_node == self.root_node or parent_node is None:
            return QModelIndex()
        
        return self.createIndex(parent_node.row(), 0, parent_node)
    
    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        """Check if node has children - optimized to avoid loading"""
        if not parent.isValid():
            return self.root_node.child_count() > 0
            
        parent_node = parent.internalPointer()
        if parent_node.type == NodeType.Mod and not parent_node._children_loaded:
            return parent_node.error_count > 0
            
        return parent_node.child_count() > 0

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of rows under parent"""
        if parent.column() > 0:
            return 0
        
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node: ErrorTreeNode = parent.internalPointer()
            if parent_node.type == NodeType.Mod and not parent_node._children_loaded:
                self._load_mod_children(parent_node)
        
        return parent_node.child_count()
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of columns"""
        return len(self._columns)  # File/Folder, Error Type, Line, Related Object
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """Get data for display"""
        if not index.isValid():
            return QVariant()
        node: ErrorTreeNode = index.internalPointer()
        column = index.column()
        err: ParsedError        
        # ["File / Folder", "Error Type", "Related Object", "Line", "Log Line", ]
        if role == Qt.DisplayRole:
            try:
                if column == 0:   # File/Folder name
                    return node.name
                elif column == 1: # Error Type (only for error nodes) (Virtual nodes used to represent errors)
                    if node.type == NodeType.Virtual and node.error_data:
                        err, err_source = list(node.error_data.items())[0]
                        return err.type
                    return ""
                elif column == 2: # Related Object (only for error nodes)               
                    if node.type == NodeType.Virtual and node.error_data:
                        err, err_source = list(node.error_data.items())[0]
                        if err_source:
                            return ', '.join(filter(None, [
                                err_source.object,
                                err_source.key,
                                err_source.value
                            ]))
                    elif node.error_count > 0:
                        return f"({node.error_count} errors)"
                    return ""
                elif column == 3: # Line (only for error nodes)
                    if node.type == NodeType.Virtual and node.error_data:
                        err, err_source = list(node.error_data.items())[0]
                        if err_source and err_source.line is not None:
                            return err_source.line
                    return "" 
                elif column == 4: # Log Line (only for error nodes)
                    if node.type == NodeType.Virtual and node.error_data:
                        err, err_source = list(node.error_data.items())[0]
                        return err.log_line
                    return ""
            except IndexError as e:
                logger.exception(f"IndexError in data({node.error_data}): {e}")
        
        return QVariant()
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        """Get header data"""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            headers = self._columns
            if 0 <= section < len(headers):
                return headers[section]
        return QVariant()
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """Get item flags"""
        if not index.isValid():
            return Qt.ItemFlags(Qt.NoItemFlags)
        return Qt.ItemFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
