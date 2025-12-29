import os
import logging
import PyQt5.QtWidgets as qt
from PyQt5.QtCore import Qt
from typing import Optional

from mod_analyzer.mod.manager import ModManager
from app.qt_widgets import TableWidgetDragRows

logger = logging.getLogger(__name__)
class ModTableWidget(qt.QWidget):
    """Layout for Mod Table with drag-and-drop support"""
    def __init__(self, mod_manager:ModManager):
        super().__init__()
        self.mod_table_layout = qt.QVBoxLayout(self)
        self.mod_table = ModTableWidgetItem(mod_manager)
        self.mod_table_layout.addWidget(self.mod_table)
        search_layout = qt.QHBoxLayout()
        search_label = qt.QLabel("Search:")
        self.mod_search_input = qt.QLineEdit()
        self.mod_search_input.setPlaceholderText("Search mods by name, tags...")
        self.mod_search_input.textChanged.connect(self.filter_mod_list)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.mod_search_input)
        self.mod_table_layout.addLayout(search_layout)        
        self.mod_table_layout.setContentsMargins(5, 5, 5, 5)
        
    def filter_mod_list(self, search_text: str):
        """Filter the mod list based on search text"""
        search_text = search_text.lower()
        
        for row in range(self.mod_table.rowCount()):
            # Get mod name and tags
            name_item = self.mod_table.item(row, 0)
            tags_item = self.mod_table.item(row, 3)
            
            name = name_item.text().lower() if name_item else ""
            tags = tags_item.text().lower() if tags_item else ""
            
            # Show row if search text is in name or tags
            if search_text in name or search_text in tags:
                self.mod_table.setRowHidden(row, False)
            else:
                self.mod_table.setRowHidden(row, True)
        
        
