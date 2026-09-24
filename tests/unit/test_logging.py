import asyncio
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import SystemClock
from app.core.logging import ContextFilter, task_id_var, tick_id_var, user_var


def make_record() -> logging.LogRecord:
    return logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello", None, None)


def test_filter_fills_dash_when_no_context_is_set() -> None:
    record = make_record()

    assert ContextFilter().filter(record) is True
    assert (record.tick_id, record.task_id, record.user) == ("-", "-", "-")


def test_filter_copies_context_values() -> None:
    tokens = [tick_id_var.set("t1"), task_id_var.set("k1"), user_var.set("alice")]
    try:
        record = make_record()
        ContextFilter().filter(record)
    finally:
        for var, token in zip((tick_id_var, task_id_var, user_var), tokens, strict=True):
            var.reset(token)

    assert (record.tick_id, record.task_id, record.user) == ("t1", "k1", "alice")


async def test_context_does_not_leak_between_gathered_coroutines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("app.test.gather")
    logger.addFilter(ContextFilter())

    async def work(task_id: str) -> None:
        task_id_var.set(task_id)
        await asyncio.sleep(0)
        logger.info("done")

    with caplog.at_level(logging.INFO, logger="app.test.gather"):
        await asyncio.gather(work("a"), work("b"))

    assert sorted(r.task_id for r in caplog.records) == ["a", "b"]
    assert task_id_var.get() == "-"


def test_system_clock_returns_aware_time_in_its_zone() -> None:
    now = SystemClock(ZoneInfo("Asia/Jakarta")).now()

    assert now.utcoffset() == timedelta(hours=7)


def test_configure_logging_is_idempotent() -> None:
    from app.core.logging import configure_logging

    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("debug")
        configure_logging("info")

        ours = [h for h in root.handlers if getattr(h, "_task_scheduler", False)]
        assert len(ours) == 1
        assert root.level == logging.INFO
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
