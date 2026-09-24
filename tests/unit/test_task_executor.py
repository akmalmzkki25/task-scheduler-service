import asyncio
import logging
from datetime import date, time
from typing import Any
from uuid import uuid4

import pytest

from app.domain.models import ClaimedTask, ExecutionStatus, Task, User
from app.services.task_executor import TaskExecutor
from app.strategies.base import ActionStrategy, TargetParams
from app.strategies.registry import StrategyRegistry, build_default_registry
from tests.fakes import FailingQuotaStore, FakeClock, InMemoryQuotaStore
from tests.unit.conftest import jakarta

TODAY = date(2026, 9, 24)
ALICE = User(username="alice", daily_quota=3, created_at=jakarta(8))


class ExplodingStrategy(ActionStrategy[TargetParams]):
    name = "explode"
    description = "Always fails."
    params_model = TargetParams

    def describe(self, params: TargetParams) -> str:
        raise RuntimeError("disk on fire")


class SlowStrategy(ActionStrategy[TargetParams]):
    name = "slow"
    description = "Takes too long."
    params_model = TargetParams

    def describe(self, params: TargetParams) -> str:
        return "never reached"


class SpyStrategy(ActionStrategy[TargetParams]):
    name = "spy"
    description = "Records calls."
    params_model = TargetParams

    def __init__(self) -> None:
        super().__init__(simulated_latency=0)
        self.calls = 0

    def describe(self, params: TargetParams) -> str:
        self.calls += 1
        return "spied"


@pytest.fixture
def full_registry() -> StrategyRegistry:
    registry = build_default_registry(simulated_latency=0)
    registry.register(ExplodingStrategy(0))
    registry.register(SlowStrategy(simulated_latency=1))
    return registry


def claimed(action: str = "sync", params: dict[str, Any] | None = None) -> ClaimedTask:
    task = Task(
        id=uuid4(),
        username="alice",
        run_at=time(12, 0),
        action=action,
        params=params if params is not None else {"target": "/data/x"},
        next_run_at=jakarta(12, day=25),
        created_at=jakarta(8),
    )
    return ClaimedTask(task=task, scheduled_for=jakarta(12))


def make_executor(
    registry: StrategyRegistry, quota: InMemoryQuotaStore, timeout: float = 5
) -> TaskExecutor:
    return TaskExecutor(
        registry=registry, quota=quota, clock=FakeClock(jakarta(12)), timeout_seconds=timeout
    )


async def run(executor: TaskExecutor, item: ClaimedTask, user: User | None = ALICE) -> Any:
    return await executor.execute(item, user, now=jakarta(12), tick_id="tick1")


async def test_success_consumes_one_quota(
    full_registry: StrategyRegistry, quota: InMemoryQuotaStore
) -> None:
    item = claimed()

    result = await run(make_executor(full_registry, quota), item)

    assert result.status is ExecutionStatus.SUCCESS
    assert result.message == "[SIMULATED] sync /data/x"
    assert result.task_id == item.task.id
    assert result.tick_id == "tick1"
    assert result.scheduled_for == jakarta(12)
    assert result.duration_ms >= 0
    assert await quota.get_usage("alice", TODAY) == 1


async def test_missing_user_fails_without_using_quota(
    full_registry: StrategyRegistry, quota: InMemoryQuotaStore
) -> None:
    result = await run(make_executor(full_registry, quota), claimed(), user=None)

    assert result.status is ExecutionStatus.FAILED
    assert result.message == "User 'alice' not found"
    assert await quota.get_usage("alice", TODAY) == 0


@pytest.mark.parametrize(
    ("item", "fragment"),
    [
        (claimed(action="archive"), "Unknown action 'archive'"),
        (claimed(params={}), "Invalid params for action 'sync'"),
    ],
)
async def test_config_errors_fail_without_using_quota(
    full_registry: StrategyRegistry, quota: InMemoryQuotaStore, item: ClaimedTask, fragment: str
) -> None:
    result = await run(make_executor(full_registry, quota), item)

    assert result.status is ExecutionStatus.FAILED
    assert fragment in result.message
    assert await quota.get_usage("alice", TODAY) == 0


async def test_quota_exceeded_skips_task(
    full_registry: StrategyRegistry,
    quota: InMemoryQuotaStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    quota.usage[("alice", TODAY)] = 3

    with caplog.at_level(logging.WARNING, logger="app.executor"):
        result = await run(make_executor(full_registry, quota), claimed())

    assert result.status is ExecutionStatus.QUOTA_EXCEEDED
    assert result.message == "Quota exceeded (3/3 today)"
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_quota_store_down_fails_closed() -> None:
    spy = SpyStrategy()
    registry = StrategyRegistry()
    registry.register(spy)

    result = await run(make_executor(registry, FailingQuotaStore()), claimed(action="spy"))

    assert result.status is ExecutionStatus.FAILED
    assert result.message == "Quota service unavailable"
    assert spy.calls == 0


async def test_strategy_exception_fails_but_keeps_quota_consumed(
    full_registry: StrategyRegistry,
    quota: InMemoryQuotaStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.executor"):
        result = await run(make_executor(full_registry, quota), claimed(action="explode"))

    assert result.status is ExecutionStatus.FAILED
    assert result.message == "explode failed: disk on fire"
    assert await quota.get_usage("alice", TODAY) == 1
    assert caplog.records[-1].exc_info is not None


async def test_slow_strategy_times_out(
    full_registry: StrategyRegistry, quota: InMemoryQuotaStore
) -> None:
    executor = make_executor(full_registry, quota, timeout=0.01)

    result = await run(executor, claimed(action="slow"))

    assert result.status is ExecutionStatus.FAILED
    assert result.message == "slow timed out after 0.01s"


async def test_log_context_is_reset_after_execute(
    full_registry: StrategyRegistry, quota: InMemoryQuotaStore
) -> None:
    from app.core.logging import task_id_var, user_var

    await run(make_executor(full_registry, quota), claimed())

    assert (task_id_var.get(), user_var.get()) == ("-", "-")


async def test_concurrent_executions_respect_quota(
    full_registry: StrategyRegistry, quota: InMemoryQuotaStore
) -> None:
    executor = make_executor(full_registry, quota)

    results = await asyncio.gather(*(run(executor, claimed()) for _ in range(5)))

    statuses = sorted(r.status for r in results)
    assert statuses.count(ExecutionStatus.SUCCESS) == 3
    assert statuses.count(ExecutionStatus.QUOTA_EXCEEDED) == 2
