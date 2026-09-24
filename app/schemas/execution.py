from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.domain.models import ExecutionResult, ExecutionStatus
from app.services.scheduler import TickReport


class ExecutionOut(BaseModel):
    id: UUID
    task_id: UUID
    user: str
    action: str
    status: ExecutionStatus
    message: str
    tick_id: str
    scheduled_for: datetime
    started_at: datetime
    duration_ms: int

    @classmethod
    def from_domain(cls, result: ExecutionResult, tz: ZoneInfo) -> "ExecutionOut":
        return cls(
            id=result.id,
            task_id=result.task_id,
            user=result.username,
            action=result.action,
            status=result.status,
            message=result.message,
            tick_id=result.tick_id,
            scheduled_for=result.scheduled_for.astimezone(tz),
            started_at=result.started_at.astimezone(tz),
            duration_ms=result.duration_ms,
        )


class TickReportOut(BaseModel):
    tick_id: str
    started_at: datetime
    results: list[ExecutionOut]

    @classmethod
    def from_domain(cls, report: TickReport, tz: ZoneInfo) -> "TickReportOut":
        return cls(
            tick_id=report.tick_id,
            started_at=report.started_at.astimezone(tz),
            results=[ExecutionOut.from_domain(r, tz) for r in report.results],
        )
