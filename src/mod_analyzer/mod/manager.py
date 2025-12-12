
import os
import json
from typing import Optional, Iterable
from pathlib import Path
from concurrent.futures import as_completed
import time
import logging
pkg = (__package__ or __name__).split('.')[0]
logger = logging.getLogger(pkg)

from utils.cocurrent import run_multithread, run_multiprocess
from ..encoding import detect_encoding
from . import paradox_parser 
from . import Mod, DefinitionNode, DefinitionDirectoryNode, DefinitionFileNode, ModList, SourceList, SourceEntry
from .mod_loader import get_mod_info, get_enabled_mod_descriptors, get_all_mod_descriptors, get_all_mod_descriptor_paths, get_playset_mod_descriptors, get_enabled_mod_dirs, load_mod_descriptor
from .conflict import non_conflict_keywords

class ModManager:
    """Checks for conflicts in mod definitions across multiple mods.    

    Example:       
    ```
        manager = ModManager()
        manager.build_mod_list()   # loads all mods from default mod directory
        manager.build_file_tree(   # See ModManager.build_file_tree for details
            file_range="all",      # options: "all", "enabled", "disabled".
            check_conflicts=True,  # If True, checks for definition conflicts.
            process_max_workers=16 # process_max_workers: (if set) uses multiprocessing
        )
        print(manager.conflict_issues)
        manager.dump_conflicts_to_json("conflict_issues.json")
    ```
    """
    # Directories: Works only for default directories installed with steam, modify if needed
    GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game"
    MODS_DIR = os.path.expandvars(r"%USERPROFILE%\Documents\Paradox Interactive\Crusader Kings III\mod")
    DOCS_DIR = os.path.expandvars(r"%USERPROFILE%\Documents\Paradox Interactive\Crusader Kings III")
    WORKSHOP_DIR = r"C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310"
    root_dir: Path
    mod_list: ModList[str]
    _max_def_depth: int = 0
    def __init__(self):
        self.mod_list = ModList()
        self.reset()
        
    def reset(self):
        self.definitions: dict[str, list[DefinitionNode]] = {}
        self.define_table = DefinitionDirectoryNode(r"%root%", "./")
        self.fileOutputBuffer = {}
        self.conflict_issues: dict[tuple[str,str], SourceList] = {}
        self.conflict_identifiers = []
        self.conflict_mods: set[str] = set()
        self.conflict_check_range: Optional[str] = None # "all", "enabled", "disabled", None
    @property
    def load_order(self) -> list[str]:
        """Returns the current load order of mods as a list of mod IDs."""
        return [mod.dup_name for mod in self.mod_list.enabled]
    def set_load_order(self, load_order: list[str]) -> None:
        """Sets the load order of mods based on the provided list of mod IDs."""
        for i, mod_id in enumerate(load_order):
            mod = self.mod_list.get(mod_id)
            if mod:
                mod.load_order = i
            else:
                logger.warning("Mod: \"%s\" not found in mod list.", mod_id)
        self.mod_list.sort()
    
    @staticmethod
    def _extract_file_definitions(file_entry:SourceEntry) -> tuple[SourceEntry, Optional[DefinitionNode], Optional[str]]:
        """Parses a single file entry. Helps with multiprocessing."""
        # For Developers: Keep this function at staticmethod level (or module level) to be picklable by ProcessPoolExecutor!!!
        try:
            encoding = detect_encoding(file_entry.file)
            with file_entry.file.open('r', encoding=encoding) as f:
                source = f.read()
            tree = paradox_parser.parser.parse(source.encode(encoding or 'utf-8'))
            definitions: DefinitionNode = paradox_parser.extract_node_definitions(
                tree.root_node, 
                # use "<def>" as a virtual space under the rel dir of the file, for tracking from root
                DefinitionNode(file_entry.file.name, str(file_entry.rel_path.parent), source=file_entry),
                max_depth=ModManager._max_def_depth
            )
        except Exception as e:
            logger.exception(f"Error reading %s: %s", file_entry.file, str(e))
            return (file_entry, None, str(e))
        return (file_entry, definitions, None)
    
    def save_profile(self, profile_path: str|Path):
        """Save the current mod list as a profile to file."""
        if profile_path == "<Default>": # save to dlc_load.json
            profile_path = self.DOCS_DIR/Path("dlc_load.json")
        profile_path = Path(profile_path)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_data = {"enabled_mods":[], "disabled_dlcs":[], "load_order":[]}
        for mod in self.mod_list.values():
            rel_path = mod.file.relative_to(self.DOCS_DIR).as_posix()
            if mod.enabled:
                profile_data["enabled_mods"].append(rel_path)
            profile_data["load_order"].append((rel_path, mod.enabled))
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=4)

    def load_profile(self, profile_path: str|Path, enabled_only: bool = False):
        """Load a mod profile from file."""
        mod_infos = []
        if profile_path == "<Default>": # load from dlc_load.json
            if not enabled_only:
                mod_infos = get_all_mod_descriptors()
            profile_path = self.DOCS_DIR/Path("dlc_load.json")
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
                mod = load_mod_descriptor(Path(self.DOCS_DIR)/rel_path)
                mod.enabled = enabled
                mod_infos.append(mod)
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
            rel_path = mod.path.relative_to(self.MODS_DIR).as_posix()
            lines.append(f"{prefix}{rel_path}")
        with open(Path(self.MODS_DIR)/"load_order.txt", "w", encoding="utf-8") as f:
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
                mod = load_mod_descriptor(Path(self.MODS_DIR)/rel_path)
                if mod:
                    mod.enabled = True if prefix == "+" else False
                    mod_infos.append(mod)
        self.mod_list = ModList(mod_infos)
     
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
            path = Path(self.DOCS_DIR)/"dlc_load.json"
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
        
    def _get_mod_file_entries(self, mod_info:Mod) -> dict[str, list[SourceEntry]]:
        """Gets the file entries for a given mod."""
        mod_dir:Path = mod_info.path
        file_entries: dict[str,list[SourceEntry]] = {"txt": [], "other": []}
        for dirpath, dirnames, files in os.walk(mod_dir):
            dirpath = Path(dirpath)
            relpath = dirpath.relative_to(mod_dir)            
            depth = len(relpath.parts)
            if depth in (0,):
                continue
            elif depth == 2:
                # Skip .git # Skip src, who's including this anyways
                if os.path.split(dirpath)[1] in ['.git','src']:
                    continue
            for file in files:
                # Create SourceEntry for tracking
                file_entry = SourceEntry(dirpath/file)
                file_entry.link_mod(mod_info)                 
                if file.lower().endswith(".txt"):
                    file_entries["txt"].append(file_entry)
                if file.lower().endswith((".yml", ".gui", ".csv", ".dds")):
                # These files are not parsed for definitions, but added to file tree
                # TODO: gui files can be parsed for definitions later
                    file_entries["other"].append(file_entry)
        return file_entries
    
    def _extract_definitions(self, file_entries:Iterable[SourceEntry]) -> None:
        '''
        Uses Paradox Tree Sitter Parser to extract definitions.
        '''
        for file_entry in file_entries:
            _, definitions, e = self._extract_file_definitions(file_entry)
            if definitions is None:
                logger.error("Error parsing %s: %s", file_entry.file, str(e))
                continue
            has_conflict = self.add_definition(file_entry, definitions)
        for obj in self.conflict_identifiers:
            self.conflict_issues[(obj.rel_dir.as_posix(),obj.name)] = obj.sources
                    
    def add_definition(self, file_entry:SourceEntry, definitions:DefinitionNode) -> bool:
        _ = self.define_table.setdefault_by_dir(file_entry.rel_path, definitions)
        def_node: DefinitionNode = self.define_table.setdefault_by_dir(
            file_entry.rel_path.parent/'<def>', 
            DefinitionFileNode('<def>', file_entry.rel_path.parent)
        )
        has_conflict = False
        if def_node == definitions: # no matching path found, safe to add without conflict
            return False
        for key, value in definitions.items():
            has_conflict = False
            _key_node = def_node.get(key)
            if key in non_conflict_keywords:
                continue            
            # Ensure the new value has the source set correctly
            value.set_source(file_entry)
            def_node[key] = value # always overwrite for now # TODO: handle defs that won't confilct with same names.
            self.definitions.setdefault(key, []).append(value)
            if _key_node:
                def_node[key].sources.update(_key_node.sources) # merge sources 
                has_conflict = def_node[key].has_conflict() or has_conflict
            if has_conflict and self.conflict_check_range:
                self.conflict_identifiers.append(def_node[key])
        return has_conflict
            
    def _extract_definitions_multiprocess(self, file_entries:Iterable[SourceEntry], max_workers:Optional[int]= None):
        """Extracts definitions using multiprocessing for better performance."""
        futures = run_multiprocess(ModManager._extract_file_definitions, file_entries, max_workers=max_workers or os.cpu_count() or 4)
        for fut in as_completed(futures):
            file_entry, definitions, err = fut.result()
            if err:
                logger.error("Error parsing %s: %s", file_entry.file, str(err))
                continue            
            # based on the acquired definitions, add to define_table
            has_conflict = self.add_definition(file_entry, definitions)
        for obj in self.conflict_identifiers:
            self.conflict_issues[(obj.rel_dir.as_posix(),obj.name)] = obj.sources
            # for mod_id in obj.sources.keys():
            #     self.conflict_issues2.setdefault(mod_id, []).append((obj.rel_dir.as_posix(), obj.name))
            # self.conflict_mods.update(obj.sources.keys())
    
    def should_check_conflicts(self, source: SourceEntry) -> bool:
        """Determines if conflicts should be checked for a given source entry."""
        if (self.conflict_check_range == "all" or
            self.conflict_check_range == "enabled" and source.enabled or 
            self.conflict_check_range == "disabled" and not source.enabled
        ):
            return True
        return False
    
    def _build_file_tree(self, mod_list:ModList[str], process_max_workers:Optional[int]= None):
        """Builds the file tree representation of the mod structure.
        
        Args:
            mod_list (ModList): List of mods to include in the file tree.
        """
        file_entries: dict[str, list[SourceEntry]] = {"txt": [], "other": []}
        t0=time.perf_counter()    
        if process_max_workers is not None and process_max_workers > 1:
            mod_entries = run_multithread(self._get_mod_file_entries, mod_list.values(), max_workers=process_max_workers)
            for mod_entry in mod_entries:
                file_entries["txt"].extend(mod_entry["txt"])
                file_entries["other"].extend(mod_entry["other"])
        else:
            for mod_info in mod_list.values():            
                mod_file_entries = self._get_mod_file_entries(mod_info)
                file_entries["txt"].extend(mod_file_entries["txt"])
                file_entries["other"].extend(mod_file_entries["other"])
        
        logger.debug("File entries collected in %.2f seconds", (t1:=time.perf_counter()) - t0)
        for file_entry in file_entries["other"]:
            self.define_table.add_file(file_entry)
        t2 = time.perf_counter()
        logger.debug("Other files added in %.2f seconds", (t2:=time.perf_counter())-t1)
        if process_max_workers is not None and process_max_workers > 1:
            # This runs multithreaded/multiprocessed, Do NOT put it in the for loop
            self._extract_definitions_multiprocess(file_entries["txt"], max_workers=process_max_workers)
        else:
            self._extract_definitions(file_entries["txt"])
        logger.debug("Definitions extracted in %.2f seconds", time.perf_counter()-t2)
        
    def get_rel_path(self, abs_path: str|Path) -> Optional[Path]:
        """Gets the relative path of a file with respect to the mod directories."""
        abs_path = Path(abs_path)
        if abs_path.is_relative_to(self.MODS_DIR):
            rel_path = abs_path.relative_to(self.MODS_DIR)
        elif abs_path.is_relative_to(self.WORKSHOP_DIR):
            rel_path = abs_path.relative_to(self.WORKSHOP_DIR)
        else:    
            return None
        return rel_path.relative_to(rel_path.parts[0])
    
    def dump_conflicts_to_json(self, output_path: str|Path):
        """Dumps the conflict issues to a JSON file for further analysis."""
        output_path = Path(output_path)
        results = {}
        for (rel_dir,identifier),mod_list in self.conflict_issues.items():
            # mod_list.sort()
            mod_list_ = {}
            for k,m in mod_list.items():
                m = m.as_dict()
                m["file"] = Path(m["file"]).as_posix() 
                mod_list_[k] = m
            results[f"{rel_dir}::{identifier}"] = mod_list_
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        logger.info("Conflict issues dumped to %s", output_path)

    
    