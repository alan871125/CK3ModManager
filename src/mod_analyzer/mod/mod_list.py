from pathlib import Path
from typing import Any, Optional,Sequence, TypeVar, Generic
from dataclasses import dataclass, field
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
        
    @property
    def load_order(self) -> list[str]:
        """Returns the current load order of mod names."""
        return list(self.keys())
    def __setitem__(self, key: str, value: Mod):
        """Sets a mod in the list by name."""
        assert isinstance(value, Mod)
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
    
@dataclass(order=True) # allows comparison based on fields
class SourceEntry:
    """Represents a source entry for an identifier definition.
    
    Attributes:
        file (Path): Path to the source file
        priority (int): Priority of the source
        enabled (Optional[bool]): Whether the source mod is enabled
        load_order (int): Load order of the source mod
        mod_id (Optional[str]): Mod identifier
        mod (Optional[Mod]): Reference to the Mod instance    
    """
    # order by priority ascending if needed; or keep separate sort key
    # primary sort fields (dataclass compares fields in definition order)
    file: Path = field(repr=True, compare=False)
    mod: Optional[Mod] = field(init=False, repr=False, compare=True)
    name: Optional[str] = ""
    # # sort_index is computed from `enabled`: enabled -> 0, disabled -> 1
    # _sort_index: int = field(init=False, repr=False, compare=True)
    # # don't include `enabled` directly in comparisons (we use sort_index)
    # _enabled: Optional[bool] = field(default=True, compare=False)
    # _load_order: int = -1
    @property
    def enabled(self) -> Optional[bool]:
        # check hasattr for thread safety
        if hasattr(self, 'mod') and self.mod is not None:
            return self.mod.enabled
    @property
    def load_order(self) -> int:
        # check hasattr for thread safety
        if hasattr(self, 'mod') and self.mod is not None:
            return self.mod.load_order
        return -1
    def __post_init__(self):
        # enabled True should sort before disabled, so enabled -> 0, disabled -> 1
        self._sort_index = 0 if bool(self.enabled) else 1
        self.file = Path(self.file) # ensure Path object

    def link_mod(self, mod: Mod):
        # update state from a Mod instance and refresh sort_index
        self.mod = mod
        self.name = mod.name
        self._sort_index = 0 if bool(self.enabled) else 1
    @property
    def rel_path(self) -> Path:
        """Returns the relative path of the source file within its mod."""
        assert self.mod is not None, "SourceEntry must be linked to a Mod before getting relative path"
        return self.file.relative_to(self.mod.path)
    def as_dict(self) -> dict[str, Any]:
        return {
            "file": str(self.file) if self.file else None,
            "enabled": self.enabled,
            "load_order": self.load_order,
            "mod_id": self.name,
        }
        
class SourceList(IndexedOrderedDict, Generic[TypeVar('KeyType')]):
    def sort(self, *, key=None, reverse=False):
        if key is None:
            key = lambda k: self[k]
        super().sort(key=key, reverse=reverse)
    def __setitem__(self, key: str, value: SourceEntry):
        assert isinstance(value, SourceEntry)
        super().__setitem__(key, value)
    def update(self, __m: dict[str, SourceEntry], **kwargs) -> None:
        super().update(__m, **kwargs)
        self.sort()
    def get_mods(self) -> ModList:
        """Returns a list of linked Mod instances from the sources."""
        mods = ModList()
        source:SourceEntry
        for source in self.values():
            if source.mod is not None:
                mods.add_duplicate(source.mod)
        return mods
    def get_enabled(self) -> "SourceList":
        """Returns a SourceList of only enabled sources."""
        enabled_sources = SourceList()
        for key, source in self.items():
            if source.enabled:
                enabled_sources[key] = source
        return enabled_sources

