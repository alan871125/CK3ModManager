"""
tree_nodes.py - Tree node classes for lazy loading tree views
"""

from typing import Optional, List, Union, Tuple, Any
from pathlib import Path


class ConflictTreeNode:
    """Represents a node in the conflict tree hierarchy"""
    
    def __init__(self, name: str, parent=None, node_type: str = "folder", filename: str = "", path: Optional[Path] = None):
        self.name = name
        self.parent = parent
        self.children: List['ConflictTreeNode'] = []
        self.node_type = node_type  # "mod", "folder", "file", "identifier"
        self.filename = filename  # Filename for identifier nodes
        self.path: Optional[Path] = path  # Full path to the folder/file (for easy opening)
        self.conflict_count = 0
        self.conflict_data: Optional[Union[List[Tuple[str, str, Any]], List[str]]] = None
        self._children_loaded = False
    
    def add_child(self, child: 'ConflictTreeNode'):
        """Add a child node"""
        child.parent = self
        self.children.append(child)
    
    def child(self, row: int) -> Optional['ConflictTreeNode']:
        """Get child at specific row"""
        if 0 <= row < len(self.children):
            return self.children[row]
        return None
    
    def child_count(self) -> int:
        """Get number of children"""
        return len(self.children)
    
    def row(self) -> int:
        """Get this node's row index in parent"""
        if self.parent:
            return self.parent.children.index(self)
        return 0
    
    def column_count(self) -> int:
        """Number of columns"""
        return 4  # File/Def, Filename, Line, Other Mods


class ErrorTreeNode:
    """Represents a node in the error tree hierarchy"""
    
    def __init__(self, name: str, parent=None, node_type: str = "folder", path: Optional[Path] = None):
        self.name = name
        self.parent = parent
        self.children: List['ErrorTreeNode'] = []
        self.node_type = node_type  # "mod", "folder", "file", "error"
        self.path: Optional[Path] = path  # Full path to the folder/file (for easy opening)
        self.error_count = 0
        self.error_data: Optional[Any] = None  # Stores ParsedError or error info
        self._children_loaded = False
    
    def add_child(self, child: 'ErrorTreeNode'):
        """Add a child node"""
        child.parent = self
        self.children.append(child)
    
    def child(self, row: int) -> Optional['ErrorTreeNode']:
        """Get child at specific row"""
        if 0 <= row < len(self.children):
            return self.children[row]
        return None
    
    def child_count(self) -> int:
        """Get number of children"""
        return len(self.children)
    
    def row(self) -> int:
        """Get this node's row index in parent"""
        if self.parent:
            return self.parent.children.index(self)
        return 0
    
    def column_count(self) -> int:
        """Number of columns"""
        return 4  # File/Folder, Error Type, Line, Element/Key
