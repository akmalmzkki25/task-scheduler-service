"""Pure scheduling rules, kept free of I/O so they can be tested directly."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def compute_next_run(run_at: time, tz: ZoneInfo, after: datetime) -> datetime:
    """Return the first moment strictly after `after` whose wall-clock time in `tz` is `run_at`."""
    local_day = after.astimezone(tz).date()
    candidate = datetime.combine(local_day, run_at, tzinfo=tz)
    if candidate <= after:
        candidate = datetime.combine(local_day + timedelta(days=1), run_at, tzinfo=tz)
    return candidate
