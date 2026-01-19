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
from constants import CK3_DOCS_DIR

pkg = (__package__ or __name__).split('.')[0]
logger = logging.getLogger(pkg)

ERRORS_NOT_ENOUGH_INFO = {
    'FAILED_TO_READ_KEY_REFERENCE', # key & line given
    'TRYING_TO_IMPORT_LOC_KEY_OUTSIDE_OF_LANGUAGE', # only loc key given, def_table only stores localization of selected language
    # only loc key given, likely no localization definition.
    'MISSING_LOCALIZATION', 'MISSING_LOC_KEY_KEY_ONLY', 
    "MISSING_LOC", # not sure for this one.
    # Only Key:
    'OBJ_SET_NOT_USED', 'OBJ_NOT_SET_USED',
    'LOC_STR_DATA_ERROR' # This could be possibly identified if knowing what causes the error
    
}
VERBOSE_MESSAGES = {
    'FOUND': "Source mod successfully identified.",
    'NOT_FOUND': "Could not identify source mod.",
    'NOT_ENOUGH_INFO': "Not enough information to identify source mod.",
    'LOC_UNIMPLEMENTED': "Error sourcing for localization errors not implemented yet.",
    'GUI_UNIMPLEMENTED': "Error sourcing for GUI files not implemented yet.",
    'BUILDING_NOT_FOUND': "Could not identify source mod for building error.",
    
    'CONFLICT_WONT_FIX': "Conflict checking not implemented: Could not uniquely identify source mod for error, but won't be fixed due to complexity.",
    'CONFLICT_NO_LINE': "Conflict checking not implemented: Could not uniquely identify source mod for error.",
    'NO_ENABLED_CANDIDATES': "No enabled mod found among candidates for error.",
    'CONFLICT_WITH_LINE': "Conflict checking not implemented: source mod for error could possibly be identified with definition line but wasn't!",
}
ANALYZE_SUMMARY_NEED_REPORT = {
    'NO_ENABLED_CANDIDATES',
    'CONFLICT_WITH_LINE',
    'CONFLICT_NO_LINE',
}
class ModSourcedPath(Path):
    """A Path with an associated source mod."""
    mod_source: Optional[Mod]
    def __new__(cls, *args, mod_source: Optional[Mod]=None, **kwargs):
        obj = super().__new__(cls, *args, **kwargs)
        obj.mod_source = mod_source
        return obj
    def set_mod_source(self, mod: Mod):
        self.mod_source = mod
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
                    sources.extend(ScriptErrorSource.from_dict(details))            
                else:
                    sources.extend(ErrorSource.from_dict(details))
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
            candidates = [CK3_DOCS_DIR/"logs/error.log"]
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
        self.reset()
        
    def reset(self):
        self.errors = []
        self._needs_reload = True
        self._error_by_mod = {}        
        ParsedError._count = 0  # reset error ID counter
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
        
    def distribute_errors(self, parsed_errors: list[ParsedError], verbose = 1):
        """Map error sources to mods in the mod manager."""
        results = {} # {mod_id: mod_info}
        done = set()
        for err in parsed_errors:
            if err in done:
                continue
            self.locate_error_sources(err)
            if not err.sources:
                continue
            ### DEBUGGING POINT ###    
            if len(err.sources)>1 and err.type!="SCRIPT_ERROR":
            # err.type in {
            #     'DUPLICATE_LOC_KEY',
            #     "GUI_DUPLICATE_CHILD_WIDGET"
            #     "LOC_KEY_HASH_COLLISION",
            # }:
                pass # debug point
            ### DEBUGGING POINT ###
            for source in err.sources:
                if not source.mod_sources:
                    if err.type in ERRORS_NOT_ENOUGH_INFO:
                        continue # DEBUG POINT
                    continue
                for mod in source.mod_sources:
                    self._error_by_mod.setdefault(mod.name, {}).update({err:source})
                results.setdefault(source.summary, []).append((err.id, source))
                if verbose >=2 and (msg:= VERBOSE_MESSAGES.get(source.summary)):
                    if source.summary == 'FOUND':
                        logger.debug(f'Error {err.id} source mod identified: {mod.name}. ')
                    elif source.summary in ANALYZE_SUMMARY_NEED_REPORT:
                        logger.error("Error %s not solved with the reason: %s (Report if you see this ERROR)", err.id, msg)
                    else:
                        logger.error("Error %s not solved with the reason: %s", err.id, msg)
            done.add(err)
        if verbose >= 1:
            for summary, res in results.items():
                if (
                    summary in ANALYZE_SUMMARY_NEED_REPORT and 
                    (msg := VERBOSE_MESSAGES.get(summary))
                ):
                    # Counter([self.errors[r[0]].type for r in res])
                    logger.error(
                        "%d errors not solved with the reason: %s (Report if you see this ERROR)", len(res), msg)
                else:
                    logger.info(f'{summary}: {len(res)} errors. ')
        return results       
        
    def get_error_source_identifier_candidates(self, source: ErrorSource) -> list[DefinitionNode]:
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
        else:
            if source.object is not None: # gets multiple identifiers if conflict exists
                identifiers.extend(self.mod_manager.get_def_node_by_name(source.object))
            elif source.key is not None: # Least precise way
                identifiers.extend(self.mod_manager.get_def_node_by_name(source.key))
            else:
                pass
            if len(identifiers) == 1:
                source.file = identifiers[0].rel_dir / identifiers[0].name
        
        return identifiers
    
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
                if not verify_utf8_bom(candidate.full_path): # found BOM, should not cause encoding error
                    if mod := self.get_mod_from_mod_node(candidate):
                        err.source.add_mod_source(mod)
                        break
        elif file_def.source:
            for m in file_def.mod_sources:
                if (mod:=self.mod_manager.mod_list.get(m.name)) is None:
                    continue
                err.source.add_mod_source(mod)
        if err.source.mod_sources:
            err.source.summary = 'FOUND'
        err.source.summary = 'NOT_FOUND'
        # return False # No BOM found in candidates for encoding error
    
    def locate_building_error_source(self, err:ParsedError):
        assert err.type in {"DUPLICATE_BUILDING_TYPE", "INVALID_BUILDING_TYPE"}
        assert err.source is not None
        identifiers = self.get_error_source_identifier_candidates(err.source)
        for identifier in identifiers:
            mod_candidates = identifier.mod_sources
            if len(mod_candidates) >1:
                logger.debug("Multiple mod candidates found for identifier %s: %s", identifier.name, mod_candidates)
            if mod_candidates:
                mod_node = mod_candidates[-1]
                if not (mod := self.mod_manager.mod_list.get(mod_node.name)):
                    continue
            else:
                continue
            if identifier.parent and (file_path:=identifier.parent.full_path).exists():
                file_content = file_path.read_text(encoding="utf-8-sig", errors="ignore")
                if (err.source.object      and err.source.object in file_content and 
                    err.source.object_type and err.source.object_type in file_content):
                    err.source.file = identifier.parent.full_path
                    err.source.mod_sources = [mod]
                    err.source.summary = 'FOUND'
                    return
        err.source.summary = 'BUILDING_NOT_FOUND'
        # logger.error("Could not uniquely identify source mod for building error: %s", err)
        
    def locate_version_error_source(self, err:ParsedError):
        assert err.type == "INVALID_SUPPORTED_VERSION"
        assert err.source is not None
        desc_file = err.source.file
        if not desc_file:
            err.source.summary = 'NOT_FOUND'
            return
        mod_name: str = load_mod_descriptor(desc_file).name # Use only the mod name, the Mod Object is duplicate
        mod:Optional[Mod] = self.mod_manager.mod_list.get(mod_name)
        file_path = Path("%CK3_MODS_DIR%")/Path(desc_file).name
        err.source.file = file_path
        err.source.mod_sources = [mod] if mod else []
        err.source.summary = 'FOUND' if mod else 'NOT_FOUND'
        
    def locate_error_sources(self, err:ParsedError):
        '''
        Locate the source mods for a given error.            
        '''
        candidates: list[DefinitionNode] = [] # candidate FileNodes
        # ----- Special Cases -----
        if err.type == "ENCODING_ERROR":
            return self.locate_encoding_error_source(err)
        elif err.type == "INVALID_SUPPORTED_VERSION":
            return self.locate_version_error_source(err)
        elif err.type in {"DUPLICATE_BUILDING_TYPE", "INVALID_BUILDING_TYPE"}:
            return self.locate_building_error_source(err)
        # ----- Problematic Cases -----
        elif err.source is None:
            logger.error("No source information found for error: %s", err)
            return 
        # ----- General Case -----
        for source in err.sources:
            if source.file and source.file.exists(): # absolute path given
                if mod:=self.mod_manager.get_file_mod_source(source.file):
                    source.add_mod_source(mod)
                continue
            
            identifiers = self.get_error_source_identifier_candidates(source)
            candidates = list(set(chain.from_iterable(identifier.mod_sources for identifier in identifiers)))
            
            if len(candidates) == 1:
                if mod:=self.mod_list.get(candidates[0].name):
                    source.add_mod_source(mod)
                    if source.file is None:
                        source.file = candidates[0].rel_dir / candidates[0].name
            elif len(candidates) > 1:
                for c in candidates:
                    if mod:=self.mod_list.get(c.name):
                        source.add_mod_source(mod)
                if len(source.mod_sources) == 0:
                    source.summary = 'NO_ENABLED_CANDIDATES'
                elif len(source.mod_sources) > 1:                    
                    if source.line:
                        source.summary = 'CONFLICT_WITH_LINE'
                    else:
                        if err.type == 'DUPLICATE_LOC_KEY':
                            continue # this is expected to have multiple sources
                        elif err.type in [ 
                                # too hard to identify source mod for these errors
                                "TRYING_TO_IMPORT_LOC_KEY_OUTSIDE_OF_LANGUAGE", # will have to check localization files from all languages, which is too expensive
                                "OBJ_SET_NOT_USED", # example: flags that are commonly defined in multiple mods
                                "OBJ_NOT_SET_USED", # object not defined, probably can't be located
                            ]:
                                source.summary = 'CONFLICT_WONT_FIX'
                        else:
                            source.summary = 'CONFLICT_NO_LINE'
            else:# candidate not found    
                if err.type in ERRORS_NOT_ENOUGH_INFO:
                    source.summary = 'NOT_ENOUGH_INFO'
                elif "LOC" in err.type:
                    source.summary = 'LOC_UNIMPLEMENTED'
                elif source.file and source.file.parts[0] == 'gui':
                    source.summary = 'GUI_UNIMPLEMENTED'
                else: # Error source not found
                    pass
        return


    
    
                
        
                
