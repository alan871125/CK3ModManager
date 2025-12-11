"""
Encoding fix module for CK3 files.
Converts files to UTF-8-BOM encoding as required by Crusader Kings 3.
"""

import shutil
from pathlib import Path
from typing import Union, Sequence
from chardet.universaldetector import UniversalDetector

def _detect_encoding_and_bom(file):
    detector = UniversalDetector()
    detector.reset()
    has_bom = False
    with open(file, 'rb') as f:
        for row in f:
            has_bom = has_bom or row.startswith(b'\xef\xbb\xbf')
            detector.feed(row)
            if detector.done: break
    detector.close()
    return detector.result, has_bom

def detect_encoding(file):
    result, has_bom = _detect_encoding_and_bom(file)
    encoding = result.get('encoding', 'utf-8')        
    if encoding == 'utf-8' and has_bom:
        return 'utf-8-sig'        
    return encoding

def convert_to_utf8_bom(file_path: Union[str, Path], backup: bool = True) -> bool:
    """
    Convert a file to UTF-8-BOM encoding.
    
    Args:
        file_path: Path to the file to convert
        backup: If True, create a backup file before conversion
        
    Returns:
        True if successful, False otherwise
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        print(f"File not found: {file_path}")
        return False
    
    try:
        # check if file is already UTF-8-BOM
        result, has_bom = _detect_encoding_and_bom(file_path)
        if result.get('encoding') == "utf-8" and has_bom:
            print(f"File is already UTF-8-BOM: {file_path}")
            return True

        # Create backup if requested
        if backup:
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)
            print(f"Backup created: {backup_path}")
        
        # Read the file content
        with open(file_path, "rb") as f:
            raw_data = f.read()
        
        # Check if already has UTF-8 BOM
        if raw_data.startswith(b"\xef\xbb\xbf"):
            print(f"File already has UTF-8 BOM: {file_path}")
            return True
        
        # Detect current encoding
        encoding = detect_encoding(file_path)
        if encoding == "unknown":
            print(f"Unknown encoding for file: {file_path}, defaulting to utf-8")
            encoding = "utf-8"
        # Decode content
        try:
            content = raw_data.decode(encoding or "utf-8", errors="replace")
        except Exception:
            content = raw_data.decode("utf-8", errors="replace")
        
        # Write with UTF-8 BOM
        with open(file_path, "wb") as f:
            # Write BOM
            f.write(b"\xef\xbb\xbf")
            # Write content in UTF-8
            f.write(content.encode("utf-8"))
        
        print(f"✓ Converted to UTF-8-BOM: {file_path}")
        return True
        
    except Exception as e:
        print(f"✗ Error converting {file_path}: {e}")
        return False


def fix_encoding_error(file_path: Union[str, Path], backup: bool = True) -> bool:
    """
    Fix encoding error for a single file by converting it to UTF-8-BOM.
    
    This is the main function that will be called by the tool.
    
    Args:
        file_path: Path to the file to fix
        backup: If True, create a backup before conversion
        
    Returns:
        True if successful, False otherwise
    """
    return convert_to_utf8_bom(file_path, backup)


def fix_encoding_errors_batch(file_paths: Sequence[Union[str, Path]], backup: bool = True) -> tuple[list[Path], list[Path]]:
    """
    Fix encoding errors for multiple files.
    
    Args:
        file_paths: List of file paths to fix
        backup: If True, create backups before conversion
        
    Returns:
        Tuple of (successful_files, failed_files)
    """
    successful = []
    failed = []
    
    for file_path in file_paths:
        if fix_encoding_error(file_path, backup):
            successful.append(Path(file_path))
        else:
            failed.append(Path(file_path))
    
    return successful, failed


def fix_directory_encoding(directory: Union[str, Path], 
                           pattern: str = "*.yml",
                           recursive: bool = True,
                           backup: bool = True) -> tuple[list[Path], list[Path]]:
    """
    Fix encoding errors for all files matching a pattern in a directory.
    
    Args:
        directory: Path to the directory
        pattern: File pattern to match (e.g., "*.yml", "*.txt")
        recursive: If True, search subdirectories
        backup: If True, create backups before conversion
        
    Returns:
        Tuple of (successful_files, failed_files)
    """
    directory = Path(directory)
    
    if not directory.exists():
        print(f"Directory not found: {directory}")
        return [], []
    
    # Find matching files
    if recursive:
        files = list(directory.rglob(pattern))
    else:
        files = list(directory.glob(pattern))
    
    print(f"Found {len(files)} files matching '{pattern}' in {directory}")
    
    return fix_encoding_errors_batch(files, backup)


def verify_utf8_bom(file_path: Union[str, Path]) -> bool:
    """
    Verify that a file has UTF-8 BOM encoding.
    
    Args:
        file_path: Path to the file to verify
        
    Returns:
        True if file has UTF-8 BOM, False otherwise
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        return False
    
    try:
        with open(file_path, "rb") as f:
            data = f.read(3)  # BOM is 3 bytes
        return data == b"\xef\xbb\xbf"
    except Exception:
        return False


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python fix.py <file_or_directory> [pattern]")
        print("Example: python fix.py ./localization")
        print("Example: python fix.py ./localization *.yml")
        print("Example: python fix.py ./some_file.yml")
        sys.exit(1)
    
    target = sys.argv[1]
    pattern = sys.argv[2] if len(sys.argv) > 2 else "*.yml"
    
    target_path = Path(target)
    
    if target_path.is_file():
        # Fix single file
        result, has_bom = _detect_encoding_and_bom(target_path)
        print(f"Current encoding: {result.get('encoding')}, Has BOM: {has_bom}")
        success = fix_encoding_error(target_path)
        print(f"Result: {'Success' if success else 'Failed'}")
    elif target_path.is_dir():
        # Fix directory
        successful, failed = fix_directory_encoding(target_path, pattern)
        print(f"\n{'='*50}")
        print(f"Summary:")
        print(f"  Successful: {len(successful)}")
        print(f"  Failed: {len(failed)}")
        if failed:
            print(f"\nFailed files:")
            for f in failed:
                print(f"  - {f}")
    else:
        print(f"Invalid path: {target}")
        sys.exit(1)
