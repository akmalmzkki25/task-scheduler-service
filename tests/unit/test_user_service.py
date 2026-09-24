from datetime import date

import pytest

from app.domain.errors import UserAlreadyExistsError, UserNotFoundError
from app.services.user_service import UserService
from tests.fakes import InMemoryQuotaStore
from tests.unit.conftest import jakarta


async def test_register_then_get_returns_user(user_service: UserService) -> None:
    created = await user_service.register("alice", daily_quota=3)

    fetched = await user_service.get("alice")

    assert fetched == created
    assert fetched.daily_quota == 3
    assert fetched.created_at == jakarta(8)


async def test_register_duplicate_raises(user_service: UserService) -> None:
    await user_service.register("alice", daily_quota=3)

    with pytest.raises(UserAlreadyExistsError):
        await user_service.register("alice", daily_quota=5)


async def test_get_unknown_user_raises(user_service: UserService) -> None:
    with pytest.raises(UserNotFoundError, match="User 'carol' not found"):
        await user_service.get("carol")


async def test_usage_today_reads_quota_store(
    user_service: UserService, quota: InMemoryQuotaStore
) -> None:
    await user_service.register("alice", daily_quota=3)
    quota.usage[("alice", date(2026, 9, 24))] = 2
    quota.usage[("alice", date(2026, 9, 23))] = 3

    user, used, day = await user_service.get_usage_today("alice")

    assert (user.username, used, day) == ("alice", 2, date(2026, 9, 24))
