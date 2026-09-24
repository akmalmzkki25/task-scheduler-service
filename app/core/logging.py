"""Logging setup that stamps every record with the current tick, task, and user.

The values live in context variables. `asyncio.gather` runs each coroutine in a task
with its own copy of the context, so concurrent executions never see each other's IDs.
"""

import logging
import sys
from contextvars import ContextVar

tick_id_var: ContextVar[str] = ContextVar("tick_id", default="-")
task_id_var: ContextVar[str] = ContextVar("task_id", default="-")
user_var: ContextVar[str] = ContextVar("user", default="-")

LOG_FORMAT = (
    "%(asctime)s %(levelname)-7s %(name)-14s "
    "[tick=%(tick_id)s task=%(task_id)s user=%(user)s] %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.tick_id = tick_id_var.get()
        record.task_id = task_id_var.get()
        record.user = user_var.get()
        return True


def configure_logging(level: str) -> None:
    """Install one stdout handler on the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_task_scheduler", False):
            root.removeHandler(existing)
    handler._task_scheduler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
