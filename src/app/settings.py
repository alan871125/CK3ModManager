from doctest import debug
import os
import json
import logging  
from pathlib import Path
from dataclasses import dataclass, asdict, field
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox, QHBoxLayout,
    QCheckBox, QSpinBox, QLineEdit, QPushButton, QFileDialog, QDialogButtonBox
)

from app import game


from .directory import CK3_MODS_DIR

logger = logging.getLogger(__name__)

@dataclass
class Settings:
    max_workers: int = os.cpu_count() or 4
    enabled_only: bool = False
    ck3_docs_path: str = str(Path.home()/"Documents/Paradox Interactive/Crusader Kings III")
    ck3_mods_path: str = str(CK3_MODS_DIR)
    error_log_path: str = str(Path.home()/"Documents/Paradox Interactive/Crusader Kings III/error.log")
    launcher_settings_path: str = r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\launcher\launcher-settings.json"
    exe_args: str = "-gdpr-compliant"# default exe args from launcher-settings.json
    debug: bool = False
    check_conflict_on_startup: bool = False
    game_language: str = "english"
    
    def asdict(self) -> dict:
        return asdict(self)
    @staticmethod    
    def load(path: str|Path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return Settings(**data)
        except Exception as e:
            logger.error(f"Failed to load settings from {path}: {e}")
    def save(self, path: str|Path):
        try:
            with open(path, "w") as f:
                json.dump(self.asdict(),  f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Failed to save settings to {path}: {e}")
    
class SettingsDialog(QDialog):
    """Settings dialog window"""
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings: Settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumSize(700, 270)        
        self.init_ui()
    def init_ui(self):
        """Initialize the settings UI"""
        layout = QVBoxLayout(self)
        
        # Create form layout for settings
        form_layout = QFormLayout()
        
        # General Settings Group
        general_group = QGroupBox("General Settings")
        general_layout = QFormLayout(general_group)
        self.check_conflict_on_startup = QCheckBox()
        self.check_conflict_on_startup.setChecked(self.settings.check_conflict_on_startup)
        general_layout.addRow("Auto check mod conflicts on Startup", self.check_conflict_on_startup)
        
        self.max_workers_spinbox = QSpinBox()
        self.max_workers_spinbox.setMinimum(1)
        self.max_workers_spinbox.setMaximum(32)
        self.max_workers_spinbox.setValue(self.settings.max_workers)
        general_layout.addRow("Max worker threads:", self.max_workers_spinbox)
        layout.addWidget(general_group)
        
        # Mod List Settings Group
        mods_group = QGroupBox("Mod List Settings")
        mods_layout = QFormLayout(mods_group)
        self.enabled_mods_only = QCheckBox()
        self.enabled_mods_only.setToolTip("If checked, only enabled mods will be loaded.")
        self.enabled_mods_only.setChecked(self.settings.enabled_only)
        mods_layout.addRow("Load Only Enabled Mods:", self.enabled_mods_only)
        layout.addWidget(mods_group)
        
        # ========== Paths Settings Group ==========
        paths_group = QGroupBox("Paths")
        paths_layout = QFormLayout(paths_group)
        
        # CK3 Documents Path
        ck3_docs_layout = QHBoxLayout()
        self.ck3_docs_path_edit = QLineEdit()
        self.ck3_docs_path_edit.setText(self.settings.ck3_docs_path)
        self.ck3_docs_path_edit.setReadOnly(False)
        ck3_docs_layout.addWidget(self.ck3_docs_path_edit)
        self.ck3_docs_path_button = QPushButton("Browse")
        self.ck3_docs_path_button.clicked.connect(self.browse_ck3_docs_path)
        ck3_docs_layout.addWidget(self.ck3_docs_path_button)
        paths_layout.addRow("CK3 Documents Path:", ck3_docs_layout)
        
        # Mods Directory
        mods_path_layout = QHBoxLayout()
        self.mods_path_edit = QLineEdit()
        self.mods_path_edit.setText(self.settings.ck3_mods_path)
        self.mods_path_edit.setReadOnly(False)
        mods_path_layout.addWidget(self.mods_path_edit)
        self.mods_path_button = QPushButton("Browse")
        self.mods_path_button.clicked.connect(self.browse_mods_path)
        mods_path_layout.addWidget(self.mods_path_button)
        paths_layout.addRow("Mods Directory:", mods_path_layout)
        # Error Log Path
        error_log_layout = QHBoxLayout()
        self.error_log_path_edit = QLineEdit()
        self.error_log_path_edit.setText(self.settings.error_log_path)
        self.error_log_path_edit.setReadOnly(False)
        error_log_layout.addWidget(self.error_log_path_edit)
        self.error_log_path_button = QPushButton("Browse")
        self.error_log_path_button.clicked.connect(self.browse_error_log_path)
        error_log_layout.addWidget(self.error_log_path_button)
        paths_layout.addRow("Error Log Path:", error_log_layout)

        # ========== Launcher Settings Group ==========
        launcher_group = QGroupBox("Launcher Settings")
        launcher_layout = QFormLayout(launcher_group)
        launcher_path_layout = QHBoxLayout()
        self.launcher_path_edit = QLineEdit()
        self.launcher_path_edit.setText(self.settings.launcher_settings_path)
        self.launcher_path_edit.setReadOnly(False)
        launcher_path_layout.addWidget(self.launcher_path_edit)
        self.launcher_path_button = QPushButton("Browse")
        self.launcher_path_button.clicked.connect(self.browse_launcher_path)
        launcher_path_layout.addWidget(self.launcher_path_button)
        launcher_layout.addRow("Launcher Settings Path:", launcher_path_layout)
        
        self.exe_args_edit = QLineEdit()
        self.exe_args_edit.setText(self.settings.exe_args)
        launcher_layout.addRow("Launcher Executable Arguments:", self.exe_args_edit)
        # ========================================
        layout.addWidget(paths_group)
        layout.addWidget(launcher_group)
        layout.addStretch()
        # Dialog buttons (OK/Cancel)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    def browse_path(self, target_edit: QLineEdit, default_path: str, title: str, mode: str = "dir"):
        """Generic browse function for selecting a directory or file"""
        current_path = target_edit.text().strip()
        if not current_path or not Path(current_path).exists():
            current_path = default_path
        if mode =='dir':
            path = QFileDialog.getExistingDirectory(
                self, title, current_path,
                QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
            )
        else:
            match mode:
                case "log":
                    options = "Log Files (*.log);;All Files (*)"
                case "json":
                    options = "JSON Files (*.json);;All Files (*)"
                case "file":
                    options = "All Files (*)"
                case _:
                    options = "All Files (*)"
            path, _ = QFileDialog.getOpenFileName(
                self, title, current_path,
                options
            )
        if path:
            target_edit.setText(path)

    def browse_ck3_docs_path(self):
        self.browse_path(
            target_edit=self.ck3_docs_path_edit,
            default_path=self.settings.ck3_docs_path,
            title="Select CK3 Documents Directory",
            mode="dir"
        )

    def browse_mods_path(self):
        self.browse_path(
            target_edit=self.mods_path_edit,
            default_path=self.settings.ck3_mods_path,
            title="Select Mods Directory",
            mode="dir"
        )
    def browse_error_log_path(self):
        self.browse_path(
            target_edit=self.error_log_path_edit,
            default_path=self.settings.error_log_path,
            title="Select error.log File",
            mode="log"
        )
    def browse_launcher_path(self):
        self.browse_path(
            target_edit=self.launcher_path_edit,
            default_path=self.settings.launcher_settings_path,
            title="Select Launcher Settings File",
            mode="json"
        )

            
    def get_settings(self):
        """Return current settings as a dictionary"""
        return {
            'auto_load': self.check_conflict_on_startup.isChecked(),
            'max_workers': self.max_workers_spinbox.value(),
            'ck3_docs_path': self.ck3_docs_path_edit.text(),
            'ck3_mods_path': self.mods_path_edit.text(),
        }
    def save_settings(self):
        """Update settings from the dialog inputs"""
        self.settings.check_conflict_on_startup = self.check_conflict_on_startup.isChecked()
        self.settings.max_workers = self.max_workers_spinbox.value()
        self.settings.enabled_only = self.enabled_mods_only.isChecked()
        self.settings.ck3_docs_path = self.ck3_docs_path_edit.text()
        self.settings.ck3_mods_path = self.mods_path_edit.text()
        self.settings.error_log_path = self.error_log_path_edit.text()
        self.settings.launcher_settings_path = self.launcher_path_edit.text()
        self.settings.exe_args = self.exe_args_edit.text()
        self.settings.save("settings.json")