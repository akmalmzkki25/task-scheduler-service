"""The Alembic migration must build exactly the schema the ORM models describe."""

import asyncio

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app.db.base import Base


def alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


def schema_diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(connection)
    return list(compare_metadata(context, Base.metadata))


async def test_upgrade_head_matches_orm_metadata(
    engine: AsyncEngine, test_database_url: str
) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    config = alembic_config(test_database_url)

    try:
        # env.py calls asyncio.run, so it has to run outside this test's event loop.
        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.connect() as conn:
            diff = await conn.run_sync(schema_diff)
        assert diff == []
    finally:
        await asyncio.to_thread(command.downgrade, config, "base")
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
            await conn.run_sync(Base.metadata.create_all)
