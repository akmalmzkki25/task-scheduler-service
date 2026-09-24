from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("daily_quota >= 0", name="ck_users_daily_quota"),)

    username: Mapped[str] = mapped_column(String(50), primary_key=True)
    daily_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
