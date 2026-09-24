"""Clock abstraction so scheduling logic can be tested with a controllable time source."""

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime."""
        ...


class SystemClock:
    def __init__(self, tz: ZoneInfo) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(self._tz)
