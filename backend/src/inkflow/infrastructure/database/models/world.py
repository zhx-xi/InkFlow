"""世界观条目 ORM 模型 — 映射到 world_settings 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F1 project.py / F9 character.py）。

设计约定（同 F9 spec §2 / character.py）:
- DB 主键为 int 自增；领域层 id 为 UUID，映射规则: domain_id = uuid.UUID(int=orm.id)
  （int↔UUID 转换函数在 repositories/world_repo.py，参照 project_repo.py / character_repo.py 惯例）
- 全唯一索引 (project_id, parent_id, name) 保证「同级内条目名唯一」的语义
  （v1.1 真删语义移除 is_deleted 列与 partial unique，spec §2.4；
  顶层应用层校验——SQLite unique index 对 NULL 不冲突）
- FK 级联: 项目删除 → 世界观条目级联删除
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


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
            "uq_world_settings_active_name_parent",
            "project_id",
            "parent_id",
            "name",
            unique=True,
        ),
        Index(
            "uq_world_settings_root_per_project",
            "project_id",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
        ),
    )
    """同级（project_id, parent_id）内条目名唯一（v1.1 全唯一索引；
    spec §2.4；顶层应用层校验——SQLite unique index 对 NULL 不冲突）."""

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

    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("world_settings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """父地点（自引用 FK，可空=顶层；已索引）."""

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
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """扩展字典（来源章节、标签、别名等 Phase 2+ 字段预留）."""

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


class WorldCategoryORM(Base):
    """世界观分类 ORM 模型 — 映射到 world_categories 表（受控词表，v1.2）.

    Maps to the ``world_categories`` table. Each row is a controlled
    vocabulary category within a project (issue #389).
    """

    __tablename__ = "world_categories"

    __table_args__ = (
        Index(
            "uq_world_categories_project_name",
            "project_id",
            "name",
            unique=True,
        ),
    )
    """项目内分类名唯一（v1.2 全唯一索引，spec §2.6）."""

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
    """分类名 (1–50 字符，去空白；项目内唯一)."""

    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="geo",
    )
    """分类类型 (#699): geo=地理类可挂地图 / abstract=抽象类不可挂地图."""

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
        return f"<WorldCategoryORM id={self.id} name={self.name!r}>"
