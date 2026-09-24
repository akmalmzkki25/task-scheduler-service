"""Loads the legacy script's users and tasks so the demo starts with familiar data."""

import logging
from typing import Any

from app.domain.errors import UserAlreadyExistsError
from app.services.task_service import TaskService
from app.services.user_service import UserService

logger = logging.getLogger("app.seed")

LEGACY_USERS: dict[str, int] = {"alice": 3, "bob": 5}
LEGACY_TASKS: list[dict[str, Any]] = [
    {"user": "alice", "time": "12:00", "action": "sync", "params": {"target": "/data/x"}},
    {"user": "bob", "time": "12:00", "action": "backup", "params": {"target": "/srv/y"}},
    {"user": "alice", "time": "12:00", "action": "delete", "params": {"target": "/tmp/z"}},
]


async def seed_demo_data(users: UserService, tasks: TaskService) -> None:
    """Create the legacy users and their tasks. Users that already exist are left alone."""
    created = set()
    for username, quota in LEGACY_USERS.items():
        try:
            await users.register(username, quota)
        except UserAlreadyExistsError:
            logger.info("Seed user %s already exists, skipping", username)
            continue
        created.add(username)

    for task in LEGACY_TASKS:
        if task["user"] in created:
            await tasks.submit(task)
    logger.info("Seeded %d users with legacy tasks", len(created))
