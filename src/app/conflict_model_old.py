"""
conflict_model.py - Lazy loading model for conflict tree view
"""

import os
from typing import Any
from pathlib import Path
from PyQt5.QtCore import Qt, QAbstractItemModel, QModelIndex, QVariant

from mod_analyzer.mod.manager import ModManager
from .tree_nodes import ConflictTreeNode


class ConflictTreeModel(QAbstractItemModel):
    """Model for lazy-loading conflict tree"""
    
    def __init__(self, mod_manager: ModManager, parent=None):
        super().__init__(parent)
        self.mod_manager = mod_manager
        self.root_node = ConflictTreeNode("root", None)
        self._build_root_nodes()
    
    def _build_root_nodes(self):
        """Build the root level (mods) - called once at initialization"""
        # Extract mod names directly from conflict_issues ModList
        # conflict_issues: {(rel_dir, identifier): ModList} where ModList is {mod_name: SourceEntry}
        
        mod_conflicts = {}  # {mod_name: [(rel_dir, identifier, ModList)]}
        
        for (rel_dir, identifier_name), mod_list in self.mod_manager.conflict_issues.items():
            # ModList is dict-like: {mod_name: SourceEntry}
            # Get all mod names that have this conflict
            if hasattr(mod_list, 'keys'):
                for mod_name in mod_list.keys():
                    if mod_name not in mod_conflicts:
                        mod_conflicts[mod_name] = []
                    
                    mod_conflicts[mod_name].append((rel_dir, identifier_name, mod_list))
        
        # Create mod nodes
        for mod_name in sorted(mod_conflicts.keys()):
            mod = self.mod_manager.mod_list.get(mod_name)
            mod_node = ConflictTreeNode(mod_name, self.root_node, "mod", path = mod.path if mod else None)
            conflicts = mod_conflicts[mod_name]
            # Count total conflicting identifiers for this mod
            mod_node.conflict_count = len(conflicts)
            mod_node.conflict_data = conflicts
            self.root_node.add_child(mod_node)
    
    def _load_mod_children(self, mod_node: ConflictTreeNode):
        """Lazy load: Build folder/file/identifier hierarchy under a mod"""
        if mod_node._children_loaded or mod_node.conflict_data is None:
            return
        
        node_map = {}  # {path: node} for reusing nodes
        
        for rel_dir, identifier_name, mod_list in mod_node.conflict_data:  # type: ignore
            rel_path = Path(rel_dir)
            
            # ModList is {mod_name: SourceEntry}
            # Get the filename and full path from the current mod's SourceEntry
            filename = ""
            file_full_path = None
            if hasattr(mod_list, 'get') and mod_node.name in mod_list:
                source_entry = mod_list[mod_node.name]
                if hasattr(source_entry, 'file'):
                    file_full_path = Path(source_entry.file)
                    filename = file_full_path.name
            
            # Get other mods that conflict (excluding current mod)
            other_mods = []
            if hasattr(mod_list, 'keys'):
                other_mods = [name for name in mod_list.keys() if name != mod_node.name]
            
            # Remove mod name from path if present
            if rel_path.parts and rel_path.parts[0] == mod_node.name:
                parts = rel_path.parts[1:] + (identifier_name,)
            else:
                parts = rel_path.parts + (identifier_name,)
            
            # Build hierarchy
            parent = mod_node
            full_path = ""
            
            for i, part in enumerate(parts):
                full_path = os.path.join(full_path, part) if full_path else part
                is_identifier = (i == len(parts) - 1)
                is_file = (i == len(parts) - 2)
                
                if full_path not in node_map:
                    node_type = "identifier" if is_identifier else ("file" if is_file else "folder")
                    
                    # Determine the actual filesystem path for this node
                    node_path = None
                    if file_full_path:
                        if is_identifier or is_file:
                            # For file and identifier nodes, use the actual file path
                            node_path = file_full_path
                        else:
                            # For folder nodes, use the parent directory path
                            # Navigate up from file to get the folder at this level
                            levels_from_file = len(parts) - i - 1
                            node_path = file_full_path
                            for _ in range(levels_from_file):
                                node_path = node_path.parent
                    
                    # Pass filename to identifier nodes
                    node = ConflictTreeNode(
                        part, 
                        parent, 
                        node_type,
                        filename=filename if is_identifier else "",
                        path=node_path
                    )
                    
                    if is_identifier:
                        # Show how many other mods conflict
                        node.conflict_count = len(other_mods)
                        # Store other mod names for display in "Other Mods" column
                        node.conflict_data = other_mods
                    
                    parent.add_child(node)
                    node_map[full_path] = node
                
                parent = node_map[full_path]
        
        mod_node._children_loaded = True
    
    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        """Create index for given row, column, parent"""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node = parent.internalPointer()
        
        # Lazy load children if needed
        if parent_node.node_type == "mod" and not parent_node._children_loaded:
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
    
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of rows under parent"""
        if parent.column() > 0:
            return 0
        
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node = parent.internalPointer()
            # Lazy load children if needed
            if parent_node.node_type == "mod" and not parent_node._children_loaded:
                self._load_mod_children(parent_node)
        
        return parent_node.child_count()
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of columns"""
        return 4  # File/Def, Filename, Line, Other Mods
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """Get data for display"""
        if not index.isValid():
            return QVariant()
        
        node = index.internalPointer()
        column = index.column()
        
        if role == Qt.DisplayRole:
            if   column == 0: 
                return node.name
            elif column == 1: 
                return node.filename  # Filename column
            elif column == 2: 
                return ""             # Line column - empty for now
            elif column == 3:
                # Other Mods column
                if node.node_type == "identifier" and isinstance(node.conflict_data, list):
                    # Show the actual mod names that conflict
                    if node.conflict_data:
                        return ", ".join(node.conflict_data[:3]) + ("..." if len(node.conflict_data) > 3 else "")
                    return ""
                elif node.conflict_count > 0:
                    return f"({node.conflict_count} conflicts)"
                return ""
        
        return QVariant()
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        """Get header data"""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            headers = ["File / Def", "Filename", "Line", "Conflict Mods"]
            if 0 <= section < len(headers):
                return headers[section]
        return QVariant()
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """Get item flags"""
        if not index.isValid():
            return Qt.ItemFlags(Qt.NoItemFlags)
        return Qt.ItemFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
