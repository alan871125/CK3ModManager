"""
tree_nodes.py - Tree node classes for lazy loading tree views
"""

from typing import Optional, List, Union, Tuple, Any
from pathlib import Path
from mod_analyzer.mod.paradox import DefinitionNode, NodeType
from mod_analyzer.error.source import ErrorSource
from mod_analyzer.error.analyzer import ParsedError
class TreeNode:
    def __init__(self, name: str, parent: Optional['TreeNode']=None, node_type: NodeType=NodeType.Directory, path:Optional[Path]=None):
        self.name: str = name
        self.parent: Optional['TreeNode'] = parent
        self.children: list['TreeNode'] = []
        self._children_loaded: bool = False
        self.type: NodeType = node_type
        self.path: Path = path if path else Path("./")/name  # Full path to the folder/file (for easy opening)

    def child(self, row: int) -> Optional['TreeNode']:
        """Get child at specific row"""
        if 0 <= row < len(self.children):
            return self.children[row]
        return None
    
    def row(self) -> int:
        """Get this node's row index in parent"""
        if self.parent:
            return self.parent.children.index(self)
        return 0
    
    def add_child(self, child: 'TreeNode'):
        """Add a child node"""
        child.parent = self
        self.children.append(child)
        if child.name!= "%CK3_MODS_DIR%":
            child.path = self.path / child.name
        else:
            child.path = Path("%CK3_MODS_DIR%")
    
class ConflictTreeNode(TreeNode):
    """Represents a node in the conflict tree hierarchy"""
    def __init__(self, name: str, parent: Optional['TreeNode']=None, node_type: NodeType=NodeType.Directory, path: Optional[Path]=None):
        super().__init__(name, parent, node_type, path)
        self.conflict_count: int = 0    
        
class ConflictTreeNodeEntry(ConflictTreeNode):
    """Represents a single conflict entry in the conflict tree, 
    acts as a entry pointing to the actual definition node.
    """
    def __init__(self, definition_node: DefinitionNode, parent: Optional['TreeNode']=None):
        super().__init__(definition_node.name, parent, node_type=definition_node.type)
        self._node: DefinitionNode = definition_node
        self._conflict_count: int = 0
        self._sources: Optional[list[str]] = None
    @property
    def name(self) -> str:
        return self._node.name
    @name.setter
    def name(self, value: str):
        self._name = value
    @property
    def sources(self) -> Optional[list[str]]:
        if self._sources is None and (mod_sources:=self._node.mod_sources):
            mod_names = map(lambda m:m.name,mod_sources)
            self._sources = list(mod_names)
        return self._sources
    @property
    def full_path(self) -> Path: 
        if self.type == NodeType.Identifier:
            return self._node.full_path.parent
        # for easy opening
        return self._node.full_path
    @property
    def conflict_count(self) -> int:
        return self._conflict_count or len(self._node.sources)
    @conflict_count.setter
    def conflict_count(self, value: int):
        self._conflict_count = value
    @property
    def line(self) -> Optional[int]:
        return self._node.line
    
class ErrorTreeNode(TreeNode):
    """Represents a node in the error tree hierarchy"""
    children: List['ErrorTreeNode']
    
    def __init__(self, name: str, parent=None, node_type: NodeType=NodeType.Directory, path: Optional[Path] = None):
        self.error_count = 0
        self.error_data: Optional[dict[ParsedError, ErrorSource]] = None  # Stores ParsedError or error info
        super().__init__(name, parent, node_type, path)
    @property
    def line(self) -> Optional[int]:
        """Get line number if applicable"""
        if self.error_data and len(self.error_data) == 1:
            return next(iter(self.error_data.values())).line
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
