from importlib import import_module

_scriptnames = [
    "csscompile",
    "excludata",
    "extensionupdates",
    "langinfodata",
    "langsync",
    "testscript",
    "update_iteminfo",
    "update_npcinfo",
    "update_mapviewer_versions"
]

scriptfunctions = dict(zip(
    _scriptnames,
    [import_module("ryebot.scripts." + script).script_main for script in _scriptnames]
))
