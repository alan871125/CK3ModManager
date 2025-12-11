"""The major logic for parsing and analyzing CK3 error logs."""
import json
import re
import logging
# import pandas as pd
from pathlib import Path
from typing import Optional, Any, Dict
from dataclasses import asdict, dataclass, field

from utils.time import time_execution
from ..encoding import detect_encoding, verify_utf8_bom
from ..mod import Mod, ModManager, DefinitionNode
from ..mod.mod_loader import load_mod_descriptor
from ..mod.mod_list import SourceEntry, ModList, SourceList
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
        self._error_sources : dict[int, list[SourceEntry]] = {}
        self.errors: list[ParsedError] = []
    @property
    def define_table(self)->DefinitionNode: # easy access to mod manager define table
        return self.mod_manager.define_table
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
    def error_sources(self) -> dict[int, list[SourceEntry]]:
        if self._needs_reload:
            self.distribute_errors(self.errors)
            self._needs_reload = False
        return self._error_sources
    
    def load_error_logs(self, logs_dir:Optional[str|Path]=None)-> Optional[str]:
        error_parser = ErrorParser()
        logs = error_parser.load_error_logs(logs_dir)
        self.errors_by_type: dict[str, list[ParsedError]] = time_execution(error_parser.parse_logs,logs) if logs else {}
        self.errors: list[ParsedError] = sum(self.errors_by_type.values(), [])
        self._needs_reload = True
        return logs
        
    def distribute_errors(self, parsed_errors: list[ParsedError]) -> dict[int, str|Path]:
        """Map error sources to mods in the mod manager."""
        results = {} # {mod_id: mod_info}
        for err in parsed_errors:
            sources = self.locate_error_sources(err)
            results[err.id] = sources
        self._error_sources = results
        return results
    
    def get_error_source_mod_candidates(self, source: ErrorSource) -> SourceList:
        """Get the candidate mods that could be the source of the error."""
        candidates: SourceList = SourceList()
        if source.file and source.file.exists(): # absolute path+            
            source.file = self.mod_manager.get_rel_path(source.file)
        if source.file is None:
            if source.object is not None:
                identifiers = self.mod_manager.definitions.get(source.object, [])
            elif source.key is not None:
                identifiers = self.mod_manager.definitions.get(source.key, [])
            else:
                return candidates    
        else:
            identifier: Optional[DefinitionNode] = self.define_table.get_by_dir(source.file)
            identifiers = [identifier] if identifier is not None else []
        for identifier in identifiers:
            candidates.update(identifier.sources)
        return candidates
    
    def locate_error_sources(self, err:ParsedError) -> list[SourceEntry]:
        mod_id: str = ""
        candidates: SourceList = SourceList()
        if err.type == "ENCODING_ERROR":
            if err.source is None:
                return []
            # use err.source since encoding error should only have one related file
            file_def = self.define_table.get_by_dir(err.source.file) if err.source.file else None
            if file_def is not None:
                if file_def.has_conflict():
                    candidates = file_def.sources
                    # go through candidates and check BOMs to find error source
                    for candidate in candidates.values():
                        if verify_utf8_bom(candidate):
                            return [candidate]
                    raise Exception("No BOM found in candidates for encoding error")
                elif file_def.source:
                    return [file_def.source]
        elif err.type == "INVALID_SUPPORTED_VERSION":
            desc_file = err.sources[0].file if err.sources else None
            if not desc_file:
                return []
            mod_name: str = load_mod_descriptor(desc_file).name # Use only the mod name, the Mod Object is duplicate
            mod:Optional[Mod]= self.mod_manager.mod_list.get(mod_name)
            file_path = Path("%CK3_MODS_DIR%")/Path(desc_file).name
            # file_path = CK3_DOC_DIR/"mod"/Path(err.file).name
            source: SourceEntry = SourceEntry(file=file_path, mod_id=mod_name)
            source.link_mod(mod) if mod else None                    
            return [source]
        else:
            candidates = SourceList()
            for s in err.sources:
                candidates.update(self.get_error_source_mod_candidates(s))
        if len(candidates) == 1 or err.type == "DUPLICATE_LOC_KEY":
            return list(candidates.values())
        elif len(candidates) > 1:
            if err.type =='SCRIPT_ERROR':
                return list(candidates.values())
            for mod_id, source in candidates.items():
                logger.debug("Checking candidate mod: %s", mod_id)
                logger.error("Conflict checking not implemented yet, report if you see this ERROR: Could not uniquely identify source mod for error: %s", err)
        if "LOC" in err.type:
            logger.warning("Error sourcing for this error is not implemented yet: %s", err)
        elif err.source and err.source.file:
            if err.source.file.parts[0] == 'gui':
                logger.warning("Error sourcing for GUI files not implemented yet: %s", err)
        elif err.type in {
            'FAILED_TO_READ_KEY_REFERENCE',
        }:
            logger.warning("Not enough information to determine error source for: %s", err)
        else:
            logger.error("Error source not found for error: %s", err)
        # logger.warning("Could not uniquely identify source mod for error: %s", err)
        return []


    
    
                
        
                
