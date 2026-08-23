"""项目/书籍 ORM 模型 — 映射到 projects 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class ProjectORM(Base):
    """项目/书籍 ORM 模型.

    Maps to the ``projects`` table. Each row corresponds to one
    writing project (a "book" in the user's library).
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键."""

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    """项目名称 (1–100 字符，已索引)."""

    tags: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """项目标签（多值字符串数组，JSON 序列化存储，默认空列表）."""

    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="zh-CN",
    )
    """写作语言，默认简体中文."""

    target_words: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """目标字数（0 表示不限）."""

    config: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """AI 写作配置，JSON 序列化存储."""

    active_watermark: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    """活跃基准（单调累计，只随用户活跃推进）"""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    """软删除标记（已索引，用于过滤查询）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）. """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）. """

    def __repr__(self) -> str:
        return f"<ProjectORM id={self.id} name={self.name!r}>"
