from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.container import AppContainer
from app.api.deps import get_task_service
from app.core.config import Settings
from app.main import create_app
from tests.fakes import FailingQuotaStore, FakeClock
from tests.unit.conftest import jakarta


def make_settings(db_url: str, redis_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": db_url,
        "redis_url": redis_url,
        "scheduler_enabled": False,
        "seed_demo_data": False,
        "simulated_latency_seconds": 0,
        **overrides,
    }
    return Settings(_env_file=None, **values)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(jakarta(8))


@pytest.fixture
async def app(
    engine: AsyncEngine,
    redis_client: Redis,
    test_database_url: str,
    test_redis_url: str,
    clock: FakeClock,
) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(test_database_url, test_redis_url), clock=clock)
    async with app.router.lifespan_context(app):
        yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def register(client: AsyncClient, username: str = "alice", quota: int = 3) -> None:
    response = await client.post("/api/v1/users", json={"username": username, "daily_quota": quota})
    assert response.status_code == 201, response.text


async def submit(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {
        "user": "alice",
        "time": "12:00",
        "action": "sync",
        "params": {"target": "/data/x"},
        **overrides,
    }
    response = await client.post("/api/v1/tasks", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def test_register_user_returns_envelope(client: AsyncClient) -> None:
    response = await client.post("/api/v1/users", json={"username": "alice", "daily_quota": 3})

    body = response.json()
    assert response.status_code == 201
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["username"] == "alice"
    assert body["data"]["daily_quota"] == 3


async def test_duplicate_user_returns_409(client: AsyncClient) -> None:
    await register(client)

    response = await client.post("/api/v1/users", json={"username": "alice", "daily_quota": 3})

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {
            "code": "USER_ALREADY_EXISTS",
            "message": "User 'alice' already exists",
            "error_id": None,
        },
        "meta": None,
    }


async def test_unknown_user_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/carol")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.parametrize(
    "body",
    [
        {"username": "Alice!", "daily_quota": 3},
        {"username": "alice", "daily_quota": -1},
        {"username": "alice"},
    ],
)
async def test_invalid_user_body_returns_422(client: AsyncClient, body: dict[str, Any]) -> None:
    response = await client.post("/api/v1/users", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_submit_task_with_bad_params_returns_422(client: AsyncClient) -> None:
    await register(client)

    response = await client.post(
        "/api/v1/tasks",
        json={"user": "alice", "time": "12:00", "action": "sync", "params": {"path": "/x"}},
    )

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "INVALID_TASK_PARAMS"
    assert "target: Field required" in error["message"]


async def test_submit_task_for_unknown_action_returns_422(client: AsyncClient) -> None:
    await register(client)

    response = await client.post(
        "/api/v1/tasks", json={"user": "alice", "time": "12:00", "action": "archive"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == (
        "Unknown action 'archive'. Available: backup, delete, sync"
    )


async def test_submit_task_returns_schedule_in_local_time(client: AsyncClient) -> None:
    await register(client)

    task = await submit(client)

    assert task["user"] == "alice"
    assert task["time"] == "12:00"
    assert task["next_run_at"] == "2026-09-24T12:00:00+07:00"


async def test_actions_lists_param_schemas(client: AsyncClient) -> None:
    response = await client.get("/api/v1/actions")

    actions = response.json()["data"]
    assert [a["name"] for a in actions] == ["backup", "delete", "sync"]
    assert actions[0]["params_schema"]["required"] == ["target"]


async def test_full_flow_register_submit_tick_executions(
    client: AsyncClient, clock: FakeClock
) -> None:
    await register(client)
    for target in ("/a", "/b", "/c", "/d"):
        await submit(client, params={"target": target})
    clock.set(jakarta(12))

    tick = (await client.post("/api/v1/scheduler/tick")).json()["data"]
    executions = await client.get("/api/v1/executions", params={"user": "alice"})
    user = (await client.get("/api/v1/users/alice")).json()["data"]

    statuses = sorted(r["status"] for r in tick["results"])
    assert statuses == ["QUOTA_EXCEEDED", "SUCCESS", "SUCCESS", "SUCCESS"]
    assert executions.json()["meta"] == {"total": 4, "page": 1, "limit": 20}
    assert user["usage_today"] == {"date": "2026-09-24", "used": 3, "limit": 3}


async def test_executions_filter_by_status(client: AsyncClient, clock: FakeClock) -> None:
    await register(client, quota=1)
    await submit(client, params={"target": "/a"})
    await submit(client, params={"target": "/b"})
    clock.set(jakarta(12))
    await client.post("/api/v1/scheduler/tick")

    response = await client.get("/api/v1/executions", params={"status": "QUOTA_EXCEEDED"})

    assert response.json()["meta"]["total"] == 1
    assert response.json()["data"][0]["message"] == "Quota exceeded (1/1 today)"


async def test_task_list_paginates(client: AsyncClient, clock: FakeClock) -> None:
    await register(client)
    for target in ("/a", "/b", "/c"):
        await submit(client, params={"target": target})
        clock.advance(minutes=1)

    response = await client.get("/api/v1/tasks", params={"user": "alice", "page": 2, "limit": 2})

    body = response.json()
    assert body["meta"] == {"total": 3, "page": 2, "limit": 2}
    assert [t["params"]["target"] for t in body["data"]] == ["/c"]


async def test_limit_above_maximum_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks", params={"limit": 101})

    assert response.status_code == 422


async def test_unknown_route_uses_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


async def test_unexpected_error_returns_500_with_error_id(
    app: FastAPI, client: AsyncClient
) -> None:
    class BrokenService:
        async def list_tasks(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("secret connection string leaked?")

    app.dependency_overrides[get_task_service] = BrokenService

    response = await client.get("/api/v1/tasks")

    error = response.json()["error"]
    assert response.status_code == 500
    assert error["code"] == "INTERNAL_ERROR"
    assert error["message"] == "An unexpected error occurred"
    assert len(error["error_id"]) == 12
    assert "secret" not in response.text


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {"postgres": "ok", "redis": "ok"},
    }


async def test_health_reports_redis_down(app: FastAPI, client: AsyncClient) -> None:
    container: AppContainer = app.state.container
    container.quota = FailingQuotaStore()

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["components"] == {"postgres": "ok", "redis": "unavailable"}
