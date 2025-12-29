import os
import re
import json
from pathlib import Path
from typing import List, Optional

from .descriptor import Mod
from constants import CK3_DOCS_DIR, WORKSHOP_DIR, MODS_DIR
import logging
pkg = (__package__ or __name__).split('.')[0]
logger = logging.getLogger(pkg)


def locate_mod_from_file(file_path: str | Path, mod_root: Path)-> Optional[Mod]:
    abs_file_path = Path(file_path).resolve()
    try:
        rel_path = abs_file_path.relative_to(mod_root.resolve())
        mod_dir = mod_root/rel_path.parts[0]
    except ValueError:
        logger.exception(f"File {file_path} is not under mod root {mod_root}")
        return None
    try:
        # try loading descriptor.mod in the mod dir
        mod_descriptor = load_mod_descriptor(Path(mod_dir)/"descriptor.mod")
        return mod_descriptor
    except FileNotFoundError as e:
        try: # last resort, try finding any *.mod file in the 'mod' folder
            get_mod_info_from_mod_dir(mod_dir)
        except FileNotFoundError:
            print("Mod descriptor not found:", e)
            return None
            
def parse_paradox_mod_descriptor(text:str)-> dict[str, str|List[str]]:
    result = dict(re.findall(r'([a-zA-Z0-9_]+)\s*=\s*"?([^"]*)"?', text))
    # capture tags list content inside braces and extract quoted strings
    m = re.search(r'tags\s*=\s*\{([^}]*)\}', text, re.S)
    result['tags'] = []
    if m:
        result['tags'] = re.findall(r'"([^"]+)"', m.group(1))
    return result

def update_workshop_mod_descriptor_files():
    """Search for descriptor.mod files in the Steam Workshop folder and add them to the mods folder."""
    if not WORKSHOP_DIR.exists():
        logger.warning(f"Workshop directory does not exist: {WORKSHOP_DIR}")
        return
    for f in WORKSHOP_DIR.glob("**/descriptor.mod"):
        try:
            mod_desc:Mod = load_mod_descriptor(f)
            mod_desc.path = f.parent
            mod_desc.save_to_descriptor(MODS_DIR/f"ugc_{mod_desc.remote_file_id}.mod")            
        except:
            logger.error(f"Failed loading workshop mod descriptor: {f}")
            continue

def load_mod_descriptor(path: Path | str) -> Mod:
    """Load a Mod descriptor from the given file path."""
    candidate_paths = [path, MODS_DIR/path, CK3_DOCS_DIR/path]
    for p in candidate_paths:
        if Path(p).exists():
            path = p
            break
    descriptor = Mod()
    descriptor.load_from_descriptor(path) 
    return descriptor

def get_mod_info_from_mod_dir(mod_dir: Path) -> dict[str, str|List[str]]:
    """Gets mod info from descriptor.mod file in the given mod directory.\
        If file not found, try looking for any *.mod file in the 'mod' folder.
    """
    desc_path = mod_dir/"descriptor.mod"
    if not desc_path.exists():
        # try finding any *.mod file in the 'mod' folder
        if any((mod_f:=f) for f in os.listdir(mod_dir) if is_mod_descriptor_file(mod_dir/f)):
            desc_path = mod_dir/mod_f
    return get_mod_info(desc_path)

def get_mod_info(descriptor_path: Path|str) -> dict[str, str|List[str]]:
    descriptor_path = Path(descriptor_path)
    if not descriptor_path.exists():
        raise FileNotFoundError(f"Mod descriptor file not found: {descriptor_path}")
    with open(descriptor_path, "r", encoding="utf-8") as f:
        text = f.read()
    
    info = parse_paradox_mod_descriptor(text)
    # ensure replaces and dependencies are lists
    info.setdefault("replaces", [])
    info.setdefault("dependencies", [])
    return info

def is_mod_descriptor_file(file_path: Path|str) -> bool:
    file_path = Path(file_path)
    if file_path.suffix.lower() == ".mod":
    # if file_path.suffix.lower() == ".mod" or file_path.suffix.lower() == ".mod_disabled":
        return True
    return False

