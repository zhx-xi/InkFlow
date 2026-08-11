"""大纲/情节点/故事弧线 ORM 模型 — 映射到 outlines, plot_points, story_arcs 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 F1 project.py / F9 character.py / F10 world.py）。

设计约定（F11 spec §2）:
- DB 主键为 int 自增；领域层 id 为 UUID，
  映射规则: domain_id = uuid.UUID(int=orm.id)
  （int↔UUID 转换函数在 repositories/outline_repo.py，
  参照 project_repo.py / character_repo.py 惯例）
- 软删除标记 is_deleted + partial unique index（sqlite_where）保证
  「活动记录唯一、软删除后可重建同名」的语义（spec §2.4）
- FK 级联: 项目删除 → 大纲/情节点/弧线级联删除；大纲硬删除 → 情节点物理级联删除
  （大纲软删 → 情节点级联软删由服务层实现）；弧线删除 → 情节点 arc_id 置 NULL
- 情节点冗余 project_id（同 F9 CharacterRelation 先例），便于弧线跨项目归属校验
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
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
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class OutlineORM(Base):
    """大纲 ORM 模型 — 映射到 outlines 表.

    Maps to the ``outlines`` table. Each row corresponds to one
    outline document within a project.
    """

    __tablename__ = "outlines"

    __table_args__ = (
        Index(
            "uq_outlines_active_name",
            "project_id",
            "name",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )
    """项目内活动大纲名唯一（软删除后允许重建同名，spec §2.4）."""

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
    """大纲名 (1–50 字符，去空白)."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """大纲总体描述 (≤ 5000 字符)."""

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """大纲间排序权重（小者在前，≥ 0）."""

    extra: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """扩展字典（生成标记、来源约束等 Phase 2+ 字段预留）."""

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
        return f"<OutlineORM id={self.id} name={self.name!r}>"


class PlotPointORM(Base):
    """情节点 ORM 模型 — 映射到 plot_points 表.

    Maps to the ``plot_points`` table. Each row corresponds to one
    plot beat within an outline. No unique constraint (spec §2.4):
    names and positions may repeat within an outline.
    """

    __tablename__ = "plot_points"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（领域层映射为 UUID）."""

    outline_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("outlines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """所属大纲（大纲硬删除级联删除；软删级联由服务层实现，已索引）."""

    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """所属项目（冗余存储，便于弧线归属校验与项目隔离，同 F9 CharacterRelation 先例，已索引）."""

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    """情节点名 (1–100 字符，去空白；大纲内允许重名)."""

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="",
    )
    """情节点类型 (≤ 20 字符，去空白；空串 = 未分类，自由文本)."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """情节点要点描述 (≤ 5000 字符)."""

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """大纲内排序（小者在前，≥ 0；允许重复，稳定排序靠 created_at）."""

    arc_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("story_arcs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """所属故事弧线（可选；弧线删除时置 NULL，已索引）."""

    extra: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """扩展字典（参与角色、地点等 Phase 2+ 字段预留）."""

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
        return f"<PlotPointORM id={self.id} name={self.name!r}>"


class StoryArcORM(Base):
    """故事弧线 ORM 模型 — 映射到 story_arcs 表.

    Maps to the ``story_arcs`` table. Each row corresponds to one
    project-level story arc that may span multiple outlines.
    """

    __tablename__ = "story_arcs"

    __table_args__ = (
        Index(
            "uq_story_arcs_active_name",
            "project_id",
            "name",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )
    """项目内活动弧线名唯一（软删除后允许重建同名，spec §2.4）."""

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
    """弧线名 (1–50 字符，去空白)."""

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    """弧线说明 (≤ 500 字符)."""

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
        return f"<StoryArcORM id={self.id} name={self.name!r}>"
