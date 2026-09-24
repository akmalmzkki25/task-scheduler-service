"""Accepts task submissions as dictionaries and stores them with their first run time."""

from collections.abc import Mapping
from datetime import datetime, time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.clock import Clock
from app.domain.errors import InvalidTaskError, UserNotFoundError
from app.domain.models import Task
from app.domain.scheduling import compute_next_run
from app.repositories.interfaces import TaskRepository, UserRepository
from app.strategies.base import format_validation_error
from app.strategies.registry import StrategyRegistry

TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class TaskSubmission(BaseModel):
    """The dictionary shape a task is submitted in. Also the API request body."""

    model_config = ConfigDict(extra="forbid")

    user: str = Field(min_length=1, max_length=50)
    time: str = Field(pattern=TIME_PATTERN, examples=["12:00"])
    action: str = Field(min_length=1, max_length=50)
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def run_at(self) -> time:
        return datetime.strptime(self.time, "%H:%M").time()


class TaskService:
    def __init__(
        self,
        users: UserRepository,
        tasks: TaskRepository,
        registry: StrategyRegistry,
        clock: Clock,
        tz: ZoneInfo,
    ) -> None:
        self._users = users
        self._tasks = tasks
        self._registry = registry
        self._clock = clock
        self._tz = tz

    async def submit(self, raw: Mapping[str, Any] | TaskSubmission) -> Task:
        submission = self._parse(raw)
        if await self._users.get(submission.user) is None:
            raise UserNotFoundError(submission.user)
        strategy = self._registry.get(submission.action)
        params = strategy.parse_params(submission.params)

        now = self._clock.now()
        task = Task(
            id=uuid4(),
            username=submission.user,
            run_at=submission.run_at,
            action=submission.action,
            params=params.model_dump(mode="json"),
            next_run_at=compute_next_run(submission.run_at, self._tz, now),
            created_at=now,
        )
        await self._tasks.add(task)
        return task

    async def list_tasks(
        self, username: str | None, page: int, limit: int
    ) -> tuple[list[Task], int]:
        return await self._tasks.list_page(username, offset=(page - 1) * limit, limit=limit)

    @staticmethod
    def _parse(raw: Mapping[str, Any] | TaskSubmission) -> TaskSubmission:
        if isinstance(raw, TaskSubmission):
            return raw
        try:
            return TaskSubmission.model_validate(dict(raw))
        except ValidationError as exc:
            raise InvalidTaskError(format_validation_error(exc)) from exc