def get_all_mod_descriptor_paths(paradox_dir: Optional[Path]= None) -> List[Path]:
    paradox_dir = paradox_dir or CK3_DOCS_DIR
    mod_dir = paradox_dir/"mod"
    paths = []
    for f in os.listdir(mod_dir):
        if is_mod_descriptor_file(f):
            paths.append(mod_dir/f)
    return paths

def get_all_mod_descriptors(mod_dir: Optional[Path]= None) -> List[Mod]:
    mod_dir = mod_dir or CK3_DOCS_DIR/"mod"
    descriptors = []
    for f in os.listdir(mod_dir):
        try:
            if is_mod_descriptor_file(f):
                desc = load_mod_descriptor(f"{mod_dir}/{f}")
                descriptors.append(desc)
        except Exception as e:
            logger.error(f"Failed loading mod descriptor {f}: {e}")
    return descriptors

# ------- default dlc_load.json based functions -------
def get_enabled_mod_dirs(mod_list_path: Optional[Path]= None, paradox_dir: Optional[Path]= None) -> List[Path]:
    paradox_dir = paradox_dir or CK3_DOCS_DIR
    mod_list_path = mod_list_path or paradox_dir/"dlc_load.json"
    with open(mod_list_path, "r", encoding="utf-8") as f:
        dlc_data = json.load(f)
    desc_rel_paths = dlc_data.get("enabled_mods", [])
    mod_dirs = [Path(paradox_dir/p) for p in desc_rel_paths]
    return mod_dirs
def get_enabled_mod_descriptors(mod_list_path: Optional[str|Path]= None, paradox_dir: Optional[Path]= None) -> List[Mod]:
    paradox_dir = paradox_dir or CK3_DOCS_DIR
    mod_list_path = mod_list_path or paradox_dir/"dlc_load.json"
    with open(mod_list_path, "r", encoding="utf-8") as f:
        dlc_data = json.load(f)
    desc_rel_paths = dlc_data.get("enabled_mods", []) # example: ["mod/ugc_0000000000.mod", "mod/awesome_mod.mod"] ]
    mod_descriptors = []
    for i, p in enumerate(desc_rel_paths):
        try:
            desc = load_mod_descriptor(paradox_dir/p)
            desc.enabled = True
            desc.load_order = i
            mod_descriptors.append(desc)
        except Exception as e:
            logger.error(f"Failed loading mod descriptor {p}: {e}")
    return mod_descriptors
# ------- Paradox Mod Manager playset based functions -------
def get_playset_mod_dirs(playset_dir: Path) -> List[Path]:
    mod_dirs = []
    for f in os.listdir(playset_dir):
        if f.lower().endswith(".json"):
            with open(playset_dir/f, "r", encoding="utf-8") as pf:
                playset_data = json.load(pf)
            desc_rel_paths = playset_data.get("mods", [])
            for p in desc_rel_paths:
                mod_dirs.append(Path(p).parent)
    return mod_dirs
def get_playset_mod_descriptors(playset_dir: Path|str) -> List[Mod]:
    playset_dir = Path(playset_dir)
    mod_descriptors = []
    for f in os.listdir(playset_dir):
        try:
            if f.lower().endswith(".json"):
                with open(playset_dir/f, "r", encoding="utf-8") as pf:
                    playset_data = json.load(pf)
                desc_rel_paths = playset_data.get("mods", [])
                for i, p in enumerate(desc_rel_paths):
                    desc = load_mod_descriptor(Path(p))
                    desc.enabled = True
                    desc.load_order = i
                    mod_descriptors.append(desc)
        except Exception as e:
            logger.error(f"Failed loading mod descriptor {f}: {e}")
    return mod_descriptors
def file_search_recursive(root_dir, depth=0, max_depth=1):
    file_list = []
    if depth > max_depth:
        return []
    for f in os.scandir(root_dir):
        if f.is_file() and f.name.lower().endswith((".txt", ".yml", ".gui", ".csv")):
            file_list.append(f.path)
        elif f.is_dir():
            file_list.extend(file_search_recursive(f.path, depth + 1, max_depth))
    return file_list


