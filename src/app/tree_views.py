import os
import logging
from pathlib import Path
from typing import Optional
from PyQt5 import QtWidgets as qt
from PyQt5.QtCore import Qt
from constants import MODS_DIR


from mod_analyzer.mod.manager import ModManager
from mod_analyzer.mod.paradox import NodeType
from utils.file import open_file_at_line
from .tree_nodes import ErrorTreeNode, TreeNode
logger = logging.getLogger(__name__)
# def create_conflict_table_tab(self):
        # """Create the ConflictTable tab with lazy loading tree view"""
        # conflict_widget = qt.QWidget()
        # conflict_layout = qt.QVBoxLayout(conflict_widget)
        # conflict_layout.setContentsMargins(5, 5, 5, 5)
        
        # # Conflict tree view with Model/View architecture
        # self.conflict_tree = qt.QTreeView()
        
        # # Configure tree appearance
        # self.conflict_tree.setAlternatingRowColors(True)
        # self.conflict_tree.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        # self.conflict_tree.setUniformRowHeights(True)
        
        # # Make columns resizable
        # header = self.conflict_tree.header()
        # header.setSectionResizeMode(qt.QHeaderView.Interactive)
        # header.setStretchLastSection(True)
        
        # # Set column widths
        # self.conflict_tree.setColumnWidth(0, 400)  # File/Def
        # self.conflict_tree.setColumnWidth(1, 150)  # Filename
        # self.conflict_tree.setColumnWidth(2, 80)   # Line
        
        # # Enable context menu (right-click menu)
        # self.conflict_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        # self.conflict_tree.customContextMenuRequested.connect(self.show_conflict_context_menu)
        
        # # Note: selectionChanged signal will be connected after model is set
        # # in populate_conflict_tree() method
        
        # conflict_layout.addWidget(self.conflict_tree)
        
        # self.analysis_tab_widget.addTab(conflict_widget, "ConflictTable")

class TreeWidget(qt.QWidget):
    _columns = ["File/Def", "Filename", "Line", "Other Mods"]
    _col_widths = [400, 150, 80, 200]
    def __init__(self, mod_manager, settings, parent=None):
        super().__init__(parent)
        self.mod_manager = mod_manager
        self.settings = settings
        self.selected_node: Optional[TreeNode] = None
        self.tree_layout = qt.QVBoxLayout(self)
        self.tree_layout.setContentsMargins(5, 5, 5, 5)
        
        # Conflict tree view with Model/View architecture
        self.tree_view = qt.QTreeView()
        
        # Configure tree appearance
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        self.tree_view.setUniformRowHeights(True)
        
        # Make columns resizable
        header = self.tree_view.header()
        header.setSectionResizeMode(qt.QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.set_column_widths(self._col_widths)
        
        # Enable context menu (right-click menu)
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_context_menu)
        
        if self.tree_view.selectionModel():
            self.tree_view.selectionModel().selectionChanged.connect(self.on_selection_changed)
        
        self.tree_layout.addWidget(self.tree_view)
        
    def set_column_widths(self, widths: list[int]):
        """Set column widths based on provided list."""
        for col, width in enumerate(widths):
            self.tree_view.setColumnWidth(col, width)
    
    def _build_context_menu(self, node: TreeNode):
        """Build a base context menu for both conflict and error tree (right-click menu)"""
        context_menu = qt.QMenu(self)
        # Add actions
        self.open_file_action = context_menu.addAction("📁 Reveal in File Explorer")
        self.open_file_action.triggered.connect(self.open_file_in_explorer)
        self.open_mod_file_action = context_menu.addAction("📝 Open line in Text Editor")
        self.open_mod_file_action.triggered.connect(self.open_line_in_editor)
        # Disable actions if this is not an actual conflict identifier node
        if node.type != NodeType.Identifier:
            self.open_mod_file_action.setEnabled(False)
        return context_menu
    
    def _get_clicked_node(self, position) -> Optional[TreeNode]:
        """Get the node at the clicked position"""
        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return None        
        node = index.internalPointer()
        return node
         
    def show_context_menu(self, position):
        """Show context menu (right-click menu)"""
        # Get the item at the click position
        if (node:=self._get_clicked_node(position)) is None:
            return        
        # Create context menu
        context_menu = self._build_context_menu(node)
        # Show the menu at the cursor position
        try:
            context_menu.exec_(self.tree_view.viewport().mapToGlobal(position))
        except Exception as e:
            logger.error(f"Failed to show context menu: {e}")
        
    def on_selection_changed(self, selected, deselected):
        """Handle selection change in error tree (Model/View architecture)"""
        indexes = selected.indexes()
        if not indexes:
            return        
        # Get the first selected index (column 0)
        index = indexes[0]
        if not index.isValid():
            return        
        model = self.tree_view.model()
        if not model:
            return        
        # Get node from index
        node = index.internalPointer()
        if not node:
            return        
        # Store selected node for context menu actions
        self.selected_node = node
        
    # Right panel actions
    def get_path_to_open(self, open_folder = False) -> Optional[Path]:
        """Get the path to open based on the selected node"""
        path_to_open: Optional[Path] = None
        if node:=self.selected_node:
            path_to_open = self.selected_node.path
            if node.type == NodeType.Identifier: # example: ./file.txt/identifier
                path_to_open = path_to_open.parent
        if path_to_open is not None and path_to_open.parts[0] == "%CK3_MODS_DIR%":
            path_to_open = MODS_DIR.joinpath(*path_to_open.parts[1:])
        if open_folder and path_to_open is not None and path_to_open.is_file():
            path_to_open = path_to_open.parent
        return path_to_open
    
    def get_line_to_open(self) -> int:
        """Get the line number to open based on the selected node"""
        line_number = 0
        try:
            # Try selected node first
            if self.selected_node and self.selected_node.line is not None:
                line_number = self.selected_node.line
        finally:
            return line_number
    def open_file_in_explorer(self) -> None:
        """Open the selected file or folder in file explorer"""
        try:
            path_to_open = self.get_path_to_open(open_folder=True)
            if path_to_open and path_to_open.exists():
                # open it directly
                os.startfile(path_to_open)
                logger.info("Opened %s: %s", "file" if path_to_open.is_file() else "folder", path_to_open)
                return
            elif path_to_open:
                logger.error(f"Path does not exist: {path_to_open}")
                return
            
            logger.warning("No valid file or folder path found")
        except Exception as e:
            logger.error(f"Failed to open file/folder: {e}")
    def open_file(self) -> None:
        """Open the selected file or folder"""
        try:
            path_to_open = self.get_path_to_open()
            if path_to_open and path_to_open.exists():
                # open it directly
                os.startfile(path_to_open)
                logger.info("Opened %s: %s", "file" if path_to_open.is_file() else "folder", path_to_open)
                return
            elif path_to_open:
                logger.error(f"Path does not exist: {path_to_open}")
                return
            
            logger.warning("No valid file or folder path found")
        except Exception as e:
            logger.error(f"Failed to open file/folder: {e}")
            
    def open_line_in_editor(self) -> None:
        """Open the mod file in default text editor at the specific line"""
        try:
            file_path: Optional[Path] = self.get_path_to_open()
            line_number: int = self.get_line_to_open()
            if not file_path:
                logger.warning("No file path available")
                return
            
            if not file_path.exists():
                logger.error(f"File does not exist: {file_path}")
                return            
            # Open the file in default text editor
            # Note: Windows doesn't support opening at specific line via os.startfile
            # Users will need to manually navigate to the line
            open_file_at_line(
                file_path, 
                int(line_number or 0),
                self.settings.text_editor               
            )
            
            if line_number:
                logger.info(f"Opened file: {file_path} (Navigate to line: {line_number})")
            else:
                logger.info(f"Opened file: {file_path}")
                
        except Exception as e:
            logger.error(f"Failed to open mod file: {e}")
    
    
        
    
        
