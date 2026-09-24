"""Application settings loaded from environment variables and `.env`."""

from functools import cached_property, lru_cache
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    test_database_url: str | None = None
    test_redis_url: str | None = None

    timezone: str = "Asia/Jakarta"
    scheduler_enabled: bool = True
    tick_interval_seconds: float = Field(default=30, ge=1, le=3600)
    task_timeout_seconds: float = Field(default=30, ge=0.001, le=600)
    claim_batch_size: int = Field(default=100, ge=1, le=1000)
    simulated_latency_seconds: float = Field(default=0.1, ge=0, le=10)
    seed_demo_data: bool = False
    log_level: str = "INFO"

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone '{value}'") from exc
        return value

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def mask_url(url: str) -> str:
    """Replace the password in a connection URL with `***` so it can be logged."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    userinfo = f"{parts.username or ''}:***"
    host = parts.hostname or ""
    netloc = f"{userinfo}@{host}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))
