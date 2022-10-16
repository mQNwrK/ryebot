from datetime import datetime, timedelta, timezone

from ryebot.errors import StopwatchError


class Stopwatch():
    """Measures the time elapsed between two moments.

    >>> stopwatch = Stopwatch()
    >>> time.sleep(7)
    >>> print(stopwatch.stop())
    0:00:07.213994
    >>> print(stopwatch)
    0:00:07.213994
    >>> print(stopwatch.time)
    0:00:07.213994
    """

    def __init__(self, start_now: bool = True):
        """Create a new stopwatch that immediately starts running, unless `start_now` is `True`."""
        self._start_time: datetime = None
        self.time: timedelta = None
        if start_now:
            self.start()

    def start(self):
        """Start measuring time. Raises `StopwatchError` if already running."""
        if self._start_time is not None:
            raise StopwatchError(running=True)
        self._start_time = datetime.now(tz=timezone.utc)

    def stop(self):
        """Stop measuring time and return it. Raises `StopwatchError` if not currently running."""
        end_time = datetime.now(tz=timezone.utc)  # calling this as early as possible
        if self._start_time is None:
            raise StopwatchError(running=False)
        self.time = end_time - self._start_time
        self._start_time = None
        return self.time

    def __str__(self):
        return str(self.time)
