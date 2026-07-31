"""上下文管理 ORM 模型 — 映射到 chapter_summaries 表."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChapterSummaryORM(Base):
    """章节摘要缓存 ORM 模型.

    每章一条摘要（chapter_id 唯一约束），updated_at 用于失效检测：
    chapter.updated_at > summary.updated_at 时缓存过期，需重新生成。
    """

    __tablename__ = "chapter_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<ChapterSummaryORM id={self.id} chapter_id={self.chapter_id} model={self.model!r}>"
