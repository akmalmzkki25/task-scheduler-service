from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.domain.models import User

USERNAME_PATTERN = r"^[a-z0-9_]{3,50}$"


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN, examples=["alice"])
    daily_quota: int = Field(ge=0, le=10_000, examples=[3])


class UserOut(BaseModel):
    username: str
    daily_quota: int
    created_at: datetime

    @classmethod
    def from_domain(cls, user: User, tz: ZoneInfo) -> "UserOut":
        return cls(
            username=user.username,
            daily_quota=user.daily_quota,
            created_at=user.created_at.astimezone(tz),
        )


class UsageOut(BaseModel):
    date: date
    used: int
    limit: int


class UserWithUsageOut(UserOut):
    usage_today: UsageOut
