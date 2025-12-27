"""The major logic for parsing and analyzing CK3 error logs."""
import json
import re
import logging
# import pandas as pd
from pathlib import Path
from typing import Optional, Any, Dict
from dataclasses import asdict, dataclass, field
from itertools import chain
from utils.time import time_execution
from ..encoding import detect_encoding, verify_utf8_bom
from ..mod import Mod, ModManager
from ..mod.paradox import DefinitionNode
from ..mod.mod_loader import load_mod_descriptor
from ..mod.mod_list import ModList
from . import patterns
from .source import ErrorSource, ScriptErrorSource

CK3_DOC_DIR = Path.home()/"Documents"/"Paradox Interactive"/"Crusader Kings III"
pkg = (__package__ or __name__).split('.')[0]
logger = logging.getLogger(pkg)

@dataclass
class ParsedError:
    _count: int = field(default=0, init=False, repr=False)
    type: str
    engine_source: str
    sources:list[ErrorSource]
    message:str = field(default_factory = str, repr=False)
    log_line: int = 0
    def __post_init__(self):
        self.id = ParsedError._count
        ParsedError._count += 1
    @property
    def source(self)->ErrorSource|None:
        """Assumes the source of the error is the last in the list, 
        which usually wins the conflict if multiple sources are present.
        """
        return self.sources[-1] if self.sources else None
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def dump_to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=4)
    def __hash__(self):
        return hash((
            self.type,
            self.engine_source,
            self.message,
            self.log_line,
        ))


class ErrorParser():
    def __init__(self):
        super().__init__()
        # self.classifier = ErrorClassifier()
        # self.parsed_errors: list[ParsedError] = []
        
    def _get_error_sources(self, error_type:str, msg:str) -> list[ErrorSource]:
        sources = []
        if regex := patterns.regex.get(error_type):
            error_pattern = re.compile(regex, re.DOTALL)
            for m in error_pattern.finditer(msg):
                details = m.groupdict()
                if error_type == 'SCRIPT_ERROR':
                    sources.append(ScriptErrorSource.from_dict(details))            
                else:
                    sources.append(ErrorSource.from_dict(details))
        return sources
    
    def parse_logs(self, logs: str, deduplicate: bool = True)-> dict[str, list[ParsedError]]:
        """
        Parse CK3 error logs and return a mapping from error source to list of messages.

        This supports multiline error messages where subsequent lines are indented
        and belong to the previous [E] entry.
        """
        # Match lines that start with a time, [E] and a source; capture the message
        # up until the next timestamp line (beginning of a log entry) or EOF.
        pattern = re.compile(
            r'^\[\d{2}:\d{2}:\d{2}\]\[E\]\[(?P<source>[^\]]+)\]: (?P<message>.*?)(?=^\[\d{2}:\d{2}:\d{2}\]\[|\Z)',
            re.MULTILINE | re.DOTALL,
        )
        already_parsed = set()
        errors:dict[str, list[ParsedError]] = {}
        current_pos = 0
        current_line = 1
        for match in pattern.finditer(logs):
            current_line += logs.count('\n', current_pos, match.start())
            current_pos = match.start()
            source = match.group('source')
            msg = match.group('message').rstrip('\n')
            candidate_errors = patterns.source_related_errors.get(source, [])
            source_scripts = []
            if deduplicate:
                unique_key = (source, msg)
                if unique_key in already_parsed:
                    continue
                already_parsed.add(unique_key)
            for error_type in candidate_errors:
                source_scripts.extend(self._get_error_sources(error_type, msg))
                if source_scripts:
                    break  # Only need the first matching error type
            if source in { # TODO: Deal with these properly
                # These error sources have not been properly parsed yet
                "pdx_data_factory.cpp:1032",
                "pdx_data_factory.cpp:1344",
                "pdx_data_factory.cpp:1351",
                "pdx_data_factory.cpp:1413",
                "pdx_data_factory.cpp:1417"}:
                continue # skip for now
            elif source_scripts == []:
                if "Script location: Unknown" in msg:
                    continue
                pass
            elif candidate_errors == []:
                error_type = "UNKNOWN_ERROR"
                logger.debug("Unknown error source (Please report to the developer): %s: %s", source, msg)
            else:
                errors.setdefault(error_type, []).append(ParsedError(type=error_type, message=msg, sources=source_scripts, engine_source = source, log_line=current_line))
        return errors
    
    def _find_log_file(self, logs_dir: Optional[str|Path]=None) -> Path | None:
        if logs_dir is None:
            candidates = [CK3_DOC_DIR/"logs/error.log"]
        else:
            logs_dir = Path(logs_dir)
            candidates = [logs_dir, logs_dir/"error.log", logs_dir/"logs/error.log"]
        for f in candidates:
            if f.exists():
                return f
        return None
    
    def _read_log_file(self, file_path: Path) -> str | None:
        try:
            enc = detect_encoding(file_path)
            with open(file_path, "r", encoding=enc, errors="replace") as f:
                return f.read()
        except Exception as e:
            logger.exception("Failed to read log file %s: %s", file_path, e)
            return None
    
    def load_error_logs(self, logs_dir:Optional[str|Path]=None)-> Optional[str]:
        log_file = self._find_log_file(logs_dir)
        if not log_file:
            return
        with open(log_file, "r", encoding="utf-8", errors='ignore') as f:
            return f.read()

