"""
conflict_model.py - Lazy loading model for conflict tree view
"""

import os
from typing import Any
from pathlib import Path
from PyQt5.QtCore import Qt, QAbstractItemModel, QModelIndex, QVariant

from mod_analyzer.mod.manager import ModManager
from mod_analyzer.mod.paradox import DefinitionNode, NodeType
from .tree_nodes import ConflictTreeNode as ConflictTreeNodeWIP
from .tree_nodes import ConflictTreeNodeEntry

class ConflictTreeModelWIP(QAbstractItemModel):
    """Model for lazy-loading conflict tree"""
    _columns = ["File/Def", "Filename", "Line", "Other Mods"]
    def __init__(self, mod_manager: ModManager, parent=None):
        super().__init__(parent)
        self.mod_manager = mod_manager
        self.root_node = ConflictTreeNodeWIP("root", None)
        self.conflicts_by_mod = self.mod_manager.conflicts_by_mod
        self._build_root_nodes()
    
    def _build_root_nodes(self):
        """Build the root level (mods) - called once at initialization"""
        # Extract mod names directly from conflict_issues ModList
        # conflict_issues: {(rel_dir, identifier): ModList} where ModList is {mod_name: SourceEntry}
        mod_nodes:dict[str, ConflictTreeNodeWIP] = {}
        # mod_conflicts = {}  # {mod_name: [(rel_dir, identifier, ModList)]}
        for mod_name in sorted(self.conflicts_by_mod.keys()):
            def_nodes = self.conflicts_by_mod[mod_name]
            mod_nodes[mod_name] = ConflictTreeNodeWIP(mod_name, self.root_node, NodeType.Mod, path=Path(mod_name))
            mod_nodes[mod_name].conflict_count = len(def_nodes)
        
    def _load_mod_children(self, mod_node: ConflictTreeNodeWIP):
        if mod_node._children_loaded:
            return
        node_map = {}  # {path: node} for reusing nodes
        for identifier in self.conflicts_by_mod.get(mod_node.name, []):
            rel_path = identifier.rel_dir
            identifier_name = identifier.name
            conflicts = self.mod_manager.get_node_mod_sources(identifier, enabled_only=True)
            # remove self mod from conflicts
            # if conflicts and mod_node.name in conflicts:
            #     del conflicts[mod_node.name]
            parts = rel_path.parts + (identifier_name,)
            # build hierarchy
            parent = mod_node
            full_path = ""
            for i, part in enumerate(parts):
                full_path = os.path.join(full_path, part) if full_path else part
                if full_path in node_map:
                    parent = node_map[full_path]
                    continue                
                # check if node already exists
                existing_node = None
                for child in parent.children:
                    if child.name == part:
                        existing_node = child
                        break
                if existing_node:
                    parent = existing_node
                    continue
                if i==len(parts)-1:
                    # identifier node
                    node = ConflictTreeNodeEntry(identifier, parent)
                    node.conflict_count = len(conflicts) if conflicts else 0
                else:
                    node = ConflictTreeNodeWIP(part, parent)
                parent = node
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
        if parent_node.type == NodeType.Mod and not parent_node._children_loaded:
            self._load_mod_children(parent_node)
        
        child_node = parent_node.child(row)
        if child_node:
            return self.createIndex(row, column, child_node)
        
        return QModelIndex()
    
    def parent(self, child: QModelIndex) -> QModelIndex:
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
            if (parent_node.type == NodeType.Mod and
                (val:=self.conflicts_by_mod.get(parent_node.name)) is not None
            ):
                return len(set(identifier.rel_dir.parts[0] for identifier in val))
        
        return len(parent_node.children)
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of columns"""
        return len(self._columns)
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """Get data for display"""
        if not index.isValid():
            return QVariant()
        
        node = index.internalPointer()
        column = index.column()
        
        if role == Qt.DisplayRole:
            match column:
                case 0: 
                    return node.name
                case 1  if node.type == NodeType.File:
                    return '-'
                case 2 if hasattr(node, 'line'):
                    return node.line or '-'  # Line column
                case 3:
                    # Other Mods column
                    if node.type == NodeType.Mod:
                        return f"({node.conflict_count} conflicts)"
                    elif node.type<NodeType.Directory  and isinstance(node, ConflictTreeNodeEntry):
                        if node.sources:
                            return ", ".join(node.sources)
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
        
from mod_analyzer.conflict.analyzer import ConflictSource, ParsedConflict, ConflictLogParser, BaseTreeNode
from mod_analyzer.conflict.analyzer import ConflictTreeNode as ConflictTreeNode
class ConflictTreeModel(QAbstractItemModel):
    """
    Model for lazy-loading conflict tree - version 2
    Args:
        mod_manager: ModManager - the mod manager instance
    """
    _columns = ["File / Def", "Filename", "Line", "Conflict Mods"]
    def __init__(self, mod_manager: ModManager):
        super().__init__()
        self.mod_manager = mod_manager
        self.conflict_parser = ConflictLogParser()
        self.conflict_parser.parse_logs(logs = None) # parse logs at default path
        self.root_node = self.conflict_parser.locate_conflict_sources2(mod_manager)
        self.root_node.sort()
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """Get data for display"""
        if not index.isValid():
            return QVariant()
        node = index.internalPointer()
        # Check if node holds a ConflictSource
        source = node.val if (isinstance(node, BaseTreeNode) and isinstance(node.val, ConflictSource)) else None
        
        if role == Qt.DisplayRole:
            match index.column():
                case 0: 
                    if source:
                        return source.object
                    return node.name
                case 1:
                    return '-' # TODO: will be removed
                case 2:
                    if source:
                        return source.line or '-'
                    return ''
                case 3:
                    # Other Mods column
                    if source and source._parsed_conflict is not None:
                        conflict_sources = source._parsed_conflict.sources
                        return ", ".join(src.mod.name for src in conflict_sources if src.mod.name != source.mod.name)
                    return ''
        return QVariant()
    
    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        """Create index for given row, column, parent"""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()        
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node = parent.internalPointer()
        
        child_node = None
        if isinstance(parent_node, BaseTreeNode):
            
            if 0 <= row < len(parent_node):
                child_node = parent_node.values()[row]
        elif isinstance(parent_node, ConflictSource):
            # ConflictSource has no children
            return QModelIndex()
        if child_node is not None:
            return self.createIndex(row, column, child_node)
        
        return QModelIndex()
    
    def parent(self, child: QModelIndex) -> QModelIndex:
        """Get parent index"""
        if not child.isValid():
            return QModelIndex()
        
        child_node = child.internalPointer()
        parent_node = child_node.parent
        
        if parent_node == self.root_node or parent_node is None:
            return QModelIndex()
        
        # Calculate row of parent_node in its parent
        grandparent = parent_node.parent
        if grandparent is None:
            return QModelIndex()
            
        try:
            row = list(grandparent.values()).index(parent_node)
            return self.createIndex(row, 0, parent_node)
        except ValueError:
            return QModelIndex()
    
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of rows under parent"""
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node = parent.internalPointer()
        if isinstance(parent_node, BaseTreeNode):
            return len(parent_node)
        return 0
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of columns"""
        return len(self._columns)
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        """Get header data"""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            headers = self._columns
            if 0 <= section < len(headers):
                return headers[section]
        return QVariant()               
                