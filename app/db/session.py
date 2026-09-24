from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine
from sqlalchemy.pool import NullPool


def create_engine(url: str, *, pooled: bool = True) -> AsyncEngine:
    """Create the async engine. Tests pass `pooled=False` so no connection outlives its loop."""
    if pooled:
        return _create_async_engine(url, pool_pre_ping=True)
    return _create_async_engine(url, poolclass=NullPool)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
