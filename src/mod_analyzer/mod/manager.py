import os
import json
from re import M
import time
import logging
from typing import Optional
from pathlib import Path
from concurrent.futures import as_completed
from utils.cocurrent import run_multithread, run_multiprocess
from ..encoding import detect_encoding
from . paradox import paradox_parser, DefinitionNode
# from . import _mod_rust as _native
# paradox_parser = _native.paradox_parser
from . import Mod, ModList
from constants import CK3_DOCS_DIR, MODS_DIR, WORKSHOP_DIR, GAME_DIR
from . mod_loader import get_mod_info, get_enabled_mod_descriptors, get_all_mod_descriptors, get_all_mod_descriptor_paths, get_playset_mod_descriptors, get_enabled_mod_dirs, load_mod_descriptor

pkg = (__package__ or __name__).split('.')[0]
logger = logging.getLogger(pkg)

class ModManager():
    """Checks for conflicts in mod definitions across multiple mods.
    """
    # Directories: Works only for default directories installed with steam, modify if needed
    root_dir: Path
    mod_list: ModList[str]
    _max_def_depth: int = -1
    _conflicts_by_mod: Optional[dict[str, list[DefinitionNode]]] = None
    language: str = "simp_chinese" # default language for localization parsing
    def __init__(self):
        self.mod_list = ModList()
        self.reset()
        
    def reset(self):
        self.definitions: dict[str, list[DefinitionNode]] = {}
        self.fileOutputBuffer = {}
        # self._conflict_issues: dict[tuple[str,str], list[DefinitionNode]] = {} # this shouldn't be required anymore
        self.conflict_mods: set[str] = set()
        self.conflict_check_range: Optional[str] = None # "all", "enabled", "disabled", None
        self._def_extractor = paradox_parser.DefinitionExtractor(WORKSHOP_DIR, MODS_DIR, self.language)
    @property
    def def_table(self) -> DefinitionNode:
        """Returns the root definition node of the mod definition tree."""
        return self._def_extractor.tree.root
    @property
    def conflict_identifiers(self) -> list[DefinitionNode]:
        """Returns the list of identifiers that have conflicts."""
        return self._def_extractor.conflict_identifiers
    @property
    def conflicts_by_mod(self) -> dict[str, list[DefinitionNode]]:
        """Returns a dictionary of conflict issues by mod."""
        if self._conflicts_by_mod is None:
            self._conflicts_by_mod = self._def_extractor.get_conflicts_by_mod()
        return self._conflicts_by_mod
    
    def save_profile(self, profile_path: str|Path):
        """Save the current mod list as a profile to file."""
        if profile_path == "<Default>": # save to dlc_load.json
            profile_path = CK3_DOCS_DIR/Path("dlc_load.json")
        profile_path = Path(profile_path)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_data = {"enabled_mods":[], "disabled_dlcs":[], "load_order":[]}
        for mod in self.mod_list.values():
            rel_path = mod.file.relative_to(CK3_DOCS_DIR).as_posix()
            if mod.enabled:
                profile_data["enabled_mods"].append(rel_path)
            profile_data["load_order"].append((rel_path, mod.enabled))
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=4)

    def load_profile(self, profile_path: str|Path, profile_only: bool = False):
        """
        Load a mod profile from file.
        Arguments:
            profile_path (str|Path): Path to the profile file. Use "<Default>" to load from default dlc_load.json.
            profile_only (bool): If True, only load mods from the profile without scanning all mods.
        """
        mod_infos = []
        if not profile_only:
            mod_infos = get_all_mod_descriptors()
        if profile_path == "<Default>": # load from dlc_load.json
            profile_path = CK3_DOCS_DIR/Path("dlc_load.json")
        profile_path = Path(profile_path)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.mod_list = ModList(mod_infos)
        if not profile_path.exists():
            logger.error(f"Profile not found: {profile_path}")
            return
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
        mod_infos = []
        load_order = profile_data.get("load_order", [])
        if load_order:
            for rel_path, enabled in load_order:
                try:
                    mod = load_mod_descriptor(Path(CK3_DOCS_DIR)/rel_path)
                    mod.enabled = enabled
                    mod_infos.append(mod)
                except Exception as e:
                    logger.error(f"Failed loading mod descriptor {rel_path}: {e}")
        else:
            mod_infos = get_enabled_mod_descriptors(profile_path)            
        self.mod_list.update(ModList(mod_infos))
        
    def save_load_order(self):
        """
        save load order as load_order.txt
        format:
        ```
            +mod/enabled_descriptor1.mod
            -mod/disabled_descriptor1.mod
            -mod/disabled_descriptor2.mod
        ```
        """
        lines =[]
        for mod in self.mod_list.values():
            prefix = "+" if mod.enabled else "-"
            rel_path = mod.path.relative_to(MODS_DIR).as_posix()
            lines.append(f"{prefix}{rel_path}")
        with open(Path(MODS_DIR)/"load_order.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    def load_load_order(self, file_path: str|Path):
        """
        load load order from load_order.txt
        format:
        ```
            +mod/enabled_descriptor1.mod
            -mod/disabled_descriptor1.mod
            -mod/disabled_descriptor2.mod
        ```
        """
        mod_infos = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                prefix = line[0]
                rel_path = line[1:]
                mod = load_mod_descriptor(Path(MODS_DIR)/rel_path)
                if mod:
                    mod.enabled = True if prefix == "+" else False
                    mod_infos.append(mod)
        self.mod_list = ModList(mod_infos)
    # @property
    # def conflict_issues(self)-> dict[tuple[str,str], list[DefinitionNode]]:
    #     """Returns a dictionary of conflict issues."""
    #     if not self._conflict_issues:
    #         for obj in set(self.conflict_identifiers):
    #             self._conflict_issues[(obj.rel_dir.as_posix(), obj.name)] = obj.sources
    #     return self._conflict_issues
    @property
    def load_order(self) -> list[str]:
        """Returns the current load order of mods as a list of mod IDs."""
        return [mod.dup_name for mod in self.mod_list.enabled]
    def get_def_node_by_name(self, name: str, default = []) -> list[DefinitionNode]:
        """Gets the list of definition nodes by name.
        
        Args:
            name (str): The name of the definition node.
        
        Returns:
            Optional[list[DefinitionNode]]: List of definition nodes with the given name, or None if not found.
        """
        return self._def_extractor.get_node_by_name(name) or default
    def set_load_order(self, load_order: list[str]) -> None:
        """Sets the load order of mods based on the provided list of mod IDs."""
        for i, mod_id in enumerate(load_order):
            mod = self.mod_list.get(mod_id)
            if mod:
                mod.load_order = i
            else:
                logger.warning("Mod: \"%s\" not found in mod list.", mod_id)
        self.mod_list.sort()
        
    def get_rel_path(self, abs_path: str|Path, depth = 1) -> Optional[Path]:
        """Gets the relative path of a file with respect to the mod directories."""
        abs_path = Path(abs_path)
        if abs_path.is_relative_to(MODS_DIR):
            rel_path = abs_path.relative_to(MODS_DIR)
        elif abs_path.is_relative_to(WORKSHOP_DIR):
            rel_path = abs_path.relative_to(WORKSHOP_DIR)
        else:    
            return None
        return rel_path.relative_to('/'.join(rel_path.parts[:depth]))
    
    def get_file_mod_source(self, abs_path: str|Path) -> Optional[Mod]:
        """Get the mod that contains the given absolute file path."""
        abs_path = Path(abs_path)
        if abs_path.is_relative_to(MODS_DIR):
            rel_path = abs_path.relative_to(MODS_DIR)
            mod_dir = Path(MODS_DIR)/rel_path.parts[0]
        elif abs_path.is_relative_to(WORKSHOP_DIR):
            rel_path = abs_path.relative_to(WORKSHOP_DIR)
            mod_dir = Path(WORKSHOP_DIR)/rel_path.parts[0]
        else:    
            return None
        return self.mod_list.get_by_dir(mod_dir)
    
    def get_node_mod_sources(self, node: DefinitionNode, enabled_only: bool = False) -> Optional[ModList]:
        """Get the mod that contains the given definition node."""
        if node.mod_sources:
            mod_list = ModList()
            for mod_node in node.mod_sources:
                if mod:= self.mod_list.get(mod_node.name):
                    if enabled_only and not mod.enabled:
                        continue
                    mod_list[mod.name] = mod
            return mod_list
        return None
    
    def build_mod_list(self, path: Optional[str|Path] = None, enabled_only: bool = False, mode:str = "default") -> None:
        """Builds the mod list from the specified root directory containing .mod files.        
        Args:
            path (str|Path, optional): Default=`~Documents/Paradox Interactive/Crusader Kings III/mod`.
                choose between the following options:
                - mode = "default" -> Path to `dlc_load.json` file.
                - mode = "playset" -> Path to Paradox Mod Manager playset directory containing `*.json`.
                - mode = "folder"  -> Path to mod root directory containing `.mod` files (*Will Load All Mods).
                *** If this option is used, `enabled_only` will be ignored ***
              
            enabled_only (bool, optional): If True, only loads enabled mods from `dlc_load.json` in the game documents folder.\
                Default is False. Only used if `mode` is "default".
            mode (str, optional): Mode of loading mods. Options are:
                - "default": Load mods from `dlc_load.json`.
                - "playset": Load mods from a Paradox Mod Manager playset directory.
                - "folder" : Load all mods from a mod root directory.
        """
        # path = Path(path) if path else None
        mod_infos:list[Mod] = []
        if mode == "playset":
            assert path is not None, "Playset mode requires a valid playset directory path."
            mod_infos = get_playset_mod_descriptors(path)
        elif mode == "folder":
            mod_infos = get_all_mod_descriptors() # load all mods from mod folder
        elif mode == "default":
            path = Path(CK3_DOCS_DIR)/"dlc_load.json"
            # if enabled_only, load only enabled mods from dlc_load.json
            if not enabled_only: # default load all mods from mod folder, then update with enabled mods
                mod_infos = get_all_mod_descriptors()
        else:
            raise ValueError(f"Invalid mode: {mode}. Choose from 'default', 'playset', or 'folder'.")
        self.mod_list = ModList(mod_infos)
        if mode == "default": # update enabled status based on dlc_load.json
            self.mod_list.update(ModList(get_enabled_mod_descriptors(path)))
    
    def build_file_tree(self, file_range:Optional[str]= None, conflict_check_range: Optional[str]=None, process_max_workers:Optional[int]= None):
        """Builds a file tree representation of the mod structure.
        
        Args:
            file_range (str, optional): Range of files to include. Defaults to "all".
                Options:
                    - None      : Include all files
                    - "enabled" : Include only enabled files
                    - "disabled": Include only disabled files
            conflict_check_range (str, optional): Range of mods to check for conflicts. Defaults to None.
                Options:
                    - None      : No conflict checking
                    - "all"     : Check all mods
                    - "enabled" : Check only enabled mods
                    - "disabled": Check only disabled mods
        """
        self.conflict_check_range = conflict_check_range
        if file_range == "enabled":
            mod_list = ModList(self.mod_list.enabled)
        elif file_range == "disabled":
            mod_list = ModList(self.mod_list.disabled)
        else:
            mod_list = self.mod_list
        # self._build_file_tree(mod_list)
        t0 = time.perf_counter()
        self._build_file_tree(mod_list, process_max_workers)
        logger.info("Done building file tree in %.2f seconds", time.perf_counter()-t0)
        
    def _build_file_tree(self, mod_list:ModList[str], process_max_workers:Optional[int]= None):
        """Builds the file tree representation of the mod structure.
        Args:
            mod_list (ModList): List of mods to include in the file tree.
        """
        t0=time.perf_counter()
        self._def_extractor.enroll_mods(list(mod_list.values()))
        res: DefinitionNode = self._def_extractor.extract_definitions(max_depth = 0)
        t1 = time.perf_counter()
        logger.warning("Definitions extracted in %.2f seconds", t1-t0)