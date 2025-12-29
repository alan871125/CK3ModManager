from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
from ..mod.descriptor import Mod

@dataclass
class ErrorSource:
    file: Path|None = None
    object: str|None = None
    object_type:str|None = None
    key: str|None = None
    value: str|None = None
    line: int|None = field(default_factory = int)
    
    mod_sources: list[Mod] = field(default_factory=list, repr=False) # more than one source mod means unclear origin
    def is_solved(self) -> bool:
        return len(self.mod_sources) == 1 and self.file is not None 
    @classmethod
    def from_dict(cls, data:Dict[str,Any]) -> list['ErrorSource']:
        sources = []
        s1 = cls(
            file=data.get('file'),
            object=data.get('obj'),
            object_type=data.get('type'),
            key=data.get('key'),
            value=data.get('value'),
            line=int(data['line']) if 'line' in data and data['line'].isdigit() else None,
        )
        sources.append(s1)
        
        if any(k in data for k in ['file2', 'obj2', 'key2', 'value2']):
            s2 = cls(
                file=data.get('file2'),
                object=data.get('obj2'),
                key=data.get('key2'),
                value=data.get('value2'),
                line=int(data['line2']) if 'line2' in data and data['line2'].isdigit() else None,
            )
            sources.append(s2)
        return sources

    def __setattr__(self, name: str, value: Any) -> None:
        if name == 'file' and value is not None:
            value = Path(value)
        super().__setattr__(name, value)
    def __hash__(self):
        return hash((
            self.file,
            self.object,
            self.key,
            self.value,
            self.line,
        ))
    def __repr__(self) -> str:
        return ('ErrorSource('+
                ', '.join(f"{k}={v!r}" for k,v in self.__dict__.items() if v)+')')


@dataclass
class ScriptErrorSource(ErrorSource):
    trigger: str|None = None
    @classmethod
    def from_dict(cls, data:Dict[str,Any]):
        sources = super().from_dict(data)
        for s in sources:
            s.trigger = data.get('trigger')
        return sources
    def __hash__(self):
        return super().__hash__() ^ hash(self.trigger)
    def __repr__(self) -> str:
        return ('ScriptErrorSource('+
                ', '.join(f"{k}={v!r}" for k,v in self.__dict__.items() if v)+')')