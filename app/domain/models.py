"""Plain domain models shared by services, repositories, and the API layer."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from typing import Any
from uuid import UUID


class ExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"


@dataclass(frozen=True)
class User:
    username: str
    daily_quota: int
    created_at: datetime


@dataclass(frozen=True)
class Task:
    id: UUID
    username: str
    run_at: time
    action: str
    params: Mapping[str, Any]
    next_run_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ClaimedTask:
    """A task picked up by one tick, with the slot it was scheduled for."""

    task: Task
    scheduled_for: datetime


@dataclass(frozen=True)
class ExecutionResult:
    id: UUID
    task_id: UUID
    username: str
    action: str
    status: ExecutionStatus
    message: str
    tick_id: str
    scheduled_for: datetime
    started_at: datetime
    duration_ms: int


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    used: int
    limit: int
