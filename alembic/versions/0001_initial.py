"""Create users, tasks, and executions tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(50), primary_key=True),
        sa.Column("daily_quota", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("daily_quota >= 0", name="ck_users_daily_quota"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(50), sa.ForeignKey("users.username"), nullable=False),
        sa.Column("run_at", sa.Time(), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tasks_username", "tasks", ["username"])
    op.create_index("ix_tasks_next_run_at", "tasks", ["next_run_at"])
    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("tick_id", sa.String(16), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'FAILED', 'QUOTA_EXCEEDED')", name="ck_executions_status"
        ),
    )
    op.create_index("ix_executions_status", "executions", ["status"])
    op.create_index("ix_executions_username_started_at", "executions", ["username", "started_at"])


def downgrade() -> None:
    op.drop_table("executions")
    op.drop_table("tasks")
    op.drop_table("users")
