"""世界观条目 ORM 模型 — 映射到 world_settings 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F1 project.py / F9 character.py）。

设计约定（同 F9 spec §2 / character.py）:
- DB 主键为 int 自增；领域层 id 为 UUID，映射规则: domain_id = uuid.UUID(int=orm.id)
  （int↔UUID 转换函数在 repositories/world_repo.py，参照 project_repo.py / character_repo.py 惯例）
- 软删除标记 is_deleted + partial unique index（sqlite_where）保证
  「活动记录唯一、软删除后可重建同名」的语义（spec §2.4）
- FK 级联: 项目删除 → 世界观条目级联删除
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class WorldSettingORM(Base):
    """世界观条目 ORM 模型 — 映射到 world_settings 表.

    Maps to the ``world_settings`` table. Each row corresponds to one
    world-building entry within a project.
    """

    __tablename__ = "world_settings"

    __table_args__ = (
        Index(
            "uq_world_settings_active_name",
            "project_id",
            "name",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )
    """项目内活动条目名唯一（软删除后允许重建同名，spec §2.4）."""

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（领域层映射为 UUID）."""

    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """所属项目（项目删除级联删除，已索引）."""

    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    """条目名 (1–50 字符，去空白)."""

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="",
    )
    """类别 (≤ 50 字符，去空白；空串 = 未分类)."""

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """条目内容/详细设定 (≤ 20000 字符)."""

    extra: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    """扩展字典（来源章节、标签、别名等 Phase 2+ 字段预留）."""

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
        return f"<WorldSettingORM id={self.id} name={self.name!r}>"
