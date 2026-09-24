"""In-memory test doubles shared by unit and API tests."""

from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.exceptions import ConnectionError as RedisConnectionError

from app.domain.errors import UserAlreadyExistsError
from app.domain.models import (
    ClaimedTask,
    ExecutionResult,
    ExecutionStatus,
    QuotaDecision,
    Task,
    User,
)
from app.domain.scheduling import compute_next_run


class FakeClock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}

    async def add(self, user: User) -> None:
        if user.username in self.users:
            raise UserAlreadyExistsError(user.username)
        self.users[user.username] = user

    async def get(self, username: str) -> User | None:
        return self.users.get(username)

    async def get_many(self, usernames: Collection[str]) -> dict[str, User]:
        return {name: self.users[name] for name in usernames if name in self.users}


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[UUID, Task] = {}

    async def add(self, task: Task) -> None:
        self.tasks[task.id] = task

    async def list_page(
        self, username: str | None, offset: int, limit: int
    ) -> tuple[list[Task], int]:
        rows = sorted(
            (t for t in self.tasks.values() if username is None or t.username == username),
            key=lambda t: t.created_at,
        )
        return rows[offset : offset + limit], len(rows)

    async def claim_due(self, now: datetime, tz: ZoneInfo, limit: int) -> list[ClaimedTask]:
        due = sorted(
            (t for t in self.tasks.values() if t.next_run_at <= now),
            key=lambda t: t.next_run_at,
        )[:limit]
        claimed = []
        for task in due:
            moved = replace(task, next_run_at=compute_next_run(task.run_at, tz, now))
            self.tasks[task.id] = moved
            claimed.append(ClaimedTask(task=moved, scheduled_for=task.next_run_at))
        return claimed


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self.results: list[ExecutionResult] = []

    async def add_many(self, results: Sequence[ExecutionResult]) -> None:
        self.results.extend(results)

    async def list_page(
        self,
        username: str | None,
        status: ExecutionStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ExecutionResult], int]:
        rows = [
            r
            for r in reversed(self.results)
            if (username is None or r.username == username)
            and (status is None or r.status == status)
        ]
        return rows[offset : offset + limit], len(rows)


class InMemoryQuotaStore:
    def __init__(self) -> None:
        self.usage: dict[tuple[str, date], int] = {}

    async def try_consume(self, username: str, day: date, limit: int) -> QuotaDecision:
        used = self.usage.get((username, day), 0)
        if used >= limit:
            return QuotaDecision(allowed=False, used=used, limit=limit)
        self.usage[(username, day)] = used + 1
        return QuotaDecision(allowed=True, used=used + 1, limit=limit)

    async def get_usage(self, username: str, day: date) -> int:
        return self.usage.get((username, day), 0)

    async def ping(self) -> None:
        return None


class FailingQuotaStore(InMemoryQuotaStore):
    """Behaves like Redis being down."""

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__()
        self.error = error or RedisConnectionError("Connection refused")

    async def try_consume(self, username: str, day: date, limit: int) -> QuotaDecision:
        raise self.error

    async def get_usage(self, username: str, day: date) -> int:
        raise self.error

    async def ping(self) -> None:
        raise self.error
