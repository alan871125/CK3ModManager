# CK3 Mod Manager (Conflict and Log Analyzer) - WIP

This is a tool designed to manage mods for Crusader Kings 3.

## Features:
- **Mod List Managerment**
- **Error Log Analysis**
  - Error filtering
  - Error source tracing
- **Mod Conflict Check**
  - Parses mod identifier definitions with multiprocessing
  - Finds conflicts between identifier definitions
- **Basic Error Fixing**
  - (Currently only supports encoding errors (utf8-bom))


## Instructions
- start the app by running:
```cmd
python scr\app\main.py
```
- pack to .exe using pyinstaller or auto-py-to-exe
```cmd
pyinstaller --onefile --noconsole --add-data="src\app\icons\app_icon.png;." --icon=src\app\icons\app_icon.png --name "CK3 Mod Manager" src\app\main.py
```

## Credits
This project is inspired by [BondarchukST's CK3 Log Analyzer](https://github.com/BondarchukST/CK3-Log-Analyzer).