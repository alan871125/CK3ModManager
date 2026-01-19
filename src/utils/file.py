import os
import logging
from pathlib import Path
logger = logging.getLogger((__package__ or __name__).split('.')[0])

def open_file_at_line(file_path: Path, line=0 , editor=None) -> None:        
    """Open a file at a specific line number in the specified text editor"""
    import shutil, subprocess
    if editor is None:
        pass
    elif editor.lower() in ("notepadpp", "notepad++"):
        if exe:=next(filter(lambda p:Path(p).exists(),[
            shutil.which("notepad++") or
            r"C:\Program Files\Notepad++\notepad++.exe",
            r"C:\Program Files (x86)\Notepad++\notepad++.exe"
        ])):
            subprocess.Popen([exe, "-multiInst", f"-n{line}", f'{str(file_path)}'])
            logger.info(f"Opened {file_path} at line {line} in Notepad++")
            return
    elif editor.lower() in ("vscode", "code"):
        if exe:=shutil.which("code"):
            subprocess.Popen([exe, "-g", f'{str(file_path)}:{line}'])
            logger.info(f"Opened {file_path} at line {line} in VSCode")
            return
    logger.warning("Opening file without specific line number (editor not supported)")
    return os.startfile(file_path)