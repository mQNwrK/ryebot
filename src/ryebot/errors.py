class LoginError(RuntimeError):
    def __init__(self, targetwiki: str, details: str = ''):
        self.targetwiki = targetwiki
        self.details = details

    def __str__(self):
        if self.details:
            return f'Error while logging in to "{self.targetwiki}": {self.details}'
        return f'Error while logging in to "{self.targetwiki}"!'


class ScriptRuntimeError(RuntimeError):
    """To be raised from within the execution of a script."""
    pass


class NonexistentScriptConfigPageError(Exception):
    def __init__(self, scriptname: str, pagename: str):
        self.scriptname = scriptname
        self.pagename = pagename

    def __str__(self):
        return (
            f'The configuration page for the "{self.scriptname}" script could '
            f'not be found at "{self.pagename}"!'
        )


class StopwatchError(Exception):
    def __init__(self, running: bool = False):
        self.running = running

    def __str__(self):
        if self.running:
            return "Can't start an already-running stopwatch!"
        else:
            return "Can't stop a stopwatch that isn't running!"
