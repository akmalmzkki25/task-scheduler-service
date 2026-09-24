"""Daily quota counters in Redis.

The check and the increment run inside one Lua script, which Redis executes atomically.
That keeps the limit exact even with many concurrent executions or several app
instances, without any lock in Python.
"""

from datetime import date
from typing import cast

from redis.asyncio import Redis

from app.domain.models import QuotaDecision

KEY_PREFIX = "task_scheduler:quota"
DEFAULT_TTL_SECONDS = 2 * 24 * 60 * 60

# Returns {allowed (0/1), used}. The key only gets created on a successful consume, so a
# user with no quota never leaves an empty counter behind.
CONSUME_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current >= limit then
  return {0, current}
end
current = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return {1, current}
"""


def quota_key(username: str, day: date) -> str:
    return f"{KEY_PREFIX}:{username}:{day.isoformat()}"


class RedisQuotaStore:
    def __init__(self, client: Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._consume = client.register_script(CONSUME_SCRIPT)

    async def try_consume(self, username: str, day: date, limit: int) -> QuotaDecision:
        allowed, used = cast(
            list[int],
            await self._consume(keys=[quota_key(username, day)], args=[limit, self._ttl]),
        )
        return QuotaDecision(allowed=bool(allowed), used=int(used), limit=limit)

    async def get_usage(self, username: str, day: date) -> int:
        value = await self._client.get(quota_key(username, day))
        return int(value) if value is not None else 0

    async def ping(self) -> None:
        await self._client.ping()
