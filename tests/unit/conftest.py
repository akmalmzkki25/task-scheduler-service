from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.strategies.registry import StrategyRegistry, build_default_registry
from tests.fakes import (
    FakeClock,
    InMemoryExecutionRepository,
    InMemoryQuotaStore,
    InMemoryTaskRepository,
    InMemoryUserRepository,
)

JAKARTA = ZoneInfo("Asia/Jakarta")


def jakarta(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=JAKARTA)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(jakarta(8))


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def tasks() -> InMemoryTaskRepository:
    return InMemoryTaskRepository()


@pytest.fixture
def executions() -> InMemoryExecutionRepository:
    return InMemoryExecutionRepository()


@pytest.fixture
def quota() -> InMemoryQuotaStore:
    return InMemoryQuotaStore()


@pytest.fixture
def registry() -> StrategyRegistry:
    return build_default_registry(simulated_latency=0)


@pytest.fixture
def user_service(
    users: InMemoryUserRepository, quota: InMemoryQuotaStore, clock: FakeClock
) -> UserService:
    return UserService(users=users, quota=quota, clock=clock)


@pytest.fixture
def task_service(
    users: InMemoryUserRepository,
    tasks: InMemoryTaskRepository,
    registry: StrategyRegistry,
    clock: FakeClock,
) -> TaskService:
    return TaskService(users=users, tasks=tasks, registry=registry, clock=clock, tz=JAKARTA)
