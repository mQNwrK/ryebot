from importlib import import_module

_scriptnames = [
    "autolangsync",
    "capsredirects",
    "csscompile",
    "excludata",
    "extensionupdates",
    "langinfodata",
    "langsync",
    "testscript",
    "update_iteminfo",
    "update_mapviewer_versions",
    "update_npcinfo",
]

scriptfunctions = dict(zip(
    _scriptnames,
    [import_module("ryebot.scripts." + script).script_main for script in _scriptnames]
))
