import re
from mod_analyzer.encoding import detect_encoding
from mod_analyzer.mod.mod_list import DefinitionIdentifierNode, DefinitionValueNode, DefinitionNode

def extract_definitions(txt, root:DefinitionNode|None=None) -> DefinitionNode:
    lang_match = re.compile(r'(l_[A-Za-z_]+):$', re.MULTILINE).match(txt)
    lang = lang_match.group(1) if lang_match else 'unknown'
    root = root or DefinitionNode(lang, f'localization/{lang}')
    # Match lines like: "  key: "value"" across multiple lines
    # Use MULTILINE so ^/$ apply per-line and allow unicode values
    pattern = re.compile(r'^\s*(?P<key>[A-Za-z0-9_.-]+):\s*"(?P<value>.*)"\s*$', re.MULTILINE)
    for match in pattern.finditer(txt):
        key = match.group('key')
        value = match.group('value')
        root[key] = DefinitionValueNode(key, root.rel_dir, value=value)
    return root
    
if __name__ == "__main__":
    from pathlib import Path
    path = Path(r"C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310\2220098919\localization\simp_chinese\CFP_l_simp_chinese_artifacts_events.yml")
    txt = path.read_text(encoding=detect_encoding(path))
    x = extract_definitions(txt)
    x.pretty_print()