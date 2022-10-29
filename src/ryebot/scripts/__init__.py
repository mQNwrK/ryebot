from importlib import import_module

_scriptnames = ["excludata", "langsync", "testscript"]

scriptfunctions = dict(zip(
    _scriptnames,
    [import_module("ryebot.scripts." + script).script_main for script in _scriptnames]
))
