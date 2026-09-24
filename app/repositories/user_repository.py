from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import UserAlreadyExistsError
from app.domain.models import User
from app.models.user import UserRecord

UNIQUE_VIOLATION = "23505"


def _to_domain(row: UserRecord) -> User:
    return User(username=row.username, daily_quota=row.daily_quota, created_at=row.created_at)


class SqlUserRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def add(self, user: User) -> None:
        record = UserRecord(
            username=user.username, daily_quota=user.daily_quota, created_at=user.created_at
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(record)
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise UserAlreadyExistsError(user.username) from exc
            raise

    async def get(self, username: str) -> User | None:
        async with self._sessions() as session:
            row = await session.get(UserRecord, username)
            return None if row is None else _to_domain(row)

    async def get_many(self, usernames: Collection[str]) -> dict[str, User]:
        if not usernames:
            return {}
        async with self._sessions() as session:
            rows = await session.scalars(
                select(UserRecord).where(UserRecord.username.in_(list(usernames)))
            )
            return {row.username: _to_domain(row) for row in rows}
