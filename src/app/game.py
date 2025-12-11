from dataclasses import dataclass, field
from pathlib import Path
import os
import json

class GameLauncher:
    def __init__(self, launcher_settings_path: Path|str):
        self.launcher_path = Path(launcher_settings_path)
        self.settings = LauncherSettings.load(launcher_settings_path)
    def launch_game(self, exe_args: str|None = None):
        exe_path = self.settings.absExePath
        exe_args = exe_args or self.settings.exeArgs
        os.startfile(f'"{exe_path}" {exe_args}')    

@dataclass
class LauncherSettings:
    """
    Represents the settings stored in the CK3 launcher-settings.json file.
    
    Uses camelCase to match JSON keys
    """
    formatVersion:int
    modsCompatibilityVersion:str
    gameId:str
    displayName:str
    version:str
    rawVersion:str
    distPlatform:str
    gameDataPath: Path
    dlcPath: Path
    ingameSettingsLayoutPath:str
    themeFile:str
    browserDlcUrl:str
    browserModUrl:str
    exePath:Path
    exeArgs:str
    alternativeExecutables:list
    _rootPath:Path = field(default = Path(), init=True, repr=False, compare=False)
    def __setattr__(self, name, value: str|Path):
        if name == "gameDataPath": # format like %USER_DOCUMENTS%/Paradox Interactive/Crusader Kings III
            docs_path = str(Path.home()/"Documents")
            value = Path(str(value).replace("%USER_DOCUMENTS%", docs_path))
        elif name in {"dlcPath", "exePath"} and value is not None:
            value = Path(value)  # ensure Path object
        object.__setattr__(self, name, value)
    @staticmethod
    def load(file_path:str|Path) -> 'LauncherSettings':
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        settings = LauncherSettings(**data)
        settings._rootPath = Path(file_path).parent
        return settings
    def __str__(self):
        string = "LauncherSettings(\n"
        for field_name, field_value in self.__dict__.items():
            string += f"  {field_name}: {field_value}\n"
        string += ")"
        return string
    @property
    def absDlcPath(self) -> Path:
        if self.dlcPath.is_absolute():
            return self.dlcPath
        else:
            return (self._rootPath/self.dlcPath).resolve()
    @property
    def absExePath(self) -> Path:
        if self.exePath.is_absolute():
            return self.exePath
        else:
            return (self._rootPath/self.exePath).resolve()
if __name__ == "__main__":
    settings = LauncherSettings.load(
        r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\launcher\launcher-settings.json"
    )
    print(settings)
