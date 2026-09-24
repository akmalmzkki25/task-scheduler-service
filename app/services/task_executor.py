"""Runs one claimed task and always returns an ExecutionResult.

Order matters: configuration problems (missing user, unknown action, bad params) are
caught before any quota is used, and quota is used before the strategy starts. The
executor never raises, so one bad task can't break the others in the same tick.

It also never touches the database. Executions run concurrently under
`asyncio.gather`, and an AsyncSession isn't safe to share across them.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from redis.exceptions import RedisError

from app.core.clock import Clock
from app.core.logging import task_id_var, user_var
from app.domain.errors import DomainError
from app.domain.models import ClaimedTask, ExecutionResult, ExecutionStatus, User
from app.repositories.interfaces import QuotaStore
from app.strategies.base import ActionStrategy
from app.strategies.registry import StrategyRegistry

logger = logging.getLogger("app.executor")


@dataclass(frozen=True)
class _Outcome:
    status: ExecutionStatus
    message: str


class TaskExecutor:
    def __init__(
        self,
        registry: StrategyRegistry,
        quota: QuotaStore,
        clock: Clock,
        timeout_seconds: float,
    ) -> None:
        self._registry = registry
        self._quota = quota
        self._clock = clock
        self._timeout = timeout_seconds

    async def execute(
        self, claimed: ClaimedTask, user: User | None, now: datetime, tick_id: str
    ) -> ExecutionResult:
        task = claimed.task
        tokens = (task_id_var.set(str(task.id)[:8]), user_var.set(task.username))
        started_at = self._clock.now()
        started = time.perf_counter()
        try:
            outcome = await self._run(claimed, user, now)
        finally:
            task_id_var.reset(tokens[0])
            user_var.reset(tokens[1])

        return ExecutionResult(
            id=uuid4(),
            task_id=task.id,
            username=task.username,
            action=task.action,
            status=outcome.status,
            message=outcome.message,
            tick_id=tick_id,
            scheduled_for=claimed.scheduled_for,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def _run(self, claimed: ClaimedTask, user: User | None, now: datetime) -> _Outcome:
        task = claimed.task
        if user is None:
            logger.error("User '%s' not found, task skipped", task.username)
            return _Outcome(ExecutionStatus.FAILED, f"User '{task.username}' not found")
        try:
            strategy = self._registry.get(task.action)
            params = strategy.parse_params(task.params)
        except DomainError as exc:
            logger.error("Task misconfigured: %s", exc.message)
            return _Outcome(ExecutionStatus.FAILED, exc.message)

        try:
            decision = await self._quota.try_consume(task.username, now.date(), user.daily_quota)
        except RedisError:
            logger.exception("Quota service unavailable, task not run")
            return _Outcome(ExecutionStatus.FAILED, "Quota service unavailable")
        if not decision.allowed:
            message = f"Quota exceeded ({decision.used}/{decision.limit} today)"
            logger.warning("%s, task skipped", message)
            return _Outcome(ExecutionStatus.QUOTA_EXCEEDED, message)

        return await self._run_strategy(strategy, params, task.action)

    async def _run_strategy(
        self, strategy: ActionStrategy[Any], params: BaseModel, action: str
    ) -> _Outcome:
        logger.info("Running %s %s", action, params.model_dump_json())
        try:
            message = await asyncio.wait_for(strategy.execute(params), timeout=self._timeout)
        except TimeoutError:
            message = f"{action} timed out after {self._timeout:g}s"
            logger.error(message)
            return _Outcome(ExecutionStatus.FAILED, message)
        except Exception as exc:
            logger.exception("%s failed", action)
            return _Outcome(ExecutionStatus.FAILED, f"{action} failed: {exc}")
        logger.info("%s succeeded", action)
        return _Outcome(ExecutionStatus.SUCCESS, message)
