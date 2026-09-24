from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.domain.models import Task
from app.services.task_service import TaskSubmission

# The request body is the same dictionary shape the service accepts.
TaskCreate = TaskSubmission


class TaskOut(BaseModel):
    id: UUID
    user: str
    time: str
    action: str
    params: dict[str, Any]
    next_run_at: datetime
    created_at: datetime

    @classmethod
    def from_domain(cls, task: Task, tz: ZoneInfo) -> "TaskOut":
        return cls(
            id=task.id,
            user=task.username,
            time=task.run_at.strftime("%H:%M"),
            action=task.action,
            params=dict(task.params),
            next_run_at=task.next_run_at.astimezone(tz),
            created_at=task.created_at.astimezone(tz),
        )
