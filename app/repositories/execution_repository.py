from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import ExecutionResult, ExecutionStatus
from app.models.execution import ExecutionRecord


def _to_domain(row: ExecutionRecord) -> ExecutionResult:
    return ExecutionResult(
        id=row.id,
        task_id=row.task_id,
        username=row.username,
        action=row.action,
        status=ExecutionStatus(row.status),
        message=row.message,
        tick_id=row.tick_id,
        scheduled_for=row.scheduled_for,
        started_at=row.started_at,
        duration_ms=row.duration_ms,
    )


class SqlExecutionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def add_many(self, results: Sequence[ExecutionResult]) -> None:
        if not results:
            return
        async with self._sessions() as session, session.begin():
            session.add_all(
                ExecutionRecord(
                    id=r.id,
                    task_id=r.task_id,
                    username=r.username,
                    action=r.action,
                    status=r.status.value,
                    message=r.message,
                    tick_id=r.tick_id,
                    scheduled_for=r.scheduled_for,
                    started_at=r.started_at,
                    duration_ms=r.duration_ms,
                )
                for r in results
            )

    async def list_page(
        self,
        username: str | None,
        status: ExecutionStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ExecutionResult], int]:
        query: Select[tuple[ExecutionRecord]] = select(ExecutionRecord)
        if username is not None:
            query = query.where(ExecutionRecord.username == username)
        if status is not None:
            query = query.where(ExecutionRecord.status == status.value)
        async with self._sessions() as session:
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = await session.scalars(
                query.order_by(ExecutionRecord.started_at.desc(), ExecutionRecord.id)
                .offset(offset)
                .limit(limit)
            )
            return [_to_domain(row) for row in rows], total or 0
