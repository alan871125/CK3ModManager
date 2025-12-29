"""CK3 Mod Descriptor data model.

This module contains the ModDescriptor class, which represents metadata
about a CK3 mod from its descriptor.mod file.
"""
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, asdict, field
from constants import CK3_DOCS_DIR

import logging
logger = logging.getLogger((__package__ or __name__).split('.')[0])

@dataclass(order=True) 
class Mod:
    """Represents a CK3 mod with metadata.
    See https://ck3.paradoxwikis.com/Mod_structure for details
    Arguments:
        load_order (int): The load order index of the mod.
        enabled (bool): Whether the mod is enabled.
        name (str): The name of the mod.
        version (str): The version of the mod.
        path (Path): The file system path to the mod.
        tags (List[str]): List of tags associated with the mod.
        supported_version (Optional[int]): Supported game version.
        remote_file_id (Optional[str]): Remote file ID for Steam Workshop mods.
        picture (Optional[Path]): Path to the mod picture.
        replace_path (Optional[Path]): Path that this mod replaces.
        replaces (List[str]): List of mod names that this mod replaces.
        dependencies (List[str]): List of mod dependencies.
    """
    # include _sort_index in dataclass comparison
    _sort_index: int = field(init=False, repr=False, compare=True)
    load_order: int = -1
    enabled: bool = field(default=False, repr=True, compare=False)
    # Standard mod descriptor fields
    name: str = ""
    version: str = ""
    path: Path = field(default_factory=Path, repr=False, compare=False)
    tags: List[str] = field(default_factory=list, repr=False, compare=False)
    supported_version: Optional[str] = field(default=None, repr=False, compare=False)
    remote_file_id: Optional[str] = field(default="", repr=False, compare=False)  # Required for Steam Workshop mods
    picture: Optional[Path] = field(default_factory=Path, repr=False, compare=False)
    replace_path: Optional[Path] = field(default_factory=Path, repr=False, compare=False)
    replaces: List[str] = field(default_factory=list, repr=False, compare=False)
    dependencies: List[str] = field(default_factory=list, repr=False, compare=False)
    file: Optional[Path] = field(default=None, repr=False, compare=False)  # Path to descriptor.mod file
    # If this is True, enabled mods sort before disabled mods
    _enabled_first: bool = field(default = False, init=True, repr=False, compare=False)
    _dup_id:int = field(default=0, init=False, repr=False, compare=False)
    def __post_init__(self):
        # Set initial sort index from enabled
        object.__setattr__(self, "_sort_index", 0 if bool(self.enabled and self._enabled_first) else 1)
        # object.__setattr__(self, "path", Path(self.path))  # ensure Path object
    def __setattr__(self, name, value):
        # Keep _sort_index in sync whenever `enabled` changes
        if name == "enabled" and self._enabled_first:
            object.__setattr__(self, "_sort_index", 0 if bool(value) else 1)

        if name in {"path", "picture", "replace_path", "file"} and value is not None:
            value = Path(value)  # ensure Path object
        super().__setattr__(name, value)
    @property
    def dup_name(self) -> str:
        """Get the mod name with duplicate suffix if applicable."""
        if self._dup_id > 0:
            return f"{self.name}#{self._dup_id}"
        return self.name
    def as_dict(self):
        """Convert to dictionary representation."""
        return asdict(self)
    
    def load_from_descriptor(self, path: str|Path):
        """Load mod info from a descriptor file.
        
        Note: This method requires importing get_mod_info, which should
        be done locally to avoid circular imports.
        """
        # Import here to avoid circular dependency
        from .mod_loader import get_mod_info
        path = Path(path)
        _data = get_mod_info(path)
        for k, v in _data.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.path = Path(self.path) # ensure Path object
        self.file = path
        if self.path.parts and self.path.parts[0] == "mod": # adjust relative path
            self.path = Path(CK3_DOCS_DIR)/self.path
            self.save_to_descriptor(path) # save adjusted path back to descriptor
            
    def save_to_descriptor(self, path: str|Path):
        """Save mod info to a descriptor file.
        
        Note: This method only saves standard fields and may not
        preserve comments or formatting in the original file.
        """
        lines = []
        lines.append(f'name = "{self.name}"')
        lines.append(f'version = "{self.version}"')
        lines.append(f'path = "{self.path.as_posix()}"')
        if self.tags:
            tags_str = '", "'.join(self.tags)
            lines.append(f'tags={{"{tags_str}"}}')
        if self.supported_version is not None:
            lines.append(f'supported_version = "{self.supported_version}"')
        if self.remote_file_id:
            lines.append(f'remote_file_id = "{self.remote_file_id}"')
        if self.picture is not None and self.picture.parts:
            lines.append(f'picture = "{self.picture.as_posix()}"')
        if self.replace_path is not None and self.replace_path.parts:
            lines.append(f'replace_path = "{self.replace_path.as_posix()}"')
        if self.replaces:
            replaces_str = '", "'.join(self.replaces)
            lines.append(f'replaces = {{"{replaces_str}"}}')
        if self.dependencies:
            dependencies_str = '", "'.join(self.dependencies)
            lines.append(f'dependencies = {{"{dependencies_str}"}}')
        
        content = "\n".join(lines)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    def is_outdated(self, current_version: str) -> bool:
        """Check if the mod is outdated compared to the current game version.
        
        version format: "1.5.2", "1.6.*", "1.7.*.*" etc.
        """
        if self.supported_version is None:
            return False
        for part0, part1 in zip(self.supported_version.strip().split("."), current_version.split(" ")[0].split(".")):
            try:
                if part0 == "*" or part1 == "*":
                    return False
                num0 = int(part0)
                num1 = int(part1)
            except Exception as e:
                logger.error(f"Invalid version format: '{self.version}' or '{current_version}'")
                return False
            if num0 < num1:
                return True
            # elif num0 > num1:
            #     return False
        return False  # Versions are equal up to the length of the shorter one

    def __hash__(self):
        return hash((self.name, self.path))