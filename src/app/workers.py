from PyQt5.QtCore import QThread, pyqtSignal
from pathlib import Path
from app import settings
from mod_analyzer.error.analyzer import ErrorAnalyzer
# Worker thread for building file tree
class FileTreeWorker(QThread):
    """Worker thread for building file tree without blocking UI"""
    finished = pyqtSignal()  # Signal emitted when building completes
    error = pyqtSignal(str)  # Signal emitted if an error occurs
    
    def __init__(self, mod_manager, file_range, conflict_check_range, max_workers):
        super().__init__()
        self.mod_manager = mod_manager
        self.file_range = file_range
        self.conflict_check_range = conflict_check_range
        self.max_workers = max_workers
    
    def run(self):
        """Build file tree in background thread"""
        try:
            self.mod_manager.reset()
            self.mod_manager.build_file_tree(
                file_range=self.file_range,
                conflict_check_range=self.conflict_check_range,
                process_max_workers=self.max_workers
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

# Worker thread for error analysis
class ErrorAnalysisWorker(QThread):
    """Worker thread for running error analysis without blocking UI"""
    finished = pyqtSignal(dict)  # Signal emitted when analysis completes with results
    error = pyqtSignal(str)  # Signal emitted if an error occurs
    
    def __init__(self, analyzer, error_log_path:str|Path):
        super().__init__()
        self.analyzer: ErrorAnalyzer = analyzer
        self.error_log_path:str|Path = error_log_path
    def run(self):
        """Run the analysis in background thread"""
        try:
            self.analyzer.load_error_logs(self.error_log_path)
            error_sources = self.analyzer.error_sources
            self.finished.emit(error_sources)
        except Exception as e:
            self.error.emit(str(e))