from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import ClaimedTask, Task
from app.domain.scheduling import compute_next_run
from app.models.task import TaskRecord


def _to_domain(row: TaskRecord) -> Task:
    return Task(
        id=row.id,
        username=row.username,
        run_at=row.run_at,
        action=row.action,
        params=dict(row.params),
        next_run_at=row.next_run_at,
        created_at=row.created_at,
    )


class SqlTaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def add(self, task: Task) -> None:
        async with self._sessions() as session, session.begin():
            session.add(
                TaskRecord(
                    id=task.id,
                    username=task.username,
                    run_at=task.run_at,
                    action=task.action,
                    params=dict(task.params),
                    next_run_at=task.next_run_at,
                    created_at=task.created_at,
                )
            )

    async def list_page(
        self, username: str | None, offset: int, limit: int
    ) -> tuple[list[Task], int]:
        query: Select[tuple[TaskRecord]] = select(TaskRecord)
        if username is not None:
            query = query.where(TaskRecord.username == username)
        async with self._sessions() as session:
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = await session.scalars(
                query.order_by(TaskRecord.created_at, TaskRecord.id).offset(offset).limit(limit)
            )
            return [_to_domain(row) for row in rows], total or 0

    async def claim_due(self, now: datetime, tz: ZoneInfo, limit: int) -> list[ClaimedTask]:
        """Lock due rows, skipping any another tick already holds, and move them forward.

        The SELECT ... FOR UPDATE SKIP LOCKED and the UPDATE share one transaction, so a
        concurrent tick (or another app instance) can never claim the same task.
        """
        query = (
            select(TaskRecord)
            .where(TaskRecord.next_run_at <= now)
            .order_by(TaskRecord.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._sessions() as session, session.begin():
            rows = (await session.scalars(query)).all()
            claimed = []
            for row in rows:
                scheduled_for = row.next_run_at
                row.next_run_at = compute_next_run(row.run_at, tz, now)
                claimed.append(ClaimedTask(task=_to_domain(row), scheduled_for=scheduled_for))
            return claimed
