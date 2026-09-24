"""Builds every long-lived object once and owns their lifecycle.

Routes never construct services themselves; they receive them from `deps.py`, which
reads this container from `app.state`.
"""

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.db.session import create_engine, create_session_factory
from app.repositories.execution_repository import SqlExecutionRepository
from app.repositories.interfaces import ExecutionRepository, QuotaStore
from app.repositories.quota_store import RedisQuotaStore
from app.repositories.task_repository import SqlTaskRepository
from app.repositories.user_repository import SqlUserRepository
from app.services.scheduler import Scheduler, SchedulerRunner
from app.services.task_executor import TaskExecutor
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.strategies.registry import StrategyRegistry, build_default_registry


@dataclass
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    redis: Redis
    quota: QuotaStore
    registry: StrategyRegistry
    executions: ExecutionRepository
    user_service: UserService
    task_service: TaskService
    scheduler: Scheduler
    runner: SchedulerRunner

    @classmethod
    def build(cls, settings: Settings, clock: Clock | None = None) -> "AppContainer":
        clock = clock or SystemClock(settings.tz)
        engine = create_engine(settings.database_url)
        sessions = create_session_factory(engine)
        redis = Redis.from_url(settings.redis_url, decode_responses=True)

        users = SqlUserRepository(sessions)
        tasks = SqlTaskRepository(sessions)
        executions = SqlExecutionRepository(sessions)
        quota = RedisQuotaStore(redis)
        registry = build_default_registry(settings.simulated_latency_seconds)

        executor = TaskExecutor(
            registry=registry,
            quota=quota,
            clock=clock,
            timeout_seconds=settings.task_timeout_seconds,
        )
        scheduler = Scheduler(
            tasks=tasks,
            users=users,
            executions=executions,
            executor=executor,
            clock=clock,
            tz=settings.tz,
            claim_batch_size=settings.claim_batch_size,
        )
        return cls(
            settings=settings,
            engine=engine,
            redis=redis,
            quota=quota,
            registry=registry,
            executions=executions,
            user_service=UserService(users=users, quota=quota, clock=clock),
            task_service=TaskService(
                users=users, tasks=tasks, registry=registry, clock=clock, tz=settings.tz
            ),
            scheduler=scheduler,
            runner=SchedulerRunner(scheduler, settings.tick_interval_seconds),
        )

    async def aclose(self) -> None:
        await self.runner.stop()
        await self.redis.aclose()
        await self.engine.dispose()
