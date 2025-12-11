from pathlib import Path
import tree_sitter as ts
import tree_sitter_paradox as tsp
from mod_analyzer.encoding import detect_encoding
from mod_analyzer.mod.mod_list import DefinitionIdentifierNode, DefinitionValueNode, DefinitionNode

language = ts.Language(tsp.language())
parser = ts.Parser(language)

def dict_pretty_print(d: dict, indent: int = 0):
    for key, value in d.items():
        print('    ' * indent + str(key) + ':', end=' ')
        if isinstance(value, dict):
            print()
            dict_pretty_print(value, indent + 1)
        else:
            print(str(value))
            
def extract_array_vals(node: ts.Node) -> list:
    assert node.type in ('array', 'hex_array')
    return [
            (n.text or b'').decode('utf-8')
            for n in node.children if n.type in ('simple_value','number')]

def extract_node_definitions(ts_node: ts.Node, root:DefinitionNode, max_depth:int= -1, _depth = 0) -> DefinitionNode:
    if root is None:
        root = DefinitionIdentifierNode('root', './', type='root')
    if max_depth >=0 and _depth > max_depth:
        return root
    rel_dir = root.rel_dir # rel_dir represents the source_file path, pass it down
    if ts_node.type in '{}':
        return root
    elif ts_node.type in 'statement':
        for child in ts_node.children:
            if child.type == 'simple_value': # this is an unnamed value inside a block
                val = (child.text or b'').decode('utf-8')
                root[val] = DefinitionValueNode(val, rel_dir, value=val)
            else:
                extract_node_definitions(child, root, max_depth, _depth)                    
        return root
    elif ts_node.type in ('source_file','map'):
        for child in ts_node.children:
            val = extract_node_definitions(child, root, max_depth, _depth)
        return root
    
    elif ts_node.type in ('assignment', 'typed_assignment'): 
        if ts_node.type == 'typed_assignment':
            pass
        # this node represents a key-value pair
        # key: IdentifierDefNode.name
        # value: simple string/array or leaf IdentifierDefNode (nested block)
        ts_key_node = ts_node.child_by_field_name('key')
        ts_val_node = ts_node.child_by_field_name('value')
        if not (ts_key_node and ts_val_node):
            return root
        key = (ts_key_node.text or b'').decode('utf-8')
        if ts_val_node.type =='simple_value': # ex: factor = 10
            child = DefinitionValueNode(key, rel_dir, value=(ts_val_node.text or b'').decode('utf-8'))
        elif ts_val_node.type =='array': # ex: key = { val1 val2 val3 }
            child = DefinitionValueNode(key, rel_dir, value=extract_array_vals(ts_val_node))
        elif ts_val_node.type =='tagged_array': # ex: color = hsv{ 0.5 0.5 0.5 }
            tag_node = ts_val_node.child_by_field_name('tag')
            tag = (tag_node.text or b'').decode('utf-8') if tag_node else ''
            if _value_node:= ts_val_node.child_by_field_name('value'):
                child = DefinitionValueNode(key, rel_dir, value=tag+"{"+", ".join(extract_array_vals(_value_node))+"}")
            else: # empty tagged array
                child = DefinitionValueNode(key, rel_dir, value=tag+"{}")
        else: # nested block ('statement', 'map')
            child = DefinitionIdentifierNode(key, rel_dir, source=root.source)
            val = extract_node_definitions(ts_val_node, child, max_depth, _depth+1)
        root[key] = child
        return root
    return root

# def extract_file_definitions(path: str|Path, max_depth:int= -1) -> DefinitionNode:
#     path = Path(path)
#     encoding = detect_encoding(path)
#     with open(path, mode='r', encoding=encoding) as f:
#         source = f.read()
#     tree = parser.parse(source.encode('utf-8'))
#     return extract_node_definitions(
#         tree.root_node, 
#         # use #def as a virtual root node, for tracking from root of files
        
#         max_depth=max_depth
#     )
        
        
if __name__ == "__main__":    
    source = b"""
    add_character_modifier = {
        modifier = "name_of_modifier"
        days = 30
        nested_block = {
            color = hsv{ 0.025 0.55 0.7 }
            color2 = hex{50779b}
            inner_key = {
                subkey1 = value1
                subkey2 = value2
                nested_key = {
                    subkey1 = value1
                    subkey2 = value2
                }
            }
        }
    }
    some_other_command = yes
    list_of_things = { apple banana cherry }
    events = {
        something.1
        something.2
        delay = {days = 10}
        something.3        
    }
    """
                
    
    path = r'C:\Users\Alan\Documents\Paradox Interactive\Crusader Kings III\mod\Carnal Consequences\common\character_interactions\zzz_cc_00_scheme_interactions_override.txt'
    # with open(path, mode='rb') as f:
    #     source = f.read()
    tree = parser.parse(source)
    x = extract_node_definitions(tree.root_node, DefinitionIdentifierNode('root','./'), max_depth=0)
    # x=build_definition_tree(tree, max_depth=-1)
    if x is not None:
        x.pretty_print()
    print(tree.root_node)
