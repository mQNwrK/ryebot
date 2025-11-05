from typing import Iterable


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


class InvalidScriptConfigError(Exception):
    """Something in the script configuration is invalid, not further specified."""
    def __init__(self, scriptname: str, configkey: str, configvalue):
        self.scriptname = scriptname
        self.configkey = configkey
        self.configvalue = configvalue

    def __str__(self):
        return (
            f'The following configuration for the "{self.scriptname}" script '
            f'is invalid: {self.configkey}={self.configvalue!r}.'
        )


class InvalidScriptConfigTypeError(InvalidScriptConfigError):
    """A script configuration value has the wrong type."""
    def __init__(self, scriptname: str, configkey: str, configvalue, provided_type: type, expected_type: type|Iterable[type]):
        super().__init__(scriptname, configkey, configvalue)
        self.provided_type = provided_type
        # ensure `expected_type` is an iterable of types
        if isinstance(expected_type, type):
            self.expected_type = [expected_type]
        elif isinstance(expected_type, Iterable) and all(isinstance(t, type) for t in expected_type):
            self.expected_type = expected_type
        else:
            raise TypeError('expected_type must be type or Iterable[type]')

    def __str__(self):
        errorstr = (
            f'The value ({self.configvalue!r}) is of type '
            f'{self.provided_type.__name__} but it should be '
            f'{" or ".join(t.__name__ for t in self.expected_type)}.'
        )
        return super().__str__() + ' ' + errorstr


class StopwatchError(Exception):
    def __init__(self, running: bool = False):
        self.running = running

    def __str__(self):
        if self.running:
            return "Can't start an already-running stopwatch!"
        else:
            return "Can't stop a stopwatch that isn't running!"
