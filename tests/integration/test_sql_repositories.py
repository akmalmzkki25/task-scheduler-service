import asyncio
from datetime import datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import UserAlreadyExistsError
from app.domain.models import ExecutionResult, ExecutionStatus, Task, User
from app.repositories.execution_repository import SqlExecutionRepository
from app.repositories.task_repository import SqlTaskRepository
from app.repositories.user_repository import SqlUserRepository

JAKARTA = ZoneInfo("Asia/Jakarta")


def jakarta(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=JAKARTA)


def make_task(
    username: str,
    next_run_at: datetime,
    target: str = "/data/x",
    created_at: datetime | None = None,
) -> Task:
    return Task(
        id=uuid4(),
        username=username,
        run_at=time(12, 0),
        action="sync",
        params={"target": target},
        next_run_at=next_run_at,
        created_at=created_at or jakarta(8),
    )


def make_result(task: Task, status: ExecutionStatus, started_at: datetime) -> ExecutionResult:
    return ExecutionResult(
        id=uuid4(),
        task_id=task.id,
        username=task.username,
        action=task.action,
        status=status,
        message="ok",
        tick_id="tick1",
        scheduled_for=task.next_run_at,
        started_at=started_at,
        duration_ms=3,
    )


@pytest.fixture
def user_repo(session_factory: async_sessionmaker[AsyncSession]) -> SqlUserRepository:
    return SqlUserRepository(session_factory)


@pytest.fixture
def task_repo(session_factory: async_sessionmaker[AsyncSession]) -> SqlTaskRepository:
    return SqlTaskRepository(session_factory)


@pytest.fixture
def execution_repo(session_factory: async_sessionmaker[AsyncSession]) -> SqlExecutionRepository:
    return SqlExecutionRepository(session_factory)


@pytest.fixture
async def alice(user_repo: SqlUserRepository) -> User:
    user = User(username="alice", daily_quota=3, created_at=jakarta(8))
    await user_repo.add(user)
    return user


async def test_user_round_trip(user_repo: SqlUserRepository, alice: User) -> None:
    await user_repo.add(User(username="bob", daily_quota=5, created_at=jakarta(8)))

    assert await user_repo.get("alice") == alice
    assert await user_repo.get("carol") is None
    assert set(await user_repo.get_many(["alice", "bob", "carol"])) == {"alice", "bob"}
    assert await user_repo.get_many([]) == {}


async def test_duplicate_user_raises_domain_error(
    user_repo: SqlUserRepository, alice: User
) -> None:
    with pytest.raises(UserAlreadyExistsError):
        await user_repo.add(alice)


async def test_task_list_paginates_with_total(task_repo: SqlTaskRepository, alice: User) -> None:
    for i in range(3):
        await task_repo.add(
            make_task("alice", jakarta(12), target=f"/t{i}", created_at=jakarta(8, i))
        )

    page, total = await task_repo.list_page("alice", offset=2, limit=2)
    _, nobody = await task_repo.list_page("bob", offset=0, limit=10)

    assert total == 3
    assert len(page) == 1
    assert [t.params["target"] for t in page] == ["/t2"]
    assert nobody == 0


async def test_claim_due_takes_only_due_tasks_and_moves_them(
    task_repo: SqlTaskRepository, alice: User
) -> None:
    due = make_task("alice", jakarta(12))
    later = make_task("alice", jakarta(12, day=25))
    await task_repo.add(due)
    await task_repo.add(later)

    claimed = await task_repo.claim_due(jakarta(12, 3), JAKARTA, limit=100)
    again = await task_repo.claim_due(jakarta(12, 4), JAKARTA, limit=100)

    assert [c.task.id for c in claimed] == [due.id]
    assert claimed[0].scheduled_for == jakarta(12)
    assert claimed[0].task.next_run_at == jakarta(12, day=25)
    assert again == []


async def test_concurrent_claims_never_overlap(task_repo: SqlTaskRepository, alice: User) -> None:
    tasks = [make_task("alice", jakarta(12), target=f"/t{i}") for i in range(20)]
    for task in tasks:
        await task_repo.add(task)

    batches = await asyncio.gather(
        *(task_repo.claim_due(jakarta(12, 1), JAKARTA, limit=100) for _ in range(4))
    )

    claimed_ids = [c.task.id for batch in batches for c in batch]
    assert len(claimed_ids) == len(set(claimed_ids)) == 20


async def test_executions_filter_and_order_newest_first(
    task_repo: SqlTaskRepository,
    execution_repo: SqlExecutionRepository,
    user_repo: SqlUserRepository,
    alice: User,
) -> None:
    await user_repo.add(User(username="bob", daily_quota=5, created_at=jakarta(8)))
    task_a = make_task("alice", jakarta(12))
    task_b = make_task("bob", jakarta(12))
    await task_repo.add(task_a)
    await task_repo.add(task_b)
    first = make_result(task_a, ExecutionStatus.SUCCESS, jakarta(12))
    second = make_result(task_a, ExecutionStatus.QUOTA_EXCEEDED, jakarta(12, 1))
    other = make_result(task_b, ExecutionStatus.SUCCESS, jakarta(12, 2))
    await execution_repo.add_many([first, second, other])
    await execution_repo.add_many([])

    alice_rows, alice_total = await execution_repo.list_page("alice", None, 0, 10)
    exceeded, _ = await execution_repo.list_page(None, ExecutionStatus.QUOTA_EXCEEDED, 0, 10)

    assert alice_total == 2
    assert [r.id for r in alice_rows] == [second.id, first.id]
    assert alice_rows[0] == second
    assert [r.id for r in exceeded] == [second.id]