class ModTableWidgetItem(TableWidgetDragRows):
    """Custom QTableWidgetItem to hold a reference to the Mod object."""
    DEFAULT_COL_WIDTHS = [400, 20, 60, 80, 400, 60, 30]  # Default widths for Mod Name, Priority, Conflicts
    _COLUMNS = ["Mod Name", "","Priority", "Conflicts", "Tags", "Version", "Outdated","Supported Version", "Mod Directory"]
    def __init__(self, mod_manager:ModManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
         # Create custom table widget with drag-drop support
        self.setColumnCount(9)
        self.setHorizontalHeaderLabels(self._COLUMNS)
        self.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        # Allow editing only for Priority column
        self.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(False)  # Disable sorting to maintain priority order
        # Make columns resizable and span full width
        header = self.horizontalHeader()
        header.setSectionResizeMode(qt.QHeaderView.Interactive)  # Make all columns resizable
        header.setStretchLastSection(True)  # Last column stretches to fill remaining space
        self.set_column_widths(self.DEFAULT_COL_WIDTHS)  # Initial column widths
        self.mod_manager:ModManager = mod_manager
        
        self.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.row_reordered.connect(self.on_row_reordered)
        
    def get_item(self,row:int, column_name:str):
        """Get item by column name"""
        try:
            col_index = self._COLUMNS.index(column_name)
            return self.item(row, col_index)
        except ValueError:
            return None
    def set_column_widths(self, widths: list[int]):
        """Set column widths based on provided list."""
        for col, width in enumerate(widths):
            self.setColumnWidth(col, width)
    def on_cell_double_clicked(self, row, column):
        """Handle double-click on table cells"""
        # Priority column (index 1) - allow editing
        if column == 1:
            self.edit_priority(row)
        else:
            # Other columns - open mod folder
            self._open_mod_folder(row, column)
    
    def _open_mod_folder(self, row, column):
        """Open the mod folder for the selected row (double-click)."""
        try:
            # Get mod from the row
            if name_item:= self.get_item(row, "Mod Name"):
                mod_name = name_item.text()
                # Find mod in mod_list
                for mod in self.mod_manager.mod_list.values():
                    if getattr(mod, "name", "") == mod_name:
                        path = str(getattr(mod, "path", ""))
                        if path and os.path.exists(path):
                            os.startfile(path)
                            logger.info(f"Opened folder: {path}")
                        else:
                            logger.info(f"Path does not exist: {path}")
                        break
        except Exception as e:
            logger.info(f"Failed to open folder: {e}")
    
    def edit_priority(self, row):
        """Allow editing priority and reorder mods"""
        priority_item = self.get_item(row, "Priority")
        if not priority_item:
            return
        
        old_priority = priority_item.text()
        
        # Get mod name from the first column
        name_item = self.get_item(row, "Mod Name")
        mod_name = name_item.text() if name_item else "this mod"
        
        # Create a dialog to get new priority
        new_priority, ok = qt.QInputDialog.getInt(
            self,
            "Edit Priority",
            f"Enter new priority for {mod_name}:",
            value=int(old_priority) if old_priority.isdigit() else 1,
            min=1,
            max=self.rowCount()
        )
        
        if ok and str(new_priority) != old_priority:
            logger.info(f"Changing priority from {old_priority} to {new_priority}")
            self.reorder_mods_by_priority(row, int(old_priority) if old_priority.isdigit() else row + 1, new_priority)
    
    def reorder_mods_by_priority(self, row, old_priority, new_priority):
        """Reorder mods based on new priority"""
        # Get all row data
        row_data = []
        for r in range(self.rowCount()):
            row_items = []
            for c in range(self.columnCount()):
                item = self.item(r, c)
                row_items.append(item.text() if item else "")
            row_data.append(row_items)
        
        # Remove the moved row
        moved_row = row_data.pop(row)
        
        # Insert at new position (priority - 1 because priority is 1-indexed)
        insert_position = new_priority - 1
        if insert_position < 0:
            insert_position = 0
        elif insert_position > len(row_data):
            insert_position = len(row_data)
        
        row_data.insert(insert_position, moved_row)
        
        # Update all priorities
        for i, data in enumerate(row_data):
            data[1] = str(i + 1)  # Priority column
        
        # Refresh the table
        self.setRowCount(0)
        for data in row_data:
            row_idx = self.rowCount()
            self.insertRow(row_idx)
            for col, text in enumerate(data):
                item = qt.QTableWidgetItem(text)
                if col in [1, 2]:  # Center align for Priority, Conflicts
                    item.setTextAlignment(Qt.AlignCenter)
                self.setItem(row_idx, col, item)
        
        logger.info(f"Reordered: moved to priority {new_priority}")
    
    def on_row_reordered(self, from_rows, to_rows):
        """Handle row reorder event from drag-and-drop"""
        # check which mods are selected
        x = self.selectedItems()
        # get row indices of selected items
        row_start = min((*from_rows, *to_rows))
        row_end = max((*from_rows, *to_rows)) + 1
        self._update_mod_priorities(row_start, row_end)
        logger.info(f"Mod moved from position {from_rows} to position {to_rows}")
        
    def _update_mod_priorities(self, row_start:int=0, row_end:Optional[int]=None):
        """Update mod priorities after drag-and-drop reorder"""
        if row_end is None:
            row_end = self.rowCount()
        for row in range(row_start, row_end):
            priority_item = self.get_item(row, "Priority")
            if priority_item:
                priority_item.setText(str(row))
            self._update_mod_manager_by_row(row)
        self.mod_manager.mod_list.sort()
        
    def _update_mod_manager_by_row(self, row: int):
        """Update ModManager's enabled mod and load_order for a specific row
        Remember to call mod_manager.mod_list.sort() after updating all rows.
        """
        name_item = self.get_item(row, "Mod Name")
        if name_item:
            mod = self.mod_manager.mod_list.get(name_item.text())
            if mod:
                mod.enabled = name_item.checkState() == Qt.Checked
                mod.load_order = row
                
    def _update_mod_manager(self):
        """Update ModManager's enabled mod and load_order based on current table state"""
        for row in range(self.rowCount()):
            self._update_mod_manager_by_row(row)
        self.mod_manager.mod_list.sort()
        
    def _get_load_order(self):
        """Get current load order of mods based on table"""
        load_order = []
        for row in range(self.rowCount()):
            name_item = self.get_item(row, "Mod Name")
            if name_item and name_item.checkState() == Qt.Checked:
                load_order.append(name_item.text())
        return load_order