class ConflictTreeWidget(TreeWidget):
    def __init__(self, mod_manager: ModManager, settings, parent=None):
        super().__init__(mod_manager, settings, parent)
        
class ErrorTreeWidget(TreeWidget):
    selected_node: Optional[ErrorTreeNode]
    _col_widths = [300, 400, 150, 75, 200]
    def __init__(self, mod_manager: ModManager, settings, parent=None):
        super().__init__(mod_manager, settings, parent)
        
    def _build_context_menu(self, node: TreeNode):
        context_menu = super()._build_context_menu(node)
        show_error_log_action = context_menu.addAction("📄 Show Line in error.log")
        show_error_log_action.triggered.connect(self.show_line_in_error_log)
        context_menu.addSeparator()        
        fix_selected_action = context_menu.addAction("🔧 Fix Selected Error")
        fix_selected_action.triggered.connect(self.fix_selected_error)
        if node.type != NodeType.Virtual: # TODO: Add a Error Type
            fix_selected_action.setEnabled(False)
            show_error_log_action.setEnabled(False)
        return context_menu
            
    def show_line_in_error_log(self) -> None:
        """Show line in error.log and open it in default text editor"""
        try:
            if not self.selected_node or self.selected_node.type != NodeType.Virtual:
                logger.warning("Please select an error item first")
                return            
            if not self.selected_node.error_data:
                logger.warning("No error data available")
                return            
            err, source = next(iter(self.selected_node.error_data.items()))
            
            # Find the error.log file
            error_log_path = Path(self.settings.error_log_path)
            
            if not error_log_path.exists():
                logger.error(f"error.log not found at: {error_log_path}")
                return
            open_file_at_line(
                error_log_path, 
                err.log_line or 0,
                self.settings.text_editor               
            )
            
            # Log the line number if available
            if hasattr(source, 'log_line') and source.line:
                logger.info(f"Opened error.log - Error at log line: {source.line}")
            else:
                logger.info(f"Opened error.log - Search for: {source.file if hasattr(source, 'file') else 'N/A'}")
                
        except Exception as e:
            logger.error(f"Failed to open error.log: {e}")
            
    def fix_selected_error(self):
        """Fix the selected error"""
        logger.info("Fixing selected error...")
        # TODO: Implement error fixing
    