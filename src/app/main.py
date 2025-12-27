import os
import sys
import shutil
import logging
from pathlib import Path
from typing import Optional
import PyQt5.QtWidgets as qt
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QModelIndex, QTimer
from PyQt5.QtGui import QDropEvent, QCursor, QIcon

from mod_analyzer.mod.descriptor import Mod
from mod_analyzer.mod.mod_list import ModList
from mod_analyzer.mod.manager import ModManager
from mod_analyzer.error import patterns
from mod_analyzer.error.analyzer import ErrorAnalyzer, ParsedError
from app.mod_table import ModTableWidget, ModTableWidgetItem
from app.directory import CK3_MODS_DIR
from app.conflict_model import ConflictTreeModel
from app.error_model import ErrorTreeModel
from app.tree_nodes import ConflictTreeNodeEntry, ErrorTreeNode, ConflictTreeNode, TreeNode
from app.workers import FileTreeWorker, ErrorAnalysisWorker
from app.settings import Settings, SettingsDialog
from app.game import GameLauncher
from mod_analyzer.mod.paradox import DefinitionNode, NodeType
logging.basicConfig(format='[%(asctime)s][%(levelname)s] %(message)s', level=logging.INFO)
# Set up loggers
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.getLogger('mod_analyzer').setLevel(logging.DEBUG)


class QTextEditLogger(logging.Handler, QtCore.QObject):
    appendPlainText = QtCore.pyqtSignal(str)
    flushOnClose = False  # Prevent logging.shutdown() from accessing deleted Qt object
    
    def __init__(self, parent):
        super().__init__()
        QtCore.QObject.__init__(self)
        self.widget = qt.QPlainTextEdit(parent)
        self.widget.setReadOnly(True)
        self.appendPlainText.connect(self.widget.appendPlainText)

    def emit(self, record):
        msg = self.format(record)
        self.appendPlainText.emit(msg)
        