class ErrorAnalyzer():      
    def __init__(self, mod_manager):
        super().__init__()
        self.mod_manager: ModManager = mod_manager
        self._needs_reload: bool = True
        # self._error_table: pd.DataFrame
        self._error_sources : dict[int, list[ErrorSource]] = {}
        self.errors: list[ParsedError] = []
        ParsedError._count = 0  # reset error ID counter
        self._error_by_mod: dict[str, dict[ParsedError, ErrorSource]] = {}
    @property
    def def_table(self)->DefinitionNode: # easy access to mod manager define table
        return self.mod_manager.def_table
    @property
    def mod_list(self)->ModList: # easy access to mod manager mod list
        return self.mod_manager.mod_list 
    # @property
    # def error_table(self)->pd.DataFrame:
    #     if self._needs_reload:
    #         self.load_error_logs()
    #     if not hasattr(self, "_error_table") or self._error_table is None:
    #         self._error_table = pd.DataFrame([e.to_dict() for e in self.errors])
    #     return self._error_table    
    @property
    def error_sources(self) -> dict[int, list[ErrorSource]]:
        if self._needs_reload:
            self.distribute_errors(self.errors)
            self._needs_reload = False
        return self._error_sources
    @property
    def error_by_mod(self) -> dict[str, dict[ParsedError, ErrorSource]]:
        if self._needs_reload:
            self.distribute_errors(self.errors)
            self._needs_reload = False
        return self._error_by_mod
    
    def load_error_logs(self, logs_dir:Optional[str|Path]=None)-> Optional[str]:
        error_parser = ErrorParser()
        logs = error_parser.load_error_logs(logs_dir)
        self.errors_by_type: dict[str, list[ParsedError]] = time_execution(error_parser.parse_logs,logs) if logs else {}
        self.errors: list[ParsedError] = sum(self.errors_by_type.values(), [])
        self._needs_reload = True
        return logs
        
    def distribute_errors(self, parsed_errors: list[ParsedError]) -> dict[int, tuple[bool, list[ErrorSource]]]:
        """Map error sources to mods in the mod manager."""
        results = {} # {mod_id: mod_info}
        for err in parsed_errors:
            self.locate_error_sources(err)
            if not err.source:
                continue
            ### DEBUGGING POINT ###    
            if len(err.source.mod_sources)>1 and err.type in {
                'DUPLICATE_LOC_KEY',
                "GUI_DUPLICATE_CHILD_WIDGET"
            }:
                pass # debug point
            elif len(err.source.mod_sources)==0:
                if err.type in {
                'FAILED_TO_READ_KEY_REFERENCE',
                'TRYING_TO_IMPORT_LOC_KEY_OUTSIDE_OF_LANGUAGE', # only loc key given, def_table only stores localization of selected language
                'MISSING_LOCALIZATION', # only loc key given, likely no localization definition.
                }:
                    continue
                pass # debug point
            for mod in err.source.mod_sources:
                if mod is None:
                    continue
                self._error_by_mod.setdefault(mod.name, {}).update({err:err.source})
            ### DEBUGGING POINT ###
            # sources: tuple[bool, list[ErrorSource]] = 
            # results[err.id] = sources
        self._error_sources = results
        return results       
        
    def get_error_source_mod_candidates(self, source: ErrorSource) -> list[DefinitionNode]:
        """Get the candidate mods that could be the source of the error."""
        identifiers: list[DefinitionNode] = []
            # source.file = rel_path # TODO: abs path Temporarily changed to relative path, keep both?
        if source.file and source.file.exists(): # absolute path given, change to relative path
            # TODO: This should be a temporary solution, the Mod item is already found, 
            # but we need to find the DefinitionNode for this function to return
            logging.warning("Absolute file path sourcing should be handled by get_file_mod_source")
            mod = self.mod_manager.get_file_mod_source(source.file)
            if mod and (rel_path := self.mod_manager.get_rel_path(source.file)):
                if file_node:= self.def_table.get_by_dir(rel_path):
                    return [n for n in file_node.mod_sources if n.name == mod.name]
            return []
            
        elif source.file is not None: # relative path given
            if (identifier:= self.def_table.get_by_dir(source.file)):
                identifiers.append(identifier)            
            if source.file2 and (identifier2:= self.def_table.get_by_dir(source.file2)):
                identifiers.append(identifier2)            
        else:
            if source.object is not None: # gets multiple identifiers if conflict exists
                identifiers.extend(self.mod_manager.get_def_node_by_name(source.object))
                if source.object2 is not None:
                    identifiers.extend(self.mod_manager.get_def_node_by_name(source.object2))
            elif source.key is not None: # Least precise way
                identifiers.extend(self.mod_manager.get_def_node_by_name(source.key))
                if source.key2 is not None:
                    identifiers.extend(self.mod_manager.get_def_node_by_name(source.key2))
            else:
                pass
            if len(identifiers) == 1:
                source.file = identifiers[0].rel_dir / identifiers[0].name
        candidates = list(set(chain.from_iterable(identifier.mod_sources for identifier in identifiers)))
        if len(candidates)>1:
            if source.line is not None:
                pass # debug point
        # candidates are file sources, actual mod_source can be located later
        return candidates
    
    def get_mod_from_mod_node(self, mod_node: DefinitionNode) -> Optional[Mod]:
        """Get the Mod instance from a mod definition node."""
        mod_name = mod_node.name
        mod = self.mod_manager.mod_list.get(mod_name)
        return mod
    
    def locate_encoding_error_source(self, err:ParsedError):
        assert err.type == "ENCODING_ERROR"
        assert err.source is not None
        file_def = self.def_table.get_by_dir(err.source.file) if err.source.file else None
        assert file_def is not None, "File definition not found for encoding error"
        if file_def.has_conflict():
            candidates = file_def.sources
            # go through candidates and check BOMs to find error source
            for candidate in candidates:
                if verify_utf8_bom(candidate.full_path):
                    err.source.mod_sources = []
                    return
            raise Exception("No BOM found in candidates for encoding error")
        elif file_def.source:
            for m in file_def.mod_sources:
                if (mod:=self.mod_manager.mod_list.get(m.name)) is None:
                    continue
                err.source.mod_sources.append(mod)
        
                
    def locate_version_error_source(self, err:ParsedError):
        assert err.type == "INVALID_SUPPORTED_VERSION"
        assert err.source is not None
        desc_file = err.source.file
        if not desc_file:
            return True, []
        mod_name: str = load_mod_descriptor(desc_file).name # Use only the mod name, the Mod Object is duplicate
        mod:Optional[Mod] = self.mod_manager.mod_list.get(mod_name)
        file_path = Path("%CK3_MODS_DIR%")/Path(desc_file).name
        err.source.file = file_path
        err.source.mod_sources = [mod] if mod else []
        
    def locate_error_sources(self, err:ParsedError):
        '''Locate the source mods for a given error.
        
        Returns:
            tuple[bool,list[DefinitionNode]]: confidence flag (bool) and list of candidate sources (FileNodes).
            
        '''        
        candidates: list[DefinitionNode] = [] # candidate FileNodes
        # ----- Special Cases -----
        if err.type == "ENCODING_ERROR":
            return self.locate_encoding_error_source(err)
        elif err.type == "INVALID_SUPPORTED_VERSION":
            return self.locate_version_error_source(err)
        elif len(err.sources)>1:
            if err.type != "SCRIPT_ERROR":
                pass
            for s in err.sources:
                candidates = self.get_error_source_mod_candidates(s)
                if len(candidates) == 1:
                    if res:=self.mod_manager.get_node_mod_sources(candidates[0]):
                        s.mod_sources = list(res.values())
                # candidates.extend(self.get_error_source_mod_candidates(s))
            return
        # ----- Problematic Cases -----
        elif not err.source:
            logger.error("No source information found for error: %s", err)
            # return False, []
            return 
        # ----- General Case -----
        if err.source.file and err.source.file.exists(): # absolute path given
            if mod:=self.mod_manager.get_file_mod_source(err.source.file):
                err.source.mod_sources = [mod]
            return
        else:
            candidates = self.get_error_source_mod_candidates(err.source)
        if err.type == 'DUPLICATE_LOC_KEY':
            pass # debug point
        if len(candidates) == 1:
            if mod:=self.mod_list.get(candidates[0].name):
                err.source.mod_sources = [mod]
        elif len(candidates) > 1:
            err.source.mod_sources = []
            for c in candidates:
                if mod:=self.mod_list.get(c.name):
                    err.source.mod_sources.append(mod)
            if err.type in {"DUPLICATE_LOC_KEY", "LOC_KEY_HASH_COLLISION"}:
                pass # TODO: handle duplicate loc key error properly
            # returning only the enabled mod for now
            elif len(err.source.mod_sources) == 0:
                logger.error("(Report if you see this ERROR) No enabled mod found among candidates for error,  %s", err)
            elif len(err.source.mod_sources) > 1:
                if err.source.line:
                    pass # debug point
                logger.error("(Report if you see this ERROR) Conflict checking not implemented yet: Could not uniquely identify source mod for error: %s", err)
            return
        else:# candidate not found    
            if err.type in {
                'FAILED_TO_READ_KEY_REFERENCE',
                'TRYING_TO_IMPORT_LOC_KEY_OUTSIDE_OF_LANGUAGE', # only loc key given, def_table only stores localization of selected language
                'MISSING_LOCALIZATION', # only loc key given, likely no localization definition.
            }:
                logger.warning("Not enough information to determine error source for: %s", err)
            elif "LOC" in err.type:
                logger.warning("Error sourcing for this error is not implemented yet: %s", err) #TODO: 'LOC_KEY_HASH_COLLISION': can be solved if two candidates are found
            elif err.source and err.source.file:
                if err.source.file.parts[0] == 'gui':
                    logger.warning("Error sourcing for GUI files not implemented yet: %s", err)
            else:
                logger.error("Error source not found for error: %s", err)
        return


    
    
                
        
                
