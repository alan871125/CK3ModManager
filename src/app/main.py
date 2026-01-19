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
from datetime import datetime
from mod_analyzer.mod.descriptor import Mod
from mod_analyzer.mod.mod_list import ModList
from mod_analyzer.mod.manager import ModManager
from mod_analyzer.mod.paradox import DefinitionNode, NodeType
from mod_analyzer.mod.mod_loader import update_workshop_mod_descriptor_files
from mod_analyzer.error import patterns
from mod_analyzer.error.analyzer import ErrorAnalyzer, ParsedError
from app.mod_table import ModTableWidget, ModTableWidgetItem
from app.conflict_model import ConflictTreeModelWIP, ConflictTreeModel
from app.error_model import ErrorTreeModel
from app.tree_nodes import ConflictTreeNodeEntry, ErrorTreeNode, ConflictTreeNode, TreeNode
from app.workers import FileTreeWorker, ErrorAnalysisWorker
from app.settings import Settings, SettingsDialog
from app.game import GameLauncher
from constants import MODS_DIR
from app.tree_views import ConflictTreeWidget, ErrorTreeWidget

logging.basicConfig(format='[%(asctime)s][%(levelname)s] %(message)s', level=logging.INFO)
# Set up loggers
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.getLogger('mod_analyzer').setLevel(logging.DEBUG)

