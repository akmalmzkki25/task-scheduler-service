import asyncio
from datetime import date

from redis.asyncio import Redis

from app.repositories.quota_store import RedisQuotaStore, quota_key

TODAY = date(2026, 9, 24)
TOMORROW = date(2026, 9, 25)


def test_quota_key_is_prefixed_per_user_and_day() -> None:
    assert quota_key("alice", TODAY) == "task_scheduler:quota:alice:2026-09-24"


async def test_first_consume_is_allowed(redis_client: Redis) -> None:
    store = RedisQuotaStore(redis_client)

    decision = await store.try_consume("alice", TODAY, limit=3)

    assert (decision.allowed, decision.used, decision.limit) == (True, 1, 3)
    assert await store.get_usage("alice", TODAY) == 1


async def test_zero_quota_never_allows(redis_client: Redis) -> None:
    store = RedisQuotaStore(redis_client)

    decision = await store.try_consume("alice", TODAY, limit=0)

    assert (decision.allowed, decision.used) == (False, 0)
    assert await redis_client.exists(quota_key("alice", TODAY)) == 0


async def test_concurrent_consumes_never_exceed_limit(redis_client: Redis) -> None:
    store = RedisQuotaStore(redis_client)

    decisions = await asyncio.gather(
        *(store.try_consume("alice", TODAY, limit=3) for _ in range(10))
    )

    assert sum(d.allowed for d in decisions) == 3
    assert await store.get_usage("alice", TODAY) == 3


async def test_counter_expires(redis_client: Redis) -> None:
    store = RedisQuotaStore(redis_client, ttl_seconds=172800)

    await store.try_consume("alice", TODAY, limit=3)

    assert 0 < await redis_client.ttl(quota_key("alice", TODAY)) <= 172800


async def test_new_day_starts_from_zero(redis_client: Redis) -> None:
    store = RedisQuotaStore(redis_client)
    for _ in range(3):
        await store.try_consume("alice", TODAY, limit=3)

    decision = await store.try_consume("alice", TOMORROW, limit=3)

    assert (decision.allowed, decision.used) == (True, 1)


async def test_usage_of_unknown_user_is_zero(redis_client: Redis) -> None:
    assert await RedisQuotaStore(redis_client).get_usage("nobody", TODAY) == 0


async def test_ping_succeeds(redis_client: Redis) -> None:
    await RedisQuotaStore(redis_client).ping()
