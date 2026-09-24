from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app.domain.scheduling import compute_next_run

JAKARTA = ZoneInfo("Asia/Jakarta")
NOON = time(12, 0)


def at(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=JAKARTA)


def test_returns_today_when_run_time_is_later() -> None:
    assert compute_next_run(NOON, JAKARTA, after=at(8)) == at(12)


def test_returns_tomorrow_when_run_time_already_passed() -> None:
    assert compute_next_run(NOON, JAKARTA, after=at(15)) == at(12, day=25)


def test_returns_tomorrow_when_exactly_at_run_time() -> None:
    assert compute_next_run(NOON, JAKARTA, after=at(12)) == at(12, day=25)


def test_compares_in_target_zone_when_after_is_utc() -> None:
    # 05:30 UTC is 12:30 in Jakarta, so today's noon has passed there.
    after = datetime(2026, 9, 24, 5, 30, tzinfo=UTC)

    result = compute_next_run(NOON, JAKARTA, after=after)

    assert result == at(12, day=25)
    assert result.tzinfo == JAKARTA


def test_rolls_over_month_end() -> None:
    after = datetime(2026, 9, 30, 23, 0, tzinfo=JAKARTA)

    assert compute_next_run(NOON, JAKARTA, after=after) == datetime(
        2026, 10, 1, 12, 0, tzinfo=JAKARTA
    )
