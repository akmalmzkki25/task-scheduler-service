from typing import Any

import pytest

from app.domain.errors import (
    InvalidTaskError,
    InvalidTaskParamsError,
    UnknownActionError,
    UserNotFoundError,
)
from app.services.task_service import TaskService
from app.services.user_service import UserService
from tests.fakes import FakeClock
from tests.unit.conftest import jakarta


def submission(**overrides: Any) -> dict[str, Any]:
    return {
        "user": "alice",
        "time": "12:00",
        "action": "sync",
        "params": {"target": "/data/x"},
        **overrides,
    }


@pytest.fixture(autouse=True)
async def alice(user_service: UserService) -> None:
    await user_service.register("alice", daily_quota=3)


async def test_submit_before_run_time_schedules_today(task_service: TaskService) -> None:
    task = await task_service.submit(submission())

    assert task.username == "alice"
    assert task.action == "sync"
    assert dict(task.params) == {"target": "/data/x"}
    assert task.next_run_at == jakarta(12)
    assert task.created_at == jakarta(8)


async def test_submit_after_run_time_schedules_tomorrow(
    task_service: TaskService, clock: FakeClock
) -> None:
    clock.set(jakarta(15))

    task = await task_service.submit(submission())

    assert task.next_run_at == jakarta(12, day=25)


async def test_submit_stores_validated_params_with_defaults(task_service: TaskService) -> None:
    task = await task_service.submit(submission(action="backup", params={"target": "/srv/y"}))

    assert dict(task.params) == {"target": "/srv/y", "destination": None}


async def test_user_can_own_many_tasks_at_same_time(task_service: TaskService) -> None:
    for target in ("/a", "/b", "/c"):
        await task_service.submit(submission(params={"target": target}))

    page, total = await task_service.list_tasks("alice", page=1, limit=10)

    assert total == 3
    assert [t.params["target"] for t in page] == ["/a", "/b", "/c"]


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"user": "carol"}, UserNotFoundError),
        ({"action": "archive"}, UnknownActionError),
        ({"params": {}}, InvalidTaskParamsError),
        ({"time": "25:00"}, InvalidTaskError),
        ({"time": "noon"}, InvalidTaskError),
        ({"priority": "high"}, InvalidTaskError),
    ],
)
async def test_submit_rejects_bad_input(
    task_service: TaskService, overrides: dict[str, Any], error: type[Exception]
) -> None:
    with pytest.raises(error):
        await task_service.submit(submission(**overrides))


async def test_list_tasks_paginates_and_filters(
    task_service: TaskService, user_service: UserService
) -> None:
    await user_service.register("bob", daily_quota=5)
    for target in ("/1", "/2", "/3"):
        await task_service.submit(submission(params={"target": target}))
    await task_service.submit(submission(user="bob"))

    page, total = await task_service.list_tasks("alice", page=2, limit=2)
    _, everyone = await task_service.list_tasks(None, page=1, limit=10)

    assert total == 3
    assert [t.params["target"] for t in page] == ["/3"]
    assert everyone == 4
