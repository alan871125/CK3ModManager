from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class ErrorSource:
    file: Path|None = None
    object: str|None = None
    key: str|None = None
    value: str|None = None
    line: int|None = field(default_factory = int)
    object2: str|None = None
    key2: str|None = None
    value2: str|None = None

    @classmethod
    def from_dict(cls, data:Dict[str,Any]):
        return cls(
            file=data.get('file'),
            object=data.get('obj'),
            key=data.get('key'),
            value=data.get('value'),
            line=int(data['line']) if 'line' in data and data['line'].isdigit() else None,
            object2=data.get('obj2'),
            key2=data.get('key2'),
            value2=data.get('value2'),
        )
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
            self.object2,
            self.key2,
            self.value2,
        ))
    def __repr__(self) -> str:
        return ('ErrorSource('+
                ', '.join(f"{k}={v!r}" for k,v in self.__dict__.items() if v)+')')


@dataclass
class ScriptErrorSource(ErrorSource):
    trigger: str|None = None
    @classmethod
    def from_dict(cls, data:Dict[str,Any]):
        x = super().from_dict(data)
        x.trigger = data.get('trigger')
        return x
    def __hash__(self):
        return super().__hash__() ^ hash(self.trigger)
    def __repr__(self) -> str:
        return ('ScriptErrorSource('+
                ', '.join(f"{k}={v!r}" for k,v in self.__dict__.items() if v)+')')