class CK3ModManagerApp(qt.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CK3 Mod Analyzer")
        self.setGeometry(100, 100, 1200, 800)
        self.setWindowIcon(QIcon(str(Path(__file__).parent/"icons"/"app_icon.png")))
        self.settings: Settings = Settings.load("settings.json") or Settings()
        self.game_launcher = GameLauncher(self.settings.launcher_settings_path)
        self.mod_manager = ModManager()
        self.mod_manager.language = self.settings.game_language
        self.analyzer:ErrorAnalyzer = ErrorAnalyzer(self.mod_manager)
        # self.error_sources: dict[int, list[SourceEntry]]
        self.error_worker: Optional[ErrorAnalysisWorker] = None
        self.file_tree_worker: Optional[FileTreeWorker] = None
        
        # Filter debounce timer to prevent multiple rapid filter applications
        self.filter_debounce_timer = QTimer()
        self.filter_debounce_timer.setSingleShot(True)
        self.filter_debounce_timer.setInterval(100)  # 100ms delay
        self.filter_debounce_timer.timeout.connect(self._apply_error_filters_impl)
        
        # Track currently selected items for context menu actions
        self.selected_error_node: Optional[ErrorTreeNode] = None
        self.selected_conflict_node: Optional[ConflictTreeNode] = None
        
        log_level = logging.DEBUG if self.settings.debug else logging.INFO
        logger.setLevel(log_level)
        self.initUI()
        # Auto-load mods on startup
        self.load_mods()
        if self.settings.check_conflict_on_startup:
            self.analyze_mod_list()
    @property
    def mod_table(self) -> ModTableWidgetItem:
        return self.mod_tab_widget.mod_table
    
    def closeEvent(self, event):
        """Handle window close event - clean up worker threads"""
        # Restore cursor if it was overridden during an operation
        qt.QApplication.restoreOverrideCursor()
        
        # Clean up error analysis worker
        if self.error_worker and self.error_worker.isRunning():
            self.error_worker.terminate()
            self.error_worker.wait()
        
        # Clean up file tree worker
        if self.file_tree_worker and self.file_tree_worker.isRunning():
            self.file_tree_worker.terminate()
            self.file_tree_worker.wait()
        event.accept()
    
    def initUI(self):
        # Create menu bar
        self.create_menu_bar()
        
        # Central widget and main layout
        self.central_widget = qt.QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.main_layout = qt.QVBoxLayout(self.central_widget)
        
        # Top button panel
        self.create_top_buttons()
        
        
        # Main vertical splitter (splits content and log)
        self.main_v_splitter = qt.QSplitter(Qt.Vertical)
        self.main_layout.addWidget(self.main_v_splitter)
        
        # Main content area (now just the left panel, no right panel)
        self.create_left_panel()
        
        # Log section at bottom
        self.create_log_section()
        
        # Set vertical splitter proportions (content takes more space than log)
        self.main_v_splitter.setStretchFactor(0, 5)
        self.main_v_splitter.setStretchFactor(1, 1)
    
    def create_menu_bar(self):
        """Create the menu bar with Settings and Help menus"""
        menubar = self.menuBar()
        
        # Settings menu
        settings_menu = menubar.addMenu("Settings")
        settings_action = qt.QAction("Open Settings", self)
        settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(settings_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        help_action = qt.QAction("About", self)
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)
    
    def create_top_buttons(self):
        """Create the top button panel"""
        button_layout = qt.QHBoxLayout()
        
        self.analyze_mod_list_button = qt.QPushButton("Analyze Mod list")
        self.analyze_mod_list_button.clicked.connect(self.analyze_mod_list)
        
        self.analyze_errors_button = qt.QPushButton("Analyze Errors")
        self.analyze_errors_button.clicked.connect(self.analyze_errors)
        self.analyze_errors_button.setEnabled(False)  # Disabled until mod list is analyzed
        
        self.export_json_button = qt.QPushButton("Export JSON")
        self.export_json_button.clicked.connect(self.export_json)
        
        self.open_error_log_button = qt.QPushButton("Open error.log")
        self.open_error_log_button.clicked.connect(self.open_error_log)
        
        self.launch_game_button = qt.QPushButton("Launch Game")
        self.launch_game_button.setToolTip("Launch Game")
        self.launch_game_button.clicked.connect(self.launch_game)
        self.launch_game_button.setMaximumSize(50,50)
        self.launch_game_button.setMinimumSize(50,50)
        # Use Path to get absolute path to icon file
        icon_path = Path(__file__).parent / "icons" / "icons8-play-48.png"
        
        self.launch_game_button.setIcon(QIcon(str(icon_path)))
        self.launch_game_button.setIconSize(QtCore.QSize(32,32))
        self.launch_game_button.setMaximumWidth(150)
        button_layout.addWidget(self.analyze_mod_list_button)
        button_layout.addWidget(self.analyze_errors_button)
        button_layout.addWidget(self.export_json_button)
        button_layout.addWidget(self.open_error_log_button)
        button_layout.addStretch()
        
        
        # Add progress bar
        self.progress_bar = qt.QProgressBar()
        self.progress_bar.setVisible(False)  # Hidden by default
        self.progress_bar.setMaximumHeight(20)
        button_layout.addWidget(self.progress_bar)
        button_layout.addWidget(self.launch_game_button)
            
        self.main_layout.addLayout(button_layout)
    
    def create_left_panel(self):
        """Create the left panel with tabs"""
        left_widget = qt.QWidget()
        left_layout = qt.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Profile dropdown
        profile_layout = qt.QHBoxLayout()
        profile_label = qt.QLabel("Profile (drop down list)")
        self.profile_combo = qt.QComboBox()
        self.profile_combo.addItems(["<Default>"])
        try:
            for profile_dir in Path("profiles").iterdir():
                if profile_dir.is_dir():
                    self.profile_combo.addItem(profile_dir.name)
        except FileNotFoundError:
            pass
        self.profile_combo.currentIndexChanged.connect(self.load_mods)
        profile_layout.addWidget(profile_label)
        profile_layout.addWidget(self.profile_combo)
        
        # Add buttons right after combo box (before stretch)
        profile_new_button = qt.QPushButton("＋")
        profile_save_button = qt.QPushButton("💾")
        # profile_apply_button = qt.QPushButton("✓")
        profile_new_button.setMaximumSize(30, 30)
        profile_save_button.setMaximumSize(30, 30)
        # profile_apply_button.setMaximumSize(30, 30)
        profile_new_button.clicked.connect(self.create_new_profile)
        profile_save_button.clicked.connect(self.save_profile)
        # profile_apply_button.clicked.connect(self.apply_profile)
        profile_new_button.setToolTip("New Profile")
        profile_save_button.setToolTip("Save Profile")
        # profile_apply_button.setToolTip("Apply Profile (to game)")
        profile_layout.addWidget(profile_new_button)
        profile_layout.addWidget(profile_save_button)
        # profile_layout.addWidget(profile_apply_button)
        
        # Add stretch after buttons to push everything to the left
        profile_layout.addStretch()
        left_layout.addLayout(profile_layout)
        
        # Tab widget with resizable splitter
        self.tab_splitter = qt.QSplitter(Qt.Horizontal)
        
        # Left tab widget - Mod List only
        self.mod_tab_widget = ModTableWidget(self.mod_manager)
        self.tab_splitter.addWidget(self.mod_tab_widget)
        
        # Middle tab widget - Error Analyzer and Conflict Table
        # Create a container for actions, analysis tabs and filter toggle button
        self.analysis_container = qt.QWidget()
        analysis_container_layout = qt.QVBoxLayout(self.analysis_container)
        analysis_container_layout.setContentsMargins(0, 0, 0, 0)
        analysis_container_layout.setSpacing(5)
        
        # Add actions at the top
        actions_layout = qt.QHBoxLayout()
        self.fix_all_button = qt.QPushButton("Fix All Encoding Errors")
        self.fix_all_button.clicked.connect(self.fix_all_encoding_errors)
        actions_layout.addWidget(self.fix_all_button)
        actions_layout.addStretch()
        analysis_container_layout.addLayout(actions_layout)
        
        self.analysis_tab_widget = qt.QTabWidget()
        self.create_conflict_table_tab()
        self.create_error_analyzer_tab()
        analysis_container_layout.addWidget(self.analysis_tab_widget)
        
        # Add filter toggle button at bottom right
        button_layout = qt.QHBoxLayout()
        button_layout.addStretch()
        filter_label = qt.QLabel("Filter")
        button_layout.addWidget(filter_label)
        self.filter_toggle_button = qt.QPushButton("«")
        self.filter_toggle_button.setMaximumSize(20, 30)
        self.filter_toggle_button.clicked.connect(self.toggle_filters_panel)
        self.filter_toggle_button.setToolTip("Hide Filter")
        button_layout.addWidget(self.filter_toggle_button)
        analysis_container_layout.addLayout(button_layout)
        
        self.tab_splitter.addWidget(self.analysis_container)
        
        # Right side - Filter (hidable)
        self.create_filters_panel()
        self.tab_splitter.addWidget(self.filters_panel_container)
        
        # Set initial splitter sizes (mod list, analysis tabs, Filter)
        self.tab_splitter.setStretchFactor(0, 3)  # Mod List
        self.tab_splitter.setStretchFactor(1, 3)  # Error Analyzer/Conflict Table
        self.tab_splitter.setStretchFactor(2, 1)  # Filters
        
        left_layout.addWidget(self.tab_splitter)
        
        # Add left widget directly to main vertical splitter (no horizontal splitter needed)
        self.main_v_splitter.addWidget(left_widget)
        
        # default untoggled filter panel
        self.toggle_filters_panel()
    
    def create_error_analyzer_tab(self):
        """Create the Error Analyzer tab with lazy loading tree view"""
        error_analyzer_widget = qt.QWidget()
        error_layout = qt.QVBoxLayout(error_analyzer_widget)
        error_layout.setContentsMargins(5, 5, 5, 5)
        
        # Error analyzer tree view with Model/View architecture
        self.error_tree = qt.QTreeView()
        
        # Configure tree appearance
        self.error_tree.setAlternatingRowColors(True)
        self.error_tree.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        self.error_tree.setUniformRowHeights(True)
        
        # Make columns resizable
        header = self.error_tree.header()
        header.setSectionResizeMode(qt.QHeaderView.Interactive)
        header.setStretchLastSection(True)
        
        # Set column widths
        self.error_tree.setColumnWidth(0, 400)  # File path
        self.error_tree.setColumnWidth(1, 150)  # Error type
        self.error_tree.setColumnWidth(2, 60)   # Line
        
        # Enable context menu (right-click menu)
        self.error_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.error_tree.customContextMenuRequested.connect(self.show_error_context_menu)
        
        # Note: selectionChanged signal will be connected after model is set
        # in _populate_error_table() method
        
        error_layout.addWidget(self.error_tree)
        
        self.analysis_tab_widget.addTab(error_analyzer_widget, "Error Analyzer")
    
    def create_conflict_table_tab(self):
        """Create the ConflictTable tab with lazy loading tree view"""
        conflict_widget = qt.QWidget()
        conflict_layout = qt.QVBoxLayout(conflict_widget)
        conflict_layout.setContentsMargins(5, 5, 5, 5)
        
        # Conflict tree view with Model/View architecture
        self.conflict_tree = qt.QTreeView()
        
        # Configure tree appearance
        self.conflict_tree.setAlternatingRowColors(True)
        self.conflict_tree.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        self.conflict_tree.setUniformRowHeights(True)
        
        # Make columns resizable
        header = self.conflict_tree.header()
        header.setSectionResizeMode(qt.QHeaderView.Interactive)
        header.setStretchLastSection(True)
        
        # Set column widths
        self.conflict_tree.setColumnWidth(0, 400)  # File/Def
        self.conflict_tree.setColumnWidth(1, 150)  # Filename
        self.conflict_tree.setColumnWidth(2, 80)   # Line
        
        # Enable context menu (right-click menu)
        self.conflict_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conflict_tree.customContextMenuRequested.connect(self.show_conflict_context_menu)
        
        # Note: selectionChanged signal will be connected after model is set
        # in populate_conflict_tree() method
        
        conflict_layout.addWidget(self.conflict_tree)
        
        self.analysis_tab_widget.addTab(conflict_widget, "ConflictTable")
    
    def create_filters_panel(self):
        """Create the hidable filters side panel"""
        # Initialize visibility state
        self.filters_panel_visible = True
        
        # Container widget for the Filter
        filter_group = qt.QGroupBox("Filter")
        filter_layout = qt.QVBoxLayout(filter_group)
        
        # Create tree widget for filters
        self.filter_tree = qt.QTreeWidget()
        self.filter_tree.setHeaderHidden(True)
        
        category_item = qt.QTreeWidgetItem(self.filter_tree)
        category_item.setText(0, 'other')
        category_item.setFlags(category_item.flags() | Qt.ItemIsUserCheckable)
        category_item.setCheckState(0, Qt.Checked)
        for err_type in patterns.regex.keys():
            type_item = qt.QTreeWidgetItem(category_item)
            type_item.setText(0, err_type)
            type_item.setFlags(type_item.flags() | Qt.ItemIsUserCheckable)
            type_item.setCheckState(0, Qt.Checked)
        
        # Connect filter changes to update function
        self.filter_tree.itemChanged.connect(self.apply_error_filters)
        
        # self.filter_tree.expandAll()
        filter_layout.addWidget(self.filter_tree)
        
        # Wrap in scroll area
        filter_scroll = qt.QScrollArea()
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setWidget(filter_group)
        
        self.filters_panel_container = filter_scroll
        
    def toggle_filters_panel(self):
        """Toggle the visibility of the Filter"""
        self.filters_panel_visible = not self.filters_panel_visible
        self.filters_panel_container.setVisible(self.filters_panel_visible)
        
        # Update button text
        if self.filters_panel_visible:
            self.filter_toggle_button.setText("»")
            self.filter_toggle_button.setToolTip("Hide Filter")
        else:
            self.filter_toggle_button.setText("«")
            self.filter_toggle_button.setToolTip("Show Filter")
    
    def get_selected_error_types(self):
        """Get list of checked error types from filter tree"""
        selected_types = set()
        
        # Iterate through all category items (top level)
        root = self.filter_tree.invisibleRootItem()
        for i in range(root.childCount()):
            category_item = root.child(i)
            
            # Iterate through all error type items (children)
            for j in range(category_item.childCount()):
                type_item = category_item.child(j)
                if type_item.checkState(0) == Qt.Checked:
                    selected_types.add(type_item.text(0))
        
        return selected_types
    
    def apply_error_filters(self):
        """Apply filters to the error tree view (debounced)"""
        # Restart the debounce timer - this delays the actual filter application
        # If called multiple times rapidly (e.g., when checking/unchecking a category),
        # only the last call will execute after the delay
        self.filter_debounce_timer.stop()
        self.filter_debounce_timer.start()
    
    def _apply_error_filters_impl(self):
        """Internal implementation of apply_error_filters (called after debounce delay)"""
        if not hasattr(self, 'error_tree') or not self.error_tree.model():
            return
        
        # Show brief progress indicator for filtering
        qt.QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        
        selected_types = self.get_selected_error_types()
        
        # Update the model's filter - much more efficient than hiding rows
        model = self.error_tree.model()
        if hasattr(model, 'set_filter'):
            model.set_filter(selected_types if selected_types else set())  # type: ignore
            logger.debug(f"Applied filter: {len(selected_types)} error types selected")
        
        # Restore cursor
        qt.QApplication.restoreOverrideCursor()
    
    def create_log_section(self):
        """Create the log section at the bottom"""
        log_group = qt.QGroupBox("Log")
        log_layout = qt.QVBoxLayout(log_group)
        log_layout.setContentsMargins(5, 5, 5, 5)        
        self.logger = QTextEditLogger(self)
        self.logger.setFormatter(logging.Formatter(
            '[%(asctime)s,%(msecs)03d][%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.addHandler(self.logger)
        # self.logs.setReadOnly(True)
        log_layout.addWidget(self.logger.widget)
        # Set minimum size for log group to prevent collapse
        log_group.setMinimumHeight(80)        
        # Add to vertical splitter instead of main layout
        self.main_v_splitter.addWidget(log_group)
    
    
    
    # def _update_mod_manager_load_order(self):
    #     """Update ModManager's load order based on current table state"""
    #     load_order = self._get_load_order()
    #     self.mod_manager.set_load_order(load_order)
    
                
                    
    
    
    # Menu bar actions
    def open_settings(self):
        """Open settings dialog"""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_()== qt.QDialog.Accepted:
            dialog.save_settings()
            logger.debug("Settings saved")
        else:
            logger.debug("Settings dialog cancelled")
    
    def show_help(self):
        """Show help/about dialog"""
        logger.info("Help dialog opened")
        # TODO: Implement help dialog
    
    # Top button actions
    def analyze_mod_list(self):
        """Analyze mod list for conflicts"""
        logger.info("Analyzing mod list...")
        
        # Show progress and set busy cursor
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        qt.QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        
        # Disable buttons during analysis
        self.analyze_mod_list_button.setEnabled(False)
        self.analyze_errors_button.setEnabled(False)
        
        # Create and start worker thread
        self.file_tree_worker = FileTreeWorker(
            self.mod_manager,
            file_range="all", #TODO: add option to settings
            conflict_check_range="enabled", #TODO: add option to settings
            # conflict_check_range=None,
            max_workers=self.settings.max_workers or 4,
        )
        self.file_tree_worker.finished.connect(self._on_mod_analysis_complete)
        self.file_tree_worker.error.connect(self._on_mod_analysis_error)
        self.file_tree_worker.start()
    
    def _on_mod_analysis_complete(self):
        """Called when mod analysis is complete"""
        logger.info("Mod analysis complete")
        
        # Hide progress and restore cursor
        self.progress_bar.setVisible(False)
        qt.QApplication.restoreOverrideCursor()
        
        # Re-enable buttons
        self.analyze_mod_list_button.setEnabled(True)
        self.analyze_errors_button.setEnabled(True)  # Enable error analysis after mod list is ready
        
        # Populate conflict tree with results
        self.populate_conflict_tree()
        # Clean up worker
        if self.file_tree_worker:
            self.file_tree_worker.deleteLater()
            self.file_tree_worker = None
    
    def _on_mod_analysis_error(self, error_msg):
        """Called when mod analysis encounters an error"""
        logger.error(f"Error during mod analysis: {error_msg}")
        
        # Hide progress and restore cursor
        self.progress_bar.setVisible(False)
        qt.QApplication.restoreOverrideCursor()
        
        # Re-enable buttons
        self.analyze_mod_list_button.setEnabled(True)
        # Don't enable error analysis button if mod analysis failed
        
        # Clean up worker
        if self.file_tree_worker:
            self.file_tree_worker.deleteLater()
            self.file_tree_worker = None
        
    def _build_error_sources(self):
        """Get error sources from analyzer"""
        # TODO: Is this still needed?
        self.analyzer.load_error_logs(self.settings.error_log_path)
    
    def _populate_error_table(self):
        """Populate error tree view after analysis is complete using lazy loading model"""
        
        # Show progress during model creation
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        qt.QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        
        # Force UI update
        qt.QApplication.processEvents()
        
        # Create and set the lazy loading model
        model = ErrorTreeModel(self.analyzer)
        self.error_tree.setModel(model)
        
        # Hide progress
        self.progress_bar.setVisible(False)
        qt.QApplication.restoreOverrideCursor()
        
        # Connect selection changed signal after model is set
        if self.error_tree.selectionModel():
            self.error_tree.selectionModel().selectionChanged.connect(self.on_error_selection_changed)
        
        # Apply current filters
        self.apply_error_filters()
        
        # Expand first level (mods) by default if desired
        # for row in range(model.rowCount()):
        #     index = model.index(row, 0)
        #     self.error_tree.expand(index)
    
    def analyze_errors(self):
        """Analyze errors from log file"""
        logger.info("Analyzing errors...")
        self.t0 = QtCore.QTime.currentTime()
        # Show progress and set busy cursor
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        qt.QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        
        # Disable buttons during analysis
        self.analyze_errors_button.setEnabled(False)
        self.analyze_mod_list_button.setEnabled(False)
        self.analyzer.reset() # Reset previous analysis
        if self.settings.debug:
            # Single-threaded analysis (blocking)
            try:
                self.analyzer.load_error_logs(self.settings.error_log_path)
                self._on_error_analysis_complete()
            except Exception as e:
                logger.exception(f"Error during error analysis: {e}")
                self._on_error_analysis_error(str(e))
        else:
            # Create and start worker thread
            self.error_worker = ErrorAnalysisWorker(self.analyzer, self.settings.error_log_path)
            self.error_worker.finished.connect(self._on_error_analysis_complete)
            self.error_worker.error.connect(self._on_error_analysis_error)
            self.error_worker.start()
    def _on_error_analysis_complete(self):
        """Called when error analysis is complete"""
        self._populate_error_table()
        logger.info("Error analysis complete")
        
        # Hide progress and restore cursor
        self.progress_bar.setVisible(False)
        qt.QApplication.restoreOverrideCursor()
        
        # Re-enable buttons
        self.analyze_errors_button.setEnabled(True)
        self.analyze_mod_list_button.setEnabled(True)
        
        # Clean up worker
        if self.error_worker:
            self.error_worker.deleteLater()
            self.error_worker = None
        self.t1 = QtCore.QTime.currentTime()
        logger.info("Error analysis took %s ms", self.t0.msecsTo(self.t1))
    
    def _on_error_analysis_error(self, error_msg):
        """Called when error analysis encounters an error"""
        logger.exception(f"Error during error analysis: {error_msg}")
        
        # Hide progress and restore cursor
        self.progress_bar.setVisible(False)
        qt.QApplication.restoreOverrideCursor()
        
        # Re-enable buttons
        self.analyze_errors_button.setEnabled(True)
        self.analyze_mod_list_button.setEnabled(True)
        
        # Clean up worker
        if self.error_worker:
            self.error_worker.deleteLater()
            self.error_worker = None
        
        
    def export_json(self):
        """Export data to JSON"""
        logger.info("Exporting to JSON...")
        # TODO: Implement JSON export
    
    def open_error_log(self):
        """Open error.log file"""
        logger.info("Opening error.log...")
        error_log_path = self.settings.error_log_path
        if not error_log_path or not Path(error_log_path).is_file():
            logger.error("error.log file not found at configured path.")
            return
        os.startfile(error_log_path)
        
    def launch_game(self):
        """Launch the game executable"""
        # self.apply_profile()  # Ensure profile is applied before launching
        self.mod_manager.save_profile("<Default>")
        logger.info("Launching game...")
        self.game_launcher.launch_game(exe_args=self.settings.exe_args)
        
    def on_error_selection_changed(self, selected, deselected):
        """Handle selection change in error tree (Model/View architecture)"""
        indexes = selected.indexes()
        if not indexes:
            return
        
        # Get the first selected index (column 0)
        index = indexes[0]
        if not index.isValid():
            return
        
        model = self.error_tree.model()
        if not model:
            return
        
        # Get node from index
        node = index.internalPointer()
        if not node:
            return
        
        # Store selected node for context menu actions
        self.selected_error_node = node
        
        # Log selection
        if node.type == "error" and node.error_data:
            err_id, source = node.error_data
            logger.info(f"Selected error in: {source.file if hasattr(source, 'file') else 'Unknown'}")
        else:
            # Parent node (mod, folder, or file)
            logger.info(f"Selected: {node.name}")
    
    def on_conflict_selection_changed(self, selected, deselected):
        """Handle selection change in conflict tree (Model/View architecture)"""
        indexes = selected.indexes()
        if not indexes:
            return
        
        # Get the first selected index
        index = indexes[0]
        if not index.isValid():
            return
        
        model = self.conflict_tree.model()
        if not model:
            return
        
        # Get node from index
        node = index.internalPointer()
        if not node:
            return
        
        # Store selected node for context menu actions
        self.selected_conflict_node = node
        
        # Log selection
        if node.type == "identifier":
            logger.debug("Selected conflict: %s :: %s", node.filename, node.name)
        else:
            # Parent node (mod, folder, or file)
            logger.debug("Selected: %s", node.name)
    
    def on_error_item_clicked(self, item: qt.QTreeWidgetItem, column: int):
        """Handle click on error tree item (legacy qt.QTreeWidget - deprecated)"""
        # Get the source data stored in the item
        source = item.data(0, Qt.UserRole)
        
        if source:
            logger.info(f"Selected error in: {source.file}")
        else:
            # This is a parent item (file grouping)
            file_path = item.text(0)
            logger.info(f"Selected file group: {file_path}")
    
    def on_conflict_item_clicked(self, item: qt.QTreeWidgetItem, column: int):
        """Handle click on conflict tree item"""
        line = item.text(0)
        element = item.text(1)
        message = item.text(2)
        
        logger.info(f"Selected conflict at line {line}: {element}")
    
    def show_error_context_menu(self, position):
        """Show context menu for error tree (right-click menu)"""
        # Get the item at the click position
        index = self.error_tree.indexAt(position)
        if not index.isValid():
            return
        
        # Get the node to check if it's an actual error (not just a folder)
        node = index.internalPointer()
        if not node:
            return
        
        # Create context menu
        context_menu = qt.QMenu(self)
        
        # Add actions
        open_file_action = context_menu.addAction("📁 Reveal in File Explorer")
        open_file_action.triggered.connect(self.open_file)
        
        show_error_log_action = context_menu.addAction("📄 Show Line in error.log")
        show_error_log_action.triggered.connect(self.show_line_in_error_log)
        
        open_mod_file_action = context_menu.addAction("📝 Open Line in Text Editor")
        open_mod_file_action.triggered.connect(self.open_line_in_editor)
        
        context_menu.addSeparator()
        
        fix_selected_action = context_menu.addAction("🔧 Fix Selected Error")
        fix_selected_action.triggered.connect(self.fix_selected_error)
        
        # Disable actions if this is not an actual error node
        if node.type != NodeType.Virtual: # TODO: Add a Error Type
            fix_selected_action.setEnabled(False)
            show_error_log_action.setEnabled(False)
            open_mod_file_action.setEnabled(False)
        
        # Show the menu at the cursor position
        context_menu.exec_(self.error_tree.viewport().mapToGlobal(position))
    
    def show_conflict_context_menu(self, position):
        """Show context menu for conflict tree (right-click menu)"""
        # Get the item at the click position
        index = self.conflict_tree.indexAt(position)
        if not index.isValid():
            return
        
        # Get the node to check if it's an actual conflict identifier
        node = index.internalPointer()
        if not node:
            return
        
        # Create context menu
        context_menu = qt.QMenu(self)
        
        # Add actions
        open_file_action = context_menu.addAction("📁 Reveal in File Explorer")
        open_file_action.triggered.connect(self.open_file)
        
        open_mod_file_action = context_menu.addAction("📝 Open line in Text Editor")
        open_mod_file_action.triggered.connect(self.open_line_in_editor)
        
        # Disable actions if this is not an actual conflict identifier node
        if node.type != NodeType.Identifier:
            open_mod_file_action.setEnabled(False)
        
        # Show the menu at the cursor position
        context_menu.exec_(self.conflict_tree.viewport().mapToGlobal(position))
                    
    def populate_conflict_tree(self):
        """Populate conflict tree view with lazy loading model"""
        logger.info("Populating conflict tree...")
        
        # Create and set the lazy loading model
        model = ConflictTreeModel(self.mod_manager)
        self.conflict_tree.setModel(model)
        
        # Connect selection changed signal after model is set
        if self.conflict_tree.selectionModel():
            self.conflict_tree.selectionModel().selectionChanged.connect(self.on_conflict_selection_changed)
        
        # Set column widths after setting model
        self.conflict_tree.setColumnWidth(0, 400)  # File/Def
        self.conflict_tree.setColumnWidth(1, 150)  # Filename
        self.conflict_tree.setColumnWidth(2, 80)   # Line
        
        total_conflicts = len(self.mod_manager.conflict_identifiers)
        logger.info(f"Populated conflict tree with {total_conflicts} conflict definitions using lazy loading")
        
    # Right panel actions
    def open_file(self) -> None:
        """Open the selected file or folder"""
        try:
            path_to_open: Optional[Path] = None
            
            # Try error node first
            if self.selected_error_node :
                path_to_open = self.selected_error_node.path            
            # Try conflict node
            elif self.selected_conflict_node:
                # Check if node has a path attribute
                if isinstance(self.selected_conflict_node, ConflictTreeNodeEntry) and self.selected_conflict_node.full_path and self.selected_conflict_node.full_path.exists():
                    path_to_open = self.selected_conflict_node.full_path
                    if self.selected_conflict_node.type == NodeType.Identifier:
                        # If it's an identifier, open the parent file
                        path_to_open = path_to_open.parent
                # Fallback: try to get path from filename
                else:                    
                    path_to_open = self.selected_conflict_node.path
            if path_to_open is not None and path_to_open.parts[0] == "%CK3_MODS_DIR%":
                path_to_open = CK3_MODS_DIR.joinpath(*path_to_open.parts[1:])
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
    
    def open_file_at_line(self, file_path: Path, line=0 , editor=None) -> None:        
        """Open a file at a specific line number in the specified text editor"""
        import shutil, subprocess
        if editor is None:
            pass
        elif editor.lower() in ("notepadpp", "notepad++"):
            exe = shutil.which("notepad++")
            if exe:
                subprocess.Popen([exe, "multiInst", f"-n{line}", f'"{str(file_path)}"'])
                return
        elif editor.lower() in ("vscode", "code"):
            exe = shutil.which("code")
            if exe:
                subprocess.Popen([exe, "-g", f'{str(file_path)}:{line}'])
                return
        logger.warning("Opening file without specific line number (editor not supported)")
        return os.startfile(file_path)

    
    def show_line_in_error_log(self) -> None:
        """Show line in error.log and open it in default text editor"""
        try:
            if not self.selected_error_node or self.selected_error_node.type != "error":
                logger.warning("Please select an error item first")
                return
            
            if not self.selected_error_node.error_data:
                logger.warning("No error data available")
                return
            
            err, source = next(iter(self.selected_error_node.error_data.items()))
            
            # Find the error.log file
            error_log_path = Path(self.settings.error_log_path)
            
            if not error_log_path.exists():
                logger.error(f"error.log not found at: {error_log_path}")
                return
            err:ParsedError = self.analyzer.errors[err.id]
            self.open_file_at_line(
                error_log_path, 
                err.log_line or 0,
                "notepad++"                
            )
            
            # Log the line number if available
            if hasattr(source, 'log_line') and source.line:
                logger.info(f"Opened error.log - Error at log line: {source.line}")
            else:
                logger.info(f"Opened error.log - Search for: {source.file if hasattr(source, 'file') else 'N/A'}")
                
        except Exception as e:
            logger.error(f"Failed to open error.log: {e}")
    
    def open_line_in_editor(self) -> None:
        """Open the mod file in default text editor at the specific line"""
        try:
            file_path: Optional[Path] = None
            line_number: Optional[str] = None
            # Try error node first
            if self.selected_error_node :
                file_path = self.selected_error_node.path
                line_number = str(self.selected_error_node.line) if self.selected_error_node.line else None
            # Try conflict node
            elif self.selected_conflict_node:
                # Check if node has a path attribute
                if isinstance(self.selected_conflict_node, ConflictTreeNodeEntry) and self.selected_conflict_node.full_path and self.selected_conflict_node.full_path.exists():
                    file_path = self.selected_conflict_node.full_path
                    if self.selected_conflict_node.type == NodeType.Identifier:
                        # If it's an identifier, open the parent file
                        line_number = str(self.selected_conflict_node.line or "") or None
                # Fallback: try to get path from filename
                else:                    
                    file_path = self.selected_conflict_node.path
            if file_path is not None and file_path.parts[0] == "%CK3_MODS_DIR%":
                file_path = CK3_MODS_DIR.joinpath(*file_path.parts[1:])
            if not file_path:
                logger.warning("No file path available")
                return
            
            if not file_path.exists():
                logger.error(f"File does not exist: {file_path}")
                return
            
            # Open the file in default text editor
            # Note: Windows doesn't support opening at specific line via os.startfile
            # Users will need to manually navigate to the line
            self.open_file_at_line(
                file_path, 
                int(line_number or 0),
                "vscode"                
            )
            
            if line_number:
                logger.info(f"Opened file: {file_path} (Navigate to line: {line_number})")
            else:
                logger.info(f"Opened file: {file_path}")
                
        except Exception as e:
            logger.error(f"Failed to open mod file: {e}")
    
    def fix_selected_error(self):
        """Fix the selected error"""
        logger.info("Fixing selected error...")
        # TODO: Implement error fixing
    
    def fix_all_encoding_errors(self):
        """Fix all encoding errors"""
        logger.info("Fixing all encoding errors...")
        # TODO: Implement fixing all encoding errors
    @property
    def existing_profiles(self):
        """Generator for existing mod profiles"""
        profiles_dir = Path("profiles")
        if not profiles_dir.exists():
            return
        for profile_path in profiles_dir.iterdir():
            if profile_path.is_dir():
                yield profile_path.name
    def load_mods(self):
        """Load mods from ModManager"""
        logger.info("Loading mods...")
        self.load_profile()
        # self.mod_manager.build_mod_list( # loads Default mods
        #     path=self.settings.ck3_mods_path,
        #     enabled_only=self.settings.enabled_only,
        # )
        profile = self.profile_combo.currentText()
        
        
        # Populate table from ModManager.mod_list
        load_order: list[str] = self.mod_manager.mod_list.load_order
        self.mod_table.setRowCount(0)
        for row, mod_name in enumerate(load_order):
            mod: Mod = self.mod_manager.mod_list[mod_name]
            self.mod_table.insertRow(row)
            
            # Mod Name with checkbox
            name_item = qt.QTableWidgetItem(getattr(mod, "name", ""))
            # name_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name_item.setCheckState(Qt.Checked if getattr(mod, "enabled", False) else Qt.Unchecked)
            
            # Priority (load order)
            priority_item = qt.QTableWidgetItem(str(getattr(mod, "load_order", "-")))
            priority_item.setTextAlignment(Qt.AlignCenter)
            
            # Conflicts
            conflicts_item = qt.QTableWidgetItem("-")
            conflicts_item.setTextAlignment(Qt.AlignCenter)
            
            # Tags
            tags_item = qt.QTableWidgetItem(", ".join(mod.tags))  # Placeholder
            
            # version
            version_item = qt.QTableWidgetItem(mod.version)
            if mod.is_outdated(current_version=self.game_launcher.settings.version):
                outdated_item = qt.QTableWidgetItem("⚠️")
                outdated_item.setToolTip(f"Outdated")
            else:
                outdated_item = qt.QTableWidgetItem("")
            supported_version_item = qt.QTableWidgetItem(mod.supported_version or "")
            
            mod_dir_item = qt.QTableWidgetItem(str(mod.path))
            is_steam_mod = mod.remote_file_id != ''
            if is_steam_mod:
                icon_path = str(Path(__file__).parent / "icons" / "icons8-steam-48.png")
                mod_source_item = qt.QTableWidgetItem(QIcon(icon_path),'')
            else:
                icon_path = str(Path(__file__).parent / "icons" / "local-48.png")
                mod_source_item = qt.QTableWidgetItem(QIcon(icon_path),'')
            self.mod_table.setItem(row, 0, name_item)
            self.mod_table.setItem(row, 1, mod_source_item)
            self.mod_table.setItem(row, 2, priority_item)
            self.mod_table.setItem(row, 3, conflicts_item)
            self.mod_table.setItem(row, 4, tags_item)
            self.mod_table.setItem(row, 5, version_item)
            self.mod_table.setItem(row, 6, outdated_item)
            self.mod_table.setItem(row, 7, supported_version_item)
            self.mod_table.setItem(row, 8, mod_dir_item)

        logger.info(f"Loaded {len(load_order)} mods")
    def create_new_profile(self):
        """Create a new mod profile."""
        logger.info("Creating new mod profile... ")
        # add a profile to the combo box
        profile_name, ok = qt.QInputDialog.getText(
            self,
            "Create New Mod Profile",
            "Enter profile name:"
        )
        if ok and profile_name:
            # Check for duplicate profile names
            if profile_name in self.existing_profiles:
                qt.QMessageBox.warning(
                    self,
                    "Duplicate Profile",
                    f"Profile '{profile_name}' already exists. Please choose a different name."
                )
                logger.warning(f"Profile creation failed: '{profile_name}' already exists")
                return
            
            # Create profile directory
            profile_dir = Path("profiles") / profile_name
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy dlc_load.json from CK3 documents folder to the new profile
            source_dlc_load = Path(self.mod_manager.DOCS_DIR) / "dlc_load.json"
            dest_dlc_load = profile_dir / "dlc_load.json"
            shutil.copy2(source_dlc_load, dest_dlc_load)
            
            self.profile_combo.addItem(profile_name)
            self.profile_combo.setCurrentText(profile_name)
            logger.info(f"Created new profile: {profile_name}")
        
        
        
    def load_profile(self):
        """Load a mod profile from file and apply to the mod list."""
        profile_name = self.profile_combo.currentText()
        if profile_name == "<Default>": # load from dlc_load.json
            self.mod_manager.load_profile(
                "<Default>", 
                enabled_only=self.settings.enabled_only)
        else:
            profile_path = Path("profiles")/profile_name/"dlc_load.json"
            self.mod_manager.load_profile(
                profile_path,
                enabled_only=self.settings.enabled_only)
            
    def save_profile(self):        
        """Save current mod list as a profile."""
        self.mod_table._update_mod_manager()
        profile_name = self.profile_combo.currentText()
        if profile_name == "<Default>": # load from dlc_load.json
            self.mod_manager.save_profile("<Default>")
            logger.info("Saved current mod list to <Default> profile")
        else:
            profile_path = Path("profiles")/profile_name/"dlc_load.json"
            self.mod_manager.save_profile(profile_path)
            logger.info(f"Saved current mod list to profile: {profile_name}")
    # def apply_profile(self):
    #     self.mod_manager.save_profile("<Default>")
    def _debug_show_mod_list(self):
        for k,v in self.mod_manager.mod_list.items():
            logger.debug(v._sort_index, v.enabled, k, v.load_order)            

if __name__ == "__main__":
    app = qt.QApplication(sys.argv)
    mainWin = CK3ModManagerApp()
    mainWin.show()
    
    sys.exit(app.exec_())



