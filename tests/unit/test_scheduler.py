import asyncio
from collections import Counter

import pytest

from app.domain.models import ExecutionStatus
from app.services.scheduler import Scheduler, SchedulerRunner, TickReport
from app.services.task_executor import TaskExecutor
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.strategies.base import ActionStrategy, TargetParams
from app.strategies.registry import StrategyRegistry
from tests.fakes import (
    FakeClock,
    InMemoryExecutionRepository,
    InMemoryQuotaStore,
    InMemoryTaskRepository,
    InMemoryUserRepository,
)
from tests.unit.conftest import JAKARTA, jakarta


class BrokenStrategy(ActionStrategy[TargetParams]):
    name = "broken"
    description = "Always fails."
    params_model = TargetParams

    def describe(self, params: TargetParams) -> str:
        raise RuntimeError("boom")


@pytest.fixture
def scheduler(
    users: InMemoryUserRepository,
    tasks: InMemoryTaskRepository,
    executions: InMemoryExecutionRepository,
    quota: InMemoryQuotaStore,
    registry: StrategyRegistry,
    clock: FakeClock,
) -> Scheduler:
    registry.register(BrokenStrategy(0))
    executor = TaskExecutor(registry=registry, quota=quota, clock=clock, timeout_seconds=5)
    return Scheduler(
        tasks=tasks,
        users=users,
        executions=executions,
        executor=executor,
        clock=clock,
        tz=JAKARTA,
        claim_batch_size=100,
    )


@pytest.fixture(autouse=True)
async def legacy_data(user_service: UserService, task_service: TaskService) -> None:
    await user_service.register("alice", daily_quota=3)
    await user_service.register("bob", daily_quota=5)
    for task in (
        {"user": "alice", "time": "12:00", "action": "sync", "params": {"target": "/data/x"}},
        {"user": "bob", "time": "12:00", "action": "backup", "params": {"target": "/srv/y"}},
        {"user": "alice", "time": "12:00", "action": "delete", "params": {"target": "/tmp/z"}},
    ):
        await task_service.submit(task)


def statuses(report: TickReport) -> Counter[ExecutionStatus]:
    return Counter(r.status for r in report.results)


async def test_nothing_runs_before_scheduled_time(scheduler: Scheduler, clock: FakeClock) -> None:
    clock.set(jakarta(11, 59))

    report = await scheduler.tick()

    assert report.results == []


async def test_late_tick_catches_up(scheduler: Scheduler, clock: FakeClock) -> None:
    clock.set(jakarta(12, 3))

    report = await scheduler.tick()

    assert statuses(report) == {ExecutionStatus.SUCCESS: 3}
    assert sorted(r.message for r in report.results) == [
        "[SIMULATED] backup /srv/y -> <default>",
        "[SIMULATED] delete /tmp/z",
        "[SIMULATED] sync /data/x",
    ]


async def test_second_tick_same_day_runs_nothing(scheduler: Scheduler, clock: FakeClock) -> None:
    clock.set(jakarta(12))
    await scheduler.tick()
    clock.advance(seconds=30)

    report = await scheduler.tick()

    assert report.results == []


async def test_tasks_run_again_next_day_with_fresh_quota(
    scheduler: Scheduler, clock: FakeClock, quota: InMemoryQuotaStore
) -> None:
    clock.set(jakarta(12))
    await scheduler.tick()
    clock.advance(days=1)

    report = await scheduler.tick()

    assert statuses(report) == {ExecutionStatus.SUCCESS: 3}
    assert await quota.get_usage("alice", jakarta(12, day=25).date()) == 2


async def test_long_outage_runs_each_task_once(scheduler: Scheduler, clock: FakeClock) -> None:
    clock.set(jakarta(13, day=27))

    first = await scheduler.tick()
    second = await scheduler.tick()

    assert len(first.results) == 3
    assert second.results == []


async def test_quota_limits_alice_to_three_runs(
    scheduler: Scheduler, task_service: TaskService, clock: FakeClock
) -> None:
    for target in ("/data/a", "/data/b"):
        await task_service.submit(
            {"user": "alice", "time": "12:00", "action": "sync", "params": {"target": target}}
        )
    clock.set(jakarta(12))

    report = await scheduler.tick()

    alice = Counter(r.status for r in report.results if r.username == "alice")
    assert alice == {ExecutionStatus.SUCCESS: 3, ExecutionStatus.QUOTA_EXCEEDED: 1}


async def test_failing_task_does_not_affect_others(
    scheduler: Scheduler, task_service: TaskService, clock: FakeClock
) -> None:
    await task_service.submit(
        {"user": "bob", "time": "12:00", "action": "broken", "params": {"target": "/x"}}
    )
    clock.set(jakarta(12))

    report = await scheduler.tick()

    assert statuses(report) == {ExecutionStatus.SUCCESS: 3, ExecutionStatus.FAILED: 1}


async def test_results_are_saved_with_tick_id(
    scheduler: Scheduler, executions: InMemoryExecutionRepository, clock: FakeClock
) -> None:
    clock.set(jakarta(12))

    report = await scheduler.tick()

    assert len(executions.results) == 3
    assert {r.tick_id for r in executions.results} == {report.tick_id}
    assert report.started_at == jakarta(12)


async def test_runner_ticks_repeatedly_and_survives_errors() -> None:
    calls = 0

    class FlakyScheduler:
        async def tick(self) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("database went away")

    runner = SchedulerRunner(FlakyScheduler(), interval_seconds=0.01)
    runner.start()
    await asyncio.sleep(0.1)
    await runner.stop()

    assert calls >= 3
    assert runner.is_running is False


async def test_runner_start_twice_raises() -> None:
    class IdleScheduler:
        async def tick(self) -> None:
            return None

    runner = SchedulerRunner(IdleScheduler(), interval_seconds=10)
    runner.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            runner.start()
    finally:
        await runner.stop()
