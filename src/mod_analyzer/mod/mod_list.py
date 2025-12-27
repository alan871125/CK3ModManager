from pathlib import Path
from typing import Any, Optional, Sequence, TypeVar, Generic
from indexed import IndexedOrderedDict
import logging

from .descriptor import Mod

pkg = (__package__ or __name__).split('.')[0]
logger = logging.getLogger(pkg)

class ModList(IndexedOrderedDict, Generic[TypeVar('KeyType')]):    
    """Holds a list of mods and their information.
    
    Example:
        ```python
        # Initialize from list of Mod instances
        # default load order is index order
        mod_list = ModList(mods:list[Mod]) 
        
        # Initialize from dict of Mod instances + load order
        # load order from list of mod names
        mod_list = ModList(mods:dict[str, Mod], load_order:list[str]) 
        ```
    """
    def __init__(self, mod_list: Optional[Sequence[Mod]|dict[Any, Mod]] = None, load_order: Optional[list[str]] = None):
        super().__init__()
        self.duplicates:dict[str, int] = {}
        self.path_name_map:dict[Path, str] = {}
        no_order_provided = load_order is None
        if mod_list is None:
            return
        # check if mod_list is iterable
        assert no_order_provided or len(load_order) == len(mod_list), "Load order length must match mod list length"
        if isinstance(mod_list, dict):
            self.update(mod_list)
            if load_order is None:
                logger.warning("ModList initialized with dict but no load_order provided, using dict keys order as load order")
            # self._load_order = load_order or list(self.keys()) # default load order is dict key order
            else:
                self.sort(key=lambda k: load_order.index(k) if k in load_order else len(load_order))
        else:
            # self._load_order = load_order or []            
            for i, mod in enumerate(mod_list or []):
                if mod.name is None:
                    mod.name = "unknown_"+str(len(self)+1)
                    logger.warning("Mod with no name found: %s", mod)
                _mod = self.setdefault(mod.name, mod)
                if _mod is not mod:
                    logger.warning("Mod with duplicate name found: %s", mod)
                    self.add_duplicate(mod)
                else:
                    self[mod.name] = mod
                if no_order_provided:
                    mod.load_order = i
                    # self._load_order.append(mod.name)
                    
    def add_duplicate(self, mod: Mod):
        """Renames duplicate mod names by appending a suffix: "#<number>"."""
        base_name = mod.name or "unknown"
        if self.get(base_name) is None:
            self[base_name] = mod
            return
        duplicates = self.duplicates.get(base_name, 0)+1
        self.duplicates[base_name] = duplicates
        mod._dup_id = duplicates
        self[mod.dup_name] = mod
    
    def get_by_dir(self, dir: str|Path) -> Optional[Mod]:
        """Get a mod by its path."""
        path = Path(dir)
        mod_name = self.path_name_map.get(path)
        if mod_name:
            return self.get(mod_name)
        return None
    def get(self, key: str) -> Optional[Mod]:
        """Get a mod by its name."""
        return super().get(key)
        
    @property
    def load_order(self) -> list[str]:
        """Returns the current load order of mod names."""
        return list(self.keys())
    def __setitem__(self, key: str, value: Mod):
        """Sets a mod in the list by name."""
        assert isinstance(value, Mod)
        if value.path is not None:
            self.path_name_map[value.path] = key
        super().__setitem__(key, value)
    def update(self, mod_list: dict[str, Mod], **kwargs) -> None:
        """Updates the mod list with new mods."""
        super().update(mod_list, **kwargs)
        self.sort()
                
    def sort(self, *, key=None, reverse=False):
        """Sorts the mod list by name in place.
        By default, sorts by:
        1. enabled>disabled
        2. load order ascending
        3. name ascending
        """
        if key is None:
            key = lambda k:(self[k])
        super().sort(key=key, reverse=reverse)   
        
    @property
    def enabled(self) -> list[Mod]:
        """Returns a list of enabled mods in load order."""
        return [mod for mod in self.values() if mod.enabled]
    @property
    def keys_enabled(self) -> list[str]:
        """Returns a list of enabled mod names in load order."""
        return [mod.name for mod in self.values() if mod.enabled]
    @property
    def disabled(self) -> list[Mod]:
        """Returns a list of disabled mods in load order."""
        return [mod for mod in self.values() if not mod.enabled]
    @property
    def keys_disabled(self) -> list[str]:
        """Returns a list of disabled mod names in load order."""
        return [mod.name for mod in self.values() if not mod.enabled]
    
    def hide_disabled_mod_descriptor_files(self):
        """Renames the descriptor files of disabled mods to hide them from the game."""
        for mod in self.disabled:
            if mod.file and mod.file.exists():
                hidden_file = mod.file.with_suffix(mod.file.suffix + "_disabled")
                mod.file.rename(hidden_file)
                mod.file = hidden_file
    def unhide_disabled_mod_descriptor_files(self):
        """Restores the descriptor files of disabled mods."""
        for mod in self.disabled:
            if mod.file and mod.file.exists() and mod.file.suffix.endswith("_disabled"):
                restored_file = mod.file.with_suffix(mod.file.suffix.replace("_disabled", ""))
                mod.file.rename(restored_file)
                mod.file = restored_file