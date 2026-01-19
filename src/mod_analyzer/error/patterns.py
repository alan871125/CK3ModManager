import re
from pathlib import Path
from .datastructure import DualAccessDict

# === Example === 
# ```{ck3 script}
# window = { 
# 	name = "Illusion_index_windows"
# }
# ```
# obj: window
# key:name
# value: Illusion_index_windows
# ===============
# <message>: Some error message to provide more information
# <file>: The file where the error occurred
# <file2>: The file where the error occurred (2nd File)
# <line>: The line number where the error occurred
# <line2> The line number where the error occurred (2nd File)
# <obj>: The owner of the element where the error occurred
# <key>: The key of the element where the error occurred
# <key2>: The 2nd key of the element where the error occurred
# <value>: The value of the element where the error occurred
# <type>: The type of the element where the error occurred (e.g., gene template, gene category)
# ?<trigger> jomini_trigger.cpp:243

regex_multiline = DualAccessDict( # regex patterns for multiline matching
    # jomini_script_system.cpp:303
    SCRIPT_ERROR = r"file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<object>[^\)]+)",
    # pdx_persistent_reader.cpp:216
    FAILED_TO_READ_KEY_REFERENCE = r"Failed to read key reference: (?P<key>\w+):\s*(?P=key), near line: (?P<line>\d+)",
    # ^.*\[pdx_persistent_reader.cpp:216\]: Error: "(Failed to read key reference: ([^"]+\n?)+)" in file: "([^\s]+)" near line: (\d+)\n
    # pdx_persistent_reader.cpp:216
)   
regex = DualAccessDict(
    # NOTDONE
    # pdx_data_factory.cpp:1032
    # pdx_data_factory.cpp:1344
    # pdx_data_factory.cpp:1351
    # pdx_data_factory.cpp:1413
    # pdx_data_factory.cpp:1417
    # character_interaction_filters.cpp:71
    # character_interaction_filters.cpp:66
    
    #=========
    #===character_interaction_filters.cpp
    # character_interaction_filters.cpp:66
    CHANCE_OUT_OF_BOUNDS = r"chance should be .* at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^\)]+)\)",
    # character_interaction_filters.cpp:71
    AT_LEAST_ONE_AI_RECIPIENT = r"needs at least one ai_recipient scripted at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^\)]+)\)",
    #===jomini_effect.cpp
    # jomini_effect.cpp:1136
    OBJ_SET_NOT_USED = r"(?P<type>[\w]+( target)?) '(?P<key>[^\']+)' is set but is never used.",
    # jomini_effect.cpp:1152
    OBJ_NOT_SET_USED = r"(?P<type>[\w]+( target)?) '(?P<key>[^\']+)' is used but is never set.",
    
    # holding_type.cpp:118
    DUPLICATE_BUILDING_TYPE = r"Duplicate holding building type (?P<type>[^\s]+), for holding (?P<obj>[^\s]+)",
    # holding_type.cpp:138
    INVALID_BUILDING_TYPE = r"Invalid building type (?P<type>[^\s]+), for holding (?P<obj>[^\s]+)",
    # jomini_eventmanager.cpp:370
    EVENT_ORPHANED = r"Event (?P<obj>[^\s]+) is orphaned",
    # jomini_eventmanager.cpp:370
    EVENT_ORPHANED_WITH_CALLERS = r"Event (?P<obj>[^\s]+) is scripted as an orphan, but has callers",
    # jomini_custom_text.h:94
    OBJECT_TYPE_NOT_VALID = r"Object of type '(?P<type>[^\']+)' is not valid for '(?P<obj>[^\']+)'",
    # jomini_trigger.cpp:243
    # TRIGGER_POSTVALIDATE_FALSE = r"PostValidate of trigger '(?P<trigger>[^\']+)' returned false at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^:]+):(?P<action>[^\)]+)\)",
    POSTVALIDATE_RETURNED_FALSE = r"PostValidate of (?P<type>\w+) '(?P<key>[^\']+)' returned false at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^\[^:]+)(\[args#\d+\])?(:(?P<action>[^\)]+))?\)",
    # jomini_trigger.cpp:749
    INCONSISTENT_SCOPES = r"Inconsistent (?P<type>.*) scopes \((?P<scope1>[^\s]+) vs\. (?P<scope2>[^\s]+)\) infile: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^\[^:]+)(\[args#\d+\])?(:(?P<action>[^\)]+))?\)",
    # dlc_descriptor.cpp:70
    INVALID_SUPPORTED_VERSION = r"Invalid supported_version in file:\s+(?P<file>mod/[^\s]+)\s+line:\s*(?P<line>\d+)",
    # virtualfilesystem_physfs.cpp:1594
    PATH_OVER_250_CHARACTERS = r"(?P<file>.+) path is over \d+ characters long and will likely cause a crash on open\. Consider changing install path to something shorter",
    # localization_reader.cpp:111
    ILLEGAL_LOC_BREAK_CHARACTER = r"Illegal localization break character \(`(?P<char>.)`\) at line (?P<line>\d+) and column (?P<column>\d+) in (?P<file>[^\n]+)",
    # localization_reader.cpp:402
    MISSING_UTF8_BOM = r"Missing UTF8 BOM in '(?P<file>[^\n]+)'",
    # localize.cpp:1854
    ENCODING_ERROR = r"'(?P<file>[^'\s]+)' should be.*in utf\-?8\-?bom encoding",
    # localization_reader.cpp:445
    INVALID_CHARACTER_IN_KEY_NAME = r"(?P<message>(Invalid character\s+'(?P<char>[^']+)))'\s+in key name\s+'(?P<key>[^']+)'.+in\s+(?P<file>[^\n]+)",
    # localization_reader.cpp:451
    MISSING_COLON_SEPARATOR = r"Missing colon.*separator at line (?P<line>\d+) and column (?P<column>\d+) in (?P<file>[^\n]+)",
    # localization_reader.cpp:535
    MISSING_QUOTED_STRING_VALUE = r"Missing quoted string value for key '(?P<key>[^']+)' at line (?P<line>\d+) and column (?P<column>\d+) in (?P<file>[^\n]+)",
    # localization_reader.cpp:581 & 575
    UNEXPECTED_LOC_TOKEN = r"Unexpected (localization )?token '(?P<key>[^']*)' at line (?P<line>\d+) and column (?P<column>\d+) in (?P<file>[^\n]+)",
    
    # culture_template_data.cpp:304
    # culture_name_equivalency.cpp:101
    # characterhistory.cpp:807
    MISSING_LOC = r"Missing loc( for)?( name)? '?(?P<value>[^\']+)'?( (?P<message> for character '[\']+'))?",
    
    
    
    # jomini_custom_text.cpp:179
    # artifact_type.cpp:25
    MISSING_LOC_KEY = r"Missing loc key '(?P<key>[^']+)' for custom localization '(?P<obj>[^']+)' \(or variant\), at 'file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj2>[^']+)\)'",
    MISSING_LOC_KEY_KEY_ONLY = r"Missing loc key: '?(?P<key>[^\']+)'?",
    # jomini_dynamicdescription.cpp:57
    UNRECOGNIZED_LOC_KEY_NEAR_FILE = r"Unrecognized loc key (?P<key>[^\s]+)\. Near file: (?P<file>[^\n]+) line: (?P<line>\d+)(\s\((?P<obj>[^\)]+)\))?",
    # jomini_dynamicdescription.cpp:66
    UNRECOGNIZED_LOC_KEY = r"Unrecognized loc key (?P<key>[^\s]+)\. file: (?P<file>[^\n]+) line: (?P<line>\d+)(\s\((?P<obj>[^\)]+)\))?",
    UNRECOGNIZED_LOC_KEY_NO_FILE = r"Unrecognized loc key (?P<key>[^\s]+)\. (?P<obj>[^\s]+)",
    # pdx_data_localize.cpp:151&136
    LOC_STR_DATA_ERROR = r"Data error in loc string '(?P<key>[^\s]+)'",
    # pdx_locstring.cpp:93
    MISSING_LOCALIZATION = r"Key is missing localization: (?P<key>[^\s]+)",
    # pdx_localize.cpp:267
    LOC_KEY_HASH_COLLISION = r"Localization key hash collision. Key '(?P<key>[^']+)' and '(?P<key2>[^']+)' have the (?P<message>.+)",
    # pdx_localize.cpp:279
    DUPLICATE_LOC_KEY = r"Duplicate localization key\. Key '(?P<key>[^']+)' is defined in both '(?P<file>[^\n]+)' and '(?P<file2>[^\n]+)'",    
    # pdx_localize.cpp:933 (only key)
    TRYING_TO_IMPORT_LOC_KEY_OUTSIDE_OF_LANGUAGE = r"Trying to import a localization key outside of a language: (?P<key>[^\s]+)",
    # pdx_gui_factory.cpp:317
    GUI_FAILED_READING_PROPERTY = r"failed reading property, at line (?P<line>\d+) in file (?P<file>[^\n]+)",
    # pdx_gui_factory.cpp:937
    GUI_FAILED_CONVERTING_PROPERTY = r"(?P<file>[^\n]+):(?P<line>\d+) - Failed converting property '(?P<property>[^']+)'\((?P<some_num>\d+)\)",
    # pdx_gui_factory.cpp:663
    GUI_DUPLICATE_CHILD_WIDGET = r"(?P<file>[^\n]+):(?P<line>\d+) - Child '(?P<value>[^\']+)' already exists added at (?P<file2>[^\s]+):(?P<line2>\d+)\. Duplicate children with the same name override previous widgets\.",
    # pdx_gui_localize.cpp:358
    GUI_FAILED_PARSING_LOCALIZED_TEXT = r"(?P<file>[^\n]+):(?P<line>\d+) - Failed parsing localized text: (?P<key>[^\s]+)",
    # pdx_gui_widget.cpp:2154
    GUI_PROPERTY_NOT_HANDLED = r"(?P<file>[^\n]+):(?P<line>\d+) - Property '(?P<key>[^\']+)'\((?P<some_num>[^\)]+)\) not handled",
    # pdx_gui_factory.cpp:1540
    GUI_ERROR_SETTING_PROPERTIES = r"(?P<file>[^\n]+):(?P<line>\d+) - Error setting properties for '(?P<value>[^\']*)' \((?P<type>[^\)]+)\)", 
    # pdx_gui_layout.cpp:137|pdx_gui_container.cpp:53|pdx_gui_container.cpp:142
    GUI_ERRORS = r"(?P<file>[^\n]+):(?P<line>\d+) - (?P<message>.+)",
    # # GUI_WIDGET_HAVING_POSITION = r"(?P<file>[^\n]+):(?P<line>\d+) - Widget cannot have a position in a layout",
    # # pdx_persistent_reader.cpp:216 # maybe already covered in other patterns (seems to be error passing)
    # # Error: "Failed to read key reference: ([^"]+)" in file: "([^\s]+)" near line: (\d+)
    # FAILED_TO_READ_KEY_REFERENCE = r'Error: "(?P<message>(Failed to read key reference: [^\"]\n?)+)" in file: "(?P<file>[^\"]*)" near line: (?P<line>\d+)',
    # pdx_persistent_reader.cpp:216
    FAILED_TO_READ_KEY_REFERENCE = r'Failed to read key reference: (?P<key>[^:]*): ([^,]*), .*line: (?P<line>\d+)( in file: (?P<file>[^"]+))',
    # FAILED_TO_READ_KEY_REFERENCE = r'Error: "(?P<message>(Failed to read key reference: ([^:]+): ([^,]+), .*line: \d+\n?)+)" in file: "(?P<file>[^"]+)" near line: \d+',
    # # UNEXPECTED_TOKEN = r'Error: "Unexpected token: (?P<token>[^,]+), near line: (?P<line>\d+)" in file: "(?P<file>[^\"]+)" near line: \d+', # not sure what the 2nd refers to
    # # UNKNOWN_TRIGGER = r'Error: "Unknown trigger: (?P<trigger>[^,]+), near line: (?P<line>\d+)" in file: "(?P<file>[^\"]+)" near line: \d+', # line seems to match
    # # UNKOWN_EFFECT = r'Error: "Unknown effect: (?P<effect>[^,]+), near line: (?P<line>\d+)" in file: "(?P<file>[^\"]+)" near line: \d+', # line seems to match
    UNKOWN_SCRIPT_ELEMENT = r'Error: "((Unknown)|(Unexpected)) (?P<type>[^:]+): (?P<key>[^,]+), near line: (?P<line>\d+)( \(expanded from file: .+ line: \d+\))?" in file: "(?P<file>[^"]+)" near line: \d+',
    INALID_NEGATIVE_VALUE = r'Error: "invalid negative value for \'(?P<key>[^\']+)\': (.*), near line: (?P<line>\d+)( \(expanded from file: .+ line: \d+\))?" in file: "(?P<file>[^"]+)" near line: \d+',
    # INALID_NEGATIVE_VALUE = r'Error: "invalid negative value for \'(?P<element>[^\']+)\': (?P=element), near line: (?P<line>\d+)( \(expanded from file: .+ line: \d+\))?" in file: "(?P<file>[^"]+)" near line: \d+',
    # pdx_gui_localize.cpp:207
    GUI_UNLOCALIZED_TEXT = r"Unlocalized text '(?P<text>[^']+)' at (?P<file>[^\n]+):(?P<line>\d+), either localize it or use the raw_text property instead of text",
    
    # portraitcontext.cpp:136
    UNKOWN_GENE_TEMPLATE = r"Unknown (?P<key>\S+) gene template (?P<value>\S+) at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>\S+)\)",
    # portraitcontext.cpp:184
    NO_GENE_WITH_KEY_IN_GROUP = r"No gene with key: (?P<key>\S+) in group human at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>\S+)\)",
    # NO_GENE_WITH_KEY_IN_GROUP = No gene with key: (\S+) in group human at file: ([^\s]+) line: \d+ \(\S+\)
    # portraitcontext.cpp:239
    GENE_READ_TWICE = r'Trying to read gene (?P<key>\S+) a second time at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>\S+)\)',
    # portraitcontext.cpp:326
    PERSISTENT_PORTRAIT_INFO_MISSING_GENE = r"Persistent portrait info missing gene (?P<key>\S+)! at 'file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>\S+)\)'",
    
    
    # ethnicity: ethnicity.cpp:304
    GENE_CATEGORY_DNA_INFLUENCED = r"gene category '(?P<key>\S+)' cannot be influenced by DNA, at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>\S+)\)",
    # ethnicity: ethnicity.cpp:174
    INVALID_COLOR_BOUNDS = r"invalid color bounds\. Expected format \{ xmin, ymin, xmax, ymax \}\. (?P<message>.+?)\. file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>\S+)\)",
    # game_concepts.cpp:208 #TODO: verify, not sure what each group represents
    CONCEPT_COLLISION = r"Trying to add a Game Concept or Alias ('(?P<key>[^']+)') from concept ('(?P<value>[^']+)') that collides.*('(?P<key2>[^']+)')",
    # title_links.cpp:214
    INVALID_LANDED_TITLE = r"Failed to fetch a valid landed title '(?P<value>[^']+)' at location 'file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^\)]+)\)'",
    CHARACTER_INTERACTION_FILTER_ERROR = r"(?P<message>.*) at file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^\)]+)\)",
    # jomini_script_system.cpp:303
    SCRIPT_ERROR = r'(file: (?P<file>[^\n]+) line: (?P<line>\d+) \((?P<obj>[^\)\[]+)\))(\[args#\d+\])?',
    
)
source_related_errors = {
    "character_interaction_filters.cpp:66": ["CHANCE_OUT_OF_BOUNDS"],
    "character_interaction_filters.cpp:71": ["AT_LEAST_ONE_AI_RECIPIENT"],
    "jomini_script_system.cpp:303": ["SCRIPT_ERROR"],
    "dlc_descriptor.cpp:70": ["INVALID_SUPPORTED_VERSION"],
    "holding_type.cpp:118": ["DUPLICATE_BUILDING_TYPE"],
    "holding_type.cpp:138": ["INVALID_BUILDING_TYPE"],
    "jomini_effect.cpp:1136": ["OBJ_SET_NOT_USED"],    
    "jomini_effect.cpp:1152": ["OBJ_NOT_SET_USED"],
    "jomini_eventmanager.cpp:370": ["EVENT_ORPHANED", "EVENT_ORPHANED_WITH_CALLERS"],
    "jomini_custom_text.h:94": ["OBJECT_TYPE_NOT_VALID"],
    "jomini_custom_text.cpp:179": ["MISSING_LOC_KEY", "MISSING_LOC_KEY_KEY_ONLY"],
    "jomini_trigger.cpp:243": ["POSTVALIDATE_RETURNED_FALSE"],
    "jomini_trigger.cpp:749": ["INCONSISTENT_SCOPES"],
    "jomini_effect.cpp:139": ["POSTVALIDATE_RETURNED_FALSE"],
    "artifact_type.cpp:25": ["MISSING_LOC_KEY", "MISSING_LOC_KEY_KEY_ONLY"],
    "jomini_dynamicdescription.cpp:57": ["UNRECOGNIZED_LOC_KEY_NEAR_FILE"],
    "jomini_dynamicdescription.cpp:66": ["UNRECOGNIZED_LOC_KEY", "UNRECOGNIZED_LOC_KEY_NO_FILE"],
    "virtualfilesystem_physfs.cpp:1594": ["PATH_OVER_250_CHARACTERS"],
    "localization_reader.cpp:111": ["ILLEGAL_LOC_BREAK_CHARACTER"],
    "localization_reader.cpp:402": ["MISSING_UTF8_BOM"],
    "localize.cpp:1854": ["ENCODING_ERROR"],
    "localization_reader.cpp:445": ["INVALID_CHARACTER_IN_KEY_NAME"],
    "localization_reader.cpp:451": ["MISSING_COLON_SEPARATOR"],
    "localization_reader.cpp:535": ["MISSING_QUOTED_STRING_VALUE"],
    "localization_reader.cpp:575": ["UNEXPECTED_LOC_TOKEN"],
    "localization_reader.cpp:581": ["UNEXPECTED_LOC_TOKEN"],
    "culture_template_data.cpp:304": ["MISSING_LOC"],
    "culture_name_equivalency.cpp:101": ["MISSING_LOC"],
    "characterhistory.cpp:807": ["MISSING_LOC"],
    "pdx_data_localize.cpp:136": ["LOC_STR_DATA_ERROR"],
    "pdx_data_localize.cpp:151": ["LOC_STR_DATA_ERROR"],
    "pdx_locstring.cpp:93": ["MISSING_LOCALIZATION"],
    "pdx_localize.cpp:267": ["LOC_KEY_HASH_COLLISION"],
    "pdx_localize.cpp:279": ["DUPLICATE_LOC_KEY"],
    "pdx_localize.cpp:933": ["TRYING_TO_IMPORT_LOC_KEY_OUTSIDE_OF_LANGUAGE"],
    "pdx_gui_factory.cpp:317": ["GUI_FAILED_READING_PROPERTY"],
    "pdx_gui_factory.cpp:937": ["GUI_FAILED_CONVERTING_PROPERTY"],
    "pdx_gui_factory.cpp:663": ["GUI_DUPLICATE_CHILD_WIDGET"],
    "pdx_gui_factory.cpp:1540": ["GUI_ERROR_SETTING_PROPERTIES"],
    "pdx_gui_widget.cpp:2154": ["GUI_PROPERTY_NOT_HANDLED"],
    "pdx_gui_layout.cpp:137": ["GUI_ERRORS"],
    "pdx_gui_container.cpp:53": ["GUI_ERRORS"],
    "pdx_gui_container.cpp:142": ["GUI_ERRORS"],
    "pdx_gui_localize.cpp:207": ["GUI_UNLOCALIZED_TEXT"],
    "pdx_gui_localize.cpp:358": ["GUI_FAILED_PARSING_LOCALIZED_TEXT"],
    "pdx_persistent_reader.cpp:216": ["FAILED_TO_READ_KEY_REFERENCE", "UNKOWN_SCRIPT_ELEMENT", "INALID_NEGATIVE_VALUE"],
    "portraitcontext.cpp:136": ["UNKOWN_GENE_TEMPLATE"],
    "portraitcontext.cpp:184": ["NO_GENE_WITH_KEY_IN_GROUP"],
    "portraitcontext.cpp:239": ["GENE_READ_TWICE"],
    "portraitcontext.cpp:326": ["PERSISTENT_PORTRAIT_INFO_MISSING_GENE"],
    "ethnicity.cpp:304": ["GENE_CATEGORY_DNA_INFLUENCED"],
    "ethnicity.cpp:174": ["INVALID_COLOR_BOUNDS"],
    "game_concepts.cpp:208": ["CONCEPT_COLLISION"],
    "title_links.cpp:214": ["INVALID_LANDED_TITLE", "CHARACTER_INTERACTION_FILTER_ERROR"],
}



if __name__ == '__main__':
    # --- Prefix all inner groups with the pattern name
    def prefix_groups(name, pattern):
        return re.sub(r"\?P<(\w+)>", f"?P<{name}_\\1>", pattern)

    combined_pattern = "|".join(
        f"(?P<{name}>{prefix_groups(name, pattern)})"
        for name, pattern in regex.items()
    )

    combined = re.compile(combined_pattern)

    results = []
    results_table ={}
    result_count = {}
    line_count = 0-3
    with open(Path(__file__).parent/"error.log", encoding="utf-8") as f:
        for line in f:
            line_count += 1
            if m := combined.search(line):
                kind = m.lastgroup
                result_count[kind] = result_count.get(kind, 0) + 1
                # Extract only this pattern's prefixed groups
                data = {k.replace(f"{kind}_", ""): v for k, v in m.groupdict().items()
                        if k.startswith(f"{kind}_") and v is not None}
                data["type"] = kind
                results.append(data)
                results_table.setdefault(kind, []).append(data)
    print(len(results), len(regex), line_count)
    for kind in regex.keys():
        print(f"{kind}: {result_count.get(kind, 0)}")
    print('done')
