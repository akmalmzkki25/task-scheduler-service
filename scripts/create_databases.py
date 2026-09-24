"""Create the app and test databases if they don't exist yet.

The Postgres server is shared with other projects, so this script only ever issues
`CREATE DATABASE` for the two names derived from DATABASE_URL and TEST_DATABASE_URL.
It never drops or alters anything.

Usage: .venv/Scripts/python scripts/create_databases.py
"""

import asyncio
import logging
import re

import asyncpg
from sqlalchemy.engine import make_url

from app.core.config import get_settings

logger = logging.getLogger("scripts.create_databases")
SAFE_DB_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


async def ensure_database(url: str) -> None:
    parsed = make_url(url)
    name = parsed.database
    if not name or not SAFE_DB_NAME.match(name):
        raise ValueError(f"Refusing to create database with unsafe name: {name!r}")

    conn = await asyncpg.connect(
        host=parsed.host,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if exists:
            logger.info("Database %s already exists", name)
            return
        # CREATE DATABASE can't take bind parameters; the name is validated above.
        await conn.execute(f'CREATE DATABASE "{name}"')
        logger.info("Created database %s", name)
    finally:
        await conn.close()


async def main() -> None:
    settings = get_settings()
    urls = [settings.database_url]
    if settings.test_database_url:
        urls.append(settings.test_database_url)
    for url in urls:
        await ensure_database(url)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main())
