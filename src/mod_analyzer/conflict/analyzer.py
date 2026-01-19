import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from constants import CONFLICT_LOGS_PATH
from mod_analyzer.mod.manager import ModManager
from mod_analyzer.mod.descriptor import Mod
from mod_analyzer.mod.paradox import DefinitionNode, NodeType
from mod_analyzer.mod.paradox import IndexedOrderedDict

class BaseTreeNode(IndexedOrderedDict):
    parent: 'BaseTreeNode|None' = None
    name: str
    val: Any = None
    def __init__(self, name:str, value:Any, parent:'BaseTreeNode|None'=None):
        super().__init__()
        self.name = name
        self.val = value
        self.parent = parent
    def __setitem__(self, key:str, value:'BaseTreeNode') -> None:
        assert isinstance(value, BaseTreeNode), "Value must be a BaseTreeNode"
        value.parent = self
        super().__setitem__(key, value)
        
    def get_by_dir(self, dir_path:Path|str, default=None) -> 'BaseTreeNode|None':
        dir_path = Path(dir_path)
        parts = dir_path.parts
        current_node = self
        for part in parts:
            if (current_node := current_node.get(part)) is not None:
                continue
            return default
        return current_node
    
    def setdefault(self, key:str, default:Any=None) -> 'BaseTreeNode':
        if not isinstance(default, BaseTreeNode):
            default = self.__class__(key, default)
        if key not in self:
            self[key] = default
        return self[key]
    
    def setdefault_by_dir(self, dir_path:Path|str, default:Any = None) -> Any:
        dir_path = Path(dir_path)
        if not isinstance(default, BaseTreeNode):
            default = self.__class__(dir_path.as_posix(), default)
        parts = dir_path.parts
        current_node = self
        for part in parts[:-1]:
            current_node = current_node.setdefault(part, self.__class__(part, None))
        return current_node.setdefault(parts[-1], default)
    
class ConflictTreeNode(BaseTreeNode):
    _path:Path|None = None
    parent: 'ConflictTreeNode|None' = None
    def __repr__(self) -> str:
        return f"ConflictTreeNode(name={self.name!r}, #children={len(self)})"
    @property
    def type(self)->NodeType:
        if self.val is not None:
            return NodeType.Identifier
        return NodeType.Directory
    @property
    def path(self) -> Path:
        if self._path is None:
            if self.parent is None:
                self._path = Path(self.name)
            else:
                self._path = self.parent.path/self.name
        return self._path
@dataclass
class ConflictSource:
    mod: Mod
    file: Path
    object: str|None = field(default=None)
    line: int|None = field(default=None)
    _parsed_conflict: 'ParsedConflict|None' = field(default=None, repr=False) # link back to the parsed conflict
    def __hash__(self) -> int:
        return hash((
            self.mod.name,
            self.file,
            self.line,
        ))
    def __repr__(self) -> str:
        return (f"ConflictSource(mod={self.mod.name!r}, "
                f"file={self.file}, line={self.line})")

@dataclass
class ParsedConflict:
    engine_source: str
    object: str
    rel_dir: Path
    _file: Path
    _line: int
    sources: list[ConflictSource] = field(default_factory=list, init=False, repr=False)
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._file}::{self.object}, line={self._line})"
    def __str__(self) ->str:
        return (
            f"{self.__class__.__name__}"
            f"({self.rel_dir}::{self.object}, sources={{"
                f"\n  {',\n  '.join(str(s) for s in self.sources)}\n"
            "})"
        )
    def add_source(self, source:ConflictSource) -> None:
        self.sources.append(source)
        source._parsed_conflict = self
    def __hash__(self) -> int:
        return hash((
            self.object,
            self.rel_dir,
        ))
class ConflictLogParser:
    # example:
    # [18:43:12][W][gamedatabase.h:321]: Overriding entry 'is_available' for database 'common/scripted_triggers' in 'file: common/scripted_triggers/zzz_carnx_00_available_for_events_triggers.txt line: 1'
    pattern = re.compile(
        (r'^\[\d{2}:\d{2}:\d{2}\]\[W\]\[(?P<source>[^\]]+)\]: ' 
         r'Overriding entry \'(?P<obj>[^\']+)\' for database \'(?P<rel_dir>[^\']+)\' in \'file: (?P<file>[^\']+) line: (?P<line>\d+)\'$'),
        re.MULTILINE | re.DOTALL,
    )
    conflicts: list[ParsedConflict]
    conflicts_by_mod2: dict[str, set[ParsedConflict]] = {}
    conflicts_by_mod: dict[str, list[DefinitionNode]] = {}
    def parse_logs(self, logs:str|None=None)->list[ParsedConflict]:
        if logs is None:
            try:
                with open(CONFLICT_LOGS_PATH, 'r', encoding='utf-8') as f:
                    logs = f.read()
            except Exception as e:
                raise RuntimeError(f"Failed to read conflict logs from {CONFLICT_LOGS_PATH}: {e}") from e
        conflicts = []
        for match in self.pattern.finditer(logs):
            conflict = ParsedConflict(
                engine_source=match.group('source'),
                object=match.group('obj'),
                rel_dir=Path(match.group('rel_dir')),
                _file=Path(match.group('file')),
                _line=int(match.group('line')),
            )
            conflicts.append(conflict)
        self.conflicts = conflicts
        return conflicts
    
    def locate_conflict_sources(self, manager:'ModManager') -> None:
        assert hasattr(self, 'conflicts'), "No conflicts parsed yet. Call parse_logs() first."
        for conflict in self.conflicts:
            sources = set()
            def_node = manager.def_table.get_by_dir(conflict.rel_dir/"<def>"/conflict.object)
            if def_node and def_node.sources:
                for file_node in def_node.sources:
                    for mod_node in file_node.mod_sources:
                        if not (mod:=manager.mod_list.get(mod_node.name)):
                            continue
                        source = ConflictSource(
                            mod, Path(file_node.name), conflict.object, file_node.line,
                        )
                        sources.add(source)
                        self.conflicts_by_mod2.setdefault(mod.name, set()).add(conflict)
                        self.conflicts_by_mod.setdefault(mod.name, []).append(def_node)
            conflict.sources = list(sources)
            
    def locate_conflict_sources2(self, manager:'ModManager') -> ConflictTreeNode:
        """Build a Conflict Tree from the parsed conflicts."""
        assert hasattr(self, 'conflicts'), "No conflicts parsed yet. Call parse_logs() first."
        root: ConflictTreeNode = ConflictTreeNode("<root>", None)
        for conflict in self.conflicts:
            def_node = manager.def_table.get_by_dir(conflict.rel_dir/"<def>"/conflict.object)
            if def_node and def_node.sources:
                for file_node in def_node.sources:
                    for mod_node in file_node.mod_sources:
                        if not (mod:=manager.mod_list.get(mod_node.name)):
                            continue
                        if type(file_node) is not DefinitionNode:
                            continue
                        source = ConflictSource(
                            mod, Path(file_node.name), conflict.object, file_node.line,
                        )
                        conflict.add_source(source)
                        tree_path = Path(mod.name)/conflict.rel_dir/source.file/conflict.object
                        root.setdefault_by_dir(tree_path, ConflictTreeNode(conflict.object, source))
                        
        for mod_name, node in root.items():
            node._path = manager.mod_list[mod_name].path       
        return root
            