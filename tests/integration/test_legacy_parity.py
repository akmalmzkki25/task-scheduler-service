"""The refactored service must reproduce what the legacy script did at 12:00."""

from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import create_app
from tests.fakes import FakeClock
from tests.integration.test_api import make_settings
from tests.unit.conftest import jakarta

# What the legacy run() printed for its three tasks at 12:00.
LEGACY_OUTPUT = {
    ("alice", "[SIMULATED] sync /data/x"),
    ("bob", "[SIMULATED] backup /srv/y -> <default>"),
    ("alice", "[SIMULATED] delete /tmp/z"),
}


async def test_seeded_legacy_tasks_match_legacy_output(
    engine: AsyncEngine, redis_client: Redis, test_database_url: str, test_redis_url: str
) -> None:
    clock = FakeClock(jakarta(8))
    settings = make_settings(test_database_url, test_redis_url, seed_demo_data=True)
    app = create_app(settings, clock=clock)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            clock.set(jakarta(12))
            tick = (await client.post("/api/v1/scheduler/tick")).json()["data"]

    assert {(r["user"], r["message"]) for r in tick["results"]} == LEGACY_OUTPUT
    assert {r["status"] for r in tick["results"]} == {"SUCCESS"}


async def test_seeding_twice_does_not_duplicate(
    engine: AsyncEngine, redis_client: Redis, test_database_url: str, test_redis_url: str
) -> None:
    settings = make_settings(test_database_url, test_redis_url, seed_demo_data=True)

    for _ in range(2):
        app = create_app(settings, clock=FakeClock(jakarta(8)))
        async with app.router.lifespan_context(app):
            pass

    app = create_app(settings, clock=FakeClock(jakarta(8)))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tasks = (await client.get("/api/v1/tasks")).json()

    assert tasks["meta"]["total"] == 3
