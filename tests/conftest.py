"""Fixtures backed by the real Postgres and Redis containers.

Only the dedicated test database and Redis db index are touched. Tables are truncated
before each test, and Redis cleanup deletes `task_scheduler:*` keys only, because the
Redis server is shared with other projects.
"""

from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory

KEY_PREFIX = "task_scheduler:"


def _test_urls() -> tuple[str, str]:
    settings = get_settings()
    if not settings.test_database_url or not settings.test_redis_url:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL must be set for integration tests")
    return settings.test_database_url, settings.test_redis_url


@pytest.fixture
def test_database_url() -> str:
    return _test_urls()[0]


@pytest.fixture
def test_redis_url() -> str:
    return _test_urls()[1]


@pytest.fixture
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(test_database_url, pooled=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE executions, tasks, users"))
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def delete_prefixed_keys(client: Redis) -> None:
    async for key in client.scan_iter(match=f"{KEY_PREFIX}*"):
        await client.delete(key)


@pytest.fixture
async def redis_client(test_redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(test_redis_url, decode_responses=True)
    await delete_prefixed_keys(client)
    yield client
    await delete_prefixed_keys(client)
    await client.aclose()
