"""User registration and quota lookups."""

from datetime import date

from app.core.clock import Clock
from app.domain.errors import UserNotFoundError
from app.domain.models import User
from app.repositories.interfaces import QuotaStore, UserRepository


class UserService:
    def __init__(self, users: UserRepository, quota: QuotaStore, clock: Clock) -> None:
        self._users = users
        self._quota = quota
        self._clock = clock

    async def register(self, username: str, daily_quota: int) -> User:
        user = User(username=username, daily_quota=daily_quota, created_at=self._clock.now())
        await self._users.add(user)
        return user

    async def get(self, username: str) -> User:
        user = await self._users.get(username)
        if user is None:
            raise UserNotFoundError(username)
        return user

    async def get_usage_today(self, username: str) -> tuple[User, int, date]:
        user = await self.get(username)
        today = self._clock.now().date()
        used = await self._quota.get_usage(username, today)
        return user, used, today
