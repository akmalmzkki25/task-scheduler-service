"""Storage interfaces the services depend on.

Postgres and Redis implement these in production; tests use in-memory fakes.
"""

from collections.abc import Collection, Sequence
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.models import (
    ClaimedTask,
    ExecutionResult,
    ExecutionStatus,
    QuotaDecision,
    Task,
    User,
)


class UserRepository(Protocol):
    async def add(self, user: User) -> None:
        """Save a new user. Raises UserAlreadyExistsError on a duplicate username."""
        ...

    async def get(self, username: str) -> User | None: ...

    async def get_many(self, usernames: Collection[str]) -> dict[str, User]: ...


class TaskRepository(Protocol):
    async def add(self, task: Task) -> None: ...

    async def list_page(
        self, username: str | None, offset: int, limit: int
    ) -> tuple[list[Task], int]:
        """Return one page of tasks, oldest first, and the total matching count."""
        ...

    async def claim_due(self, now: datetime, tz: ZoneInfo, limit: int) -> list[ClaimedTask]:
        """Atomically take tasks with `next_run_at <= now` and move each to its next run.

        Two concurrent callers must never receive the same task.
        """
        ...


class ExecutionRepository(Protocol):
    async def add_many(self, results: Sequence[ExecutionResult]) -> None: ...

    async def list_page(
        self,
        username: str | None,
        status: ExecutionStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ExecutionResult], int]:
        """Return one page of executions, newest first, and the total matching count."""
        ...


class QuotaStore(Protocol):
    async def try_consume(self, username: str, day: date, limit: int) -> QuotaDecision:
        """Atomically use one unit of `day`'s quota if any is left."""
        ...

    async def get_usage(self, username: str, day: date) -> int: ...

    async def ping(self) -> None:
        """Raise if the store can't be reached."""
        ...