@dataclass(init=False)
class DefinitionNode(dict):
    """A dictionary like Object that stores definition information for an identifier, including its source mods."""
    
    def __init__(self, name: str, rel_dir: str|Path, source:Optional[SourceEntry] = None, type: str = "directory"):
        super().__init__()
        self.name:str = name
        self.rel_dir: Path = Path(rel_dir)
        self.sources: SourceList = SourceList()
        self.type:str = type
        self.parent: Optional["DefinitionNode"] = None
        if source:
            self.set_source(source)
    def __bool__(self):
        return bool(self.name and self.rel_dir)
    
    def __setitem__(self, key: str, value: Any) -> None:
        if isinstance(value, (DefinitionNode)):
            value.parent = self
        else:
            raise TypeError("Value must be a DefinitionNode instance")
        super().__setitem__(key, value)
    @property
    def source(self) -> Optional[SourceEntry]:
        return self.sources.values()[0] if self.sources else None
    
    def setdefault(self, key: str, default: Any = None) -> Any:
        # this is required to properly call __setitem__ on new entries
        if key not in self:
            self[key] = default
        return self[key]
        
    def set_source(self, source: SourceEntry):
        assert isinstance(source, SourceEntry)
        name = source.name or source.mod.name if source.mod else None
        assert name is not None, "SourceEntry must have a name or linked Mod with a name"
        self.sources[name] = source
        self.sources.sort()
            
    def has_conflict(self) -> bool:
        enabled_count = 0
        for src in self.sources.values():
            if src.enabled:
                enabled_count += 1
            if enabled_count > 1:
                return True
        return False
        
    def update(self, __m: object = None, **kwargs) -> None:
        """
        Compatible override of dict.update that also accepts a SourceEntry as the
        first (positional) argument to update source-related state.

        - If __m is a SourceEntry, update the IdentifierDefinition's source and
          sources collection, then apply any kwargs to the dict itself.
        - Otherwise delegate to dict.update(__m, **kwargs).
        """
        if isinstance(__m, SourceEntry):
            source = __m
            assert isinstance(source, SourceEntry)
            self.set_source(source)
            if kwargs:
                super().update(**kwargs)
        else:
            super().update(__m or {}, **kwargs) #type: ignore
        
    def get_by_dir(self, dirpath: str | Path, default=None) -> Optional["DefinitionNode"]:
        parts = Path(dirpath).parts
        current_level = self
        for part in parts:
            current_level = current_level.get(part)
            if current_level is None:
                return default
        return current_level
    
    def add_file(self, source: SourceEntry):
        assert isinstance(source, SourceEntry)
        file_entry = source 
        file_name: str = file_entry.file.name
        assert (mod:=file_entry.mod) is not None, "SourceEntry must be linked to a Mod before adding file"
        reldir = file_entry.file.relative_to(mod.path).parent
        file_descriptor = self
        for part in reldir.parts: # this builds the directory structure
            file_descriptor = file_descriptor.setdefault(part, DefinitionDirectoryNode(part, reldir))
        file_descriptor = file_descriptor.setdefault(file_name, DefinitionFileNode(file_name, reldir/file_name))
        file_descriptor.set_source(file_entry) # Add the file entry to the descriptor
        
    def pretty_print(self, indent: int = 0):
        for key, value in self.items():
            print('    ' * indent + str(key) + ':', end=' ')
            if isinstance(value, DefinitionValueNode):
                print(str(value))
            elif isinstance(value, DefinitionNode):
                print()
                value.pretty_print(indent + 1)
            else:
                print(str(value))
                
    def __repr__(self):
        return self.__class__.__name__ + f"(name={self.name}, rel_dir={self.rel_dir}, source={self.source})"
    
class DefinitionDirectoryNode(DefinitionNode):
    def __init__(self, name:str, rel_dir:Path|str, source:Optional[SourceEntry] = None):
        super().__init__(name, rel_dir, source=source, type='directory')
        
    def setdefault_by_dir(self, dirpath: str | Path, default: Optional[DefinitionNode] = None) -> DefinitionNode:
        dirpath = Path(dirpath) 
        if default is None:
            default = DefinitionDirectoryNode(dirpath.name, dirpath)
        parts = dirpath.parts
        current_level = self
        for part in parts[:-1]:
            current_level = current_level.setdefault(part, DefinitionDirectoryNode(part, current_level.rel_dir/part))
        return current_level.setdefault(parts[-1], default)    
class DefinitionFileNode(DefinitionNode):
    def __init__(self, name:str, rel_dir:Path|str, source:Optional[SourceEntry] = None):
        super().__init__(name, rel_dir, source=source, type='file')
class DefinitionIdentifierNode(DefinitionNode):
    def __init__(self, name:str, rel_dir:Path|str, source:Optional[SourceEntry] = None):
        super().__init__(name, rel_dir, source=source, type='identifier')
class DefinitionValueNode(DefinitionNode):
    def __init__(self, name:str, rel_dir:Path|str, value: str|int|bool|None|list = None):
        super().__init__(name, rel_dir, type='value')
        self.value = value
    def __str__(self):
        return str(self.value)
    