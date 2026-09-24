from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import Settings, mask_url

REQUIRED = {
    "database_url": "postgresql+asyncpg://postgres:secret@localhost:5432/task_scheduler",
    "redis_url": "redis://:secret@localhost:6379/1",
}


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**REQUIRED, **overrides})  # type: ignore[arg-type]


def test_defaults_use_jakarta_time_zone() -> None:
    settings = make_settings()

    assert settings.timezone == "Asia/Jakarta"
    assert settings.tz == ZoneInfo("Asia/Jakarta")
    assert settings.scheduler_enabled is True
    assert settings.tick_interval_seconds == 30


def test_rejects_zero_tick_interval() -> None:
    with pytest.raises(ValidationError, match="tick_interval_seconds"):
        make_settings(tick_interval_seconds=0)


def test_rejects_unknown_time_zone() -> None:
    with pytest.raises(ValidationError, match="Unknown time zone"):
        make_settings(timezone="Mars/Olympus")


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED["database_url"])
    monkeypatch.setenv("REDIS_URL", REQUIRED["redis_url"])
    monkeypatch.setenv("TASK_TIMEOUT_SECONDS", "5")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.task_timeout_seconds == 5


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+asyncpg://postgres:secret@localhost:5432/db",
            "postgresql+asyncpg://postgres:***@localhost:5432/db",
        ),
        ("redis://:secret@localhost:6379/1", "redis://:***@localhost:6379/1"),
        ("redis://localhost:6379/1", "redis://localhost:6379/1"),
    ],
)
def test_mask_url_hides_password(url: str, expected: str) -> None:
    assert mask_url(url) == expected