def init_log_file(max_logs: int = 5) -> None:
    """Initialize log file in logs/ directory with timestamped filename.
    remove old log files exceeding max_logs.
    """
    existing_logs = sorted(Path("logs").glob("*.log"), key=os.path.getmtime)
    for log_file in existing_logs[:-max_logs + 1]:
        try:
            log_file.unlink()
        except Exception as e:
            logger.error(f"Failed to delete old log file {log_file}: {e}")    
    
    # Add a logger to write a app.log file
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(f"logs/{now}.log")
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text("")  # create empty log file
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s][%(levelname)s] %(message)s')
    file_handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    if not any(
        isinstance(h, logging.FileHandler)
        and str(getattr(h, 'baseFilename', '')).lower().endswith('app.log')
        for h in root_logger.handlers
    ):
        root_logger.addHandler(file_handler)


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
        # Update workshop mod descriptors on startup        
        update_workshop_mod_descriptor_files()        
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
        # Central widget and main layout
        self.central_widget = qt.QWidget()
        self.setCentralWidget(self.central_widget)        
        self.main_layout = qt.QVBoxLayout(self.central_widget)
        
        # Top button panel
        self.create_top_buttons()
        
        # Main vertical splitter (splits content and log)
        self.main_v_splitter = qt.QSplitter(Qt.Vertical)
        self.main_layout.addWidget(self.main_v_splitter)
        
        # ----- Main content area -----
        left_panel = self.create_left_panel()   # Left panel with mod list
        right_panel = self.create_right_panel() # Right panel with analysis tabs        
        # Tab widget with resizable splitter
        self.tab_splitter = qt.QSplitter(Qt.Horizontal)
        # Left tab widget - Mod List only
        self.tab_splitter.addWidget(left_panel)
        self.tab_splitter.addWidget(right_panel)
        # Right side - Filter (hidable)
        self.create_filters_panel()
        self.toggle_filters_panel()
        self.tab_splitter.addWidget(self.filters_panel_container)
        # Set initial splitter sizes (mod list, analysis tabs, Filter)
        self.tab_splitter.setStretchFactor(0, 3)  # Mod List
        self.tab_splitter.setStretchFactor(1, 3)  # Error Analyzer/Conflict Table
        self.tab_splitter.setStretchFactor(2, 1)  # Filters
        self.main_v_splitter.addWidget(self.tab_splitter)
        # ------------------------------
        # Create menu bar
        self.create_menu_bar()
        
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
        
        self.mod_tab_widget = ModTableWidget(self.mod_manager)
        left_layout.addWidget(self.mod_tab_widget)
        return left_widget
        
    def create_right_panel(self):
        """Create the right panel with Error Analyzer and Conflict Table tabs"""
        right_widget = qt.QWidget()
        right_layout = qt.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        actions_layout = qt.QHBoxLayout()
        self.fix_all_button = qt.QPushButton("Fix All Encoding Errors")
        self.fix_all_button.clicked.connect(self.fix_all_encoding_errors)
        actions_layout.addWidget(self.fix_all_button)
        actions_layout.addStretch()
        right_layout.addLayout(actions_layout)
        
        self.analysis_tab_widget = qt.QTabWidget()
        self.conflict_tree_widget = ConflictTreeWidget(self.mod_manager, self.settings, parent=self)
        self.analysis_tab_widget.addTab(self.conflict_tree_widget, "Conflict Table")
        self.error_tree_widget = ErrorTreeWidget(self.mod_manager, self.settings, parent=self)
        self.analysis_tab_widget.addTab(self.error_tree_widget, "Error Analyzer")
        right_layout.addWidget(self.analysis_tab_widget)
        button_layout = qt.QHBoxLayout()
        button_layout.addStretch()
        filter_label = qt.QLabel("Filter")
        button_layout.addWidget(filter_label)
        self.filter_toggle_button = qt.QPushButton("«")
        self.filter_toggle_button.setMaximumSize(20, 30)
        self.filter_toggle_button.clicked.connect(self.toggle_filters_panel)
        self.filter_toggle_button.setToolTip("Hide Filter")
        button_layout.addWidget(self.filter_toggle_button)
        right_layout.addLayout(button_layout)
        return right_widget
    
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
        error_tree = self.error_tree_widget.tree_view
        if not error_tree.model():
            return        
        # Show brief progress indicator for filtering
        qt.QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        
        selected_types = self.get_selected_error_types()
        
        # Update the model's filter - much more efficient than hiding rows
        model = error_tree.model()
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
        root_logger = logging.getLogger()
        if self.logger not in root_logger.handlers:
            root_logger.addHandler(self.logger)
        # self.logs.setReadOnly(True)
        log_layout.addWidget(self.logger.widget)
        # Set minimum size for log group to prevent collapse
        log_group.setMinimumHeight(80)        
        # Add to vertical splitter instead of main layout
        self.main_v_splitter.addWidget(log_group)
    
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
        error_tree = self.error_tree_widget.tree_view
        error_tree.setModel(model)
        
        # Hide progress
        self.progress_bar.setVisible(False)
        qt.QApplication.restoreOverrideCursor()
        
        # Connect selection changed signal after model is set
        if error_tree.selectionModel():
            error_tree.selectionModel().selectionChanged.connect(self.error_tree_widget.on_selection_changed)
        
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
        
        # Export mods to SQLite
        try:
            # Import here to avoid circular imports if any, or just to keep it localized
            # Assuming sqlite_exporter is in the python path (src folder)
            from sqlite_exporter import CK3ModExporter
            
            # Get enabled mods
            enabled_mods = self.mod_manager.mod_list.enabled
            
            # Get game data path from launcher settings
            game_data_path = self.game_launcher.settings.gameDataPath
            
            exporter = CK3ModExporter(str(game_data_path))
            
            # Use current profile name as playset name, or "CK3ModManager"
            playset_name = self.profile_combo.currentText()
            if playset_name == "<Default>":
                playset_name = "CK3ModManager"
                
            logger.info(f"Exporting playset '{playset_name}' to SQLite database...")
            exporter.export_mods(
                playset_name=playset_name,
                mod_list = self.mod_manager.mod_list,
                enabled_only = True,
            )
            logger.info("Export successful.")
            
        except Exception as e:
            logger.error(f"Failed to export mods to SQLite: {e}")
            qt.QMessageBox.warning(self, "Export Error", f"Failed to export mods to database:\n{e}\n\nThe game might not load mods correctly.")

        logger.info("Launching game...")
        self.game_launcher.launch_game(exe_args=self.settings.exe_args)
     
    
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
                        
    def populate_conflict_tree(self):
        """Populate conflict tree view with lazy loading model"""
        logger.info("Populating conflict tree...")
        
        # Create and set the lazy loading model
        if self.settings.active_conflict_scan:
            model = ConflictTreeModelWIP(self.mod_manager)
        else:
            model = ConflictTreeModel(self.mod_manager)
        conflict_tree = self.conflict_tree_widget.tree_view
        conflict_tree.setModel(model)
        
        # Connect selection changed signal after model is set
        if conflict_tree.selectionModel():
            conflict_tree.selectionModel().selectionChanged.connect(self.conflict_tree_widget.on_selection_changed)
        
        # Set column widths after setting model
        conflict_tree.setColumnWidth(0, 400)  # File/Def
        conflict_tree.setColumnWidth(1, 150)  # Filename
        conflict_tree.setColumnWidth(2, 80)   # Line
        
        total_conflicts = len(self.mod_manager.conflict_identifiers)
        logger.info(f"Populated conflict tree with {total_conflicts} conflict definitions using lazy loading")
    
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
            source_dlc_load = Path(self.settings.ck3_docs_path) / "dlc_load.json"
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
                profile_only=self.settings.profile_only)
        else:
            profile_path = Path("profiles")/profile_name/"dlc_load.json"
            self.mod_manager.load_profile(
                profile_path,
                profile_only=self.settings.profile_only)
            
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
    init_log_file()
    app = qt.QApplication(sys.argv)
    mainWin = CK3ModManagerApp()
    mainWin.show()
    
    sys.exit(app.exec_())



