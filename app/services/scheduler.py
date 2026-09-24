"""Tick-based scheduler.

One tick claims every due task, runs them concurrently, and stores the results.
`SchedulerRunner` calls `tick()` on an interval in the background; the API can also
trigger a tick directly. Claiming is atomic in the repository, so overlapping ticks
never run the same task twice.
"""

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.clock import Clock
from app.core.logging import tick_id_var
from app.domain.models import ExecutionResult, ExecutionStatus
from app.repositories.interfaces import ExecutionRepository, TaskRepository, UserRepository
from app.services.task_executor import TaskExecutor

logger = logging.getLogger("app.scheduler")


@dataclass(frozen=True)
class TickReport:
    tick_id: str
    started_at: datetime
    results: list[ExecutionResult]


class Scheduler:
    def __init__(
        self,
        tasks: TaskRepository,
        users: UserRepository,
        executions: ExecutionRepository,
        executor: TaskExecutor,
        clock: Clock,
        tz: ZoneInfo,
        claim_batch_size: int,
    ) -> None:
        self._tasks = tasks
        self._users = users
        self._executions = executions
        self._executor = executor
        self._clock = clock
        self._tz = tz
        self._batch_size = claim_batch_size

    async def tick(self) -> TickReport:
        tick_id = uuid4().hex[:8]
        token = tick_id_var.set(tick_id)
        try:
            return await self._tick(tick_id)
        finally:
            tick_id_var.reset(token)

    async def _tick(self, tick_id: str) -> TickReport:
        now = self._clock.now()
        claimed = await self._tasks.claim_due(now, self._tz, self._batch_size)
        if not claimed:
            logger.debug("No tasks due")
            return TickReport(tick_id=tick_id, started_at=now, results=[])

        logger.info("%d tasks due", len(claimed))
        # Load every owner in one query; executors run concurrently and stay DB-free.
        users = await self._users.get_many({c.task.username for c in claimed})
        results = list(
            await asyncio.gather(
                *(
                    self._executor.execute(c, users.get(c.task.username), now, tick_id)
                    for c in claimed
                )
            )
        )
        await self._executions.add_many(results)

        counts = Counter(r.status for r in results)
        logger.info(
            "Tick finished: %d due, %d success, %d failed, %d quota exceeded",
            len(results),
            counts[ExecutionStatus.SUCCESS],
            counts[ExecutionStatus.FAILED],
            counts[ExecutionStatus.QUOTA_EXCEEDED],
        )
        return TickReport(tick_id=tick_id, started_at=now, results=results)


class Tickable(Protocol):
    async def tick(self) -> object: ...


class SchedulerRunner:
    """Calls `scheduler.tick()` every `interval_seconds` until stopped."""

    def __init__(self, scheduler: Tickable, interval_seconds: float) -> None:
        self._scheduler = scheduler
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError("Scheduler runner is already running")
        self._task = asyncio.create_task(self._loop(), name="scheduler-runner")
        logger.info("Scheduler runner started, interval %gs", self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Scheduler runner stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._scheduler.tick()
            except Exception:
                # A failed tick (for example, the database dropping) must not kill the
                # loop; the next tick retries.
                logger.exception("Tick failed, retrying in %gs", self._interval)
            await asyncio.sleep(self._interval)
