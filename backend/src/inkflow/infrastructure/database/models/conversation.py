"""#744 会话（线程）ORM 模型 -- 映射到 conversations 表."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConversationORM(Base):
    """会话（线程）ORM -- 项目内对话线程落库."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delete_permission: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="manual",  # "manual" | "ask_once" | "auto" (#766 阶段②)
    )

    def __repr__(self) -> str:
        return f"<ConversationORM id={self.id}>"
