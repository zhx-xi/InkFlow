"""时间线事件 ORM 模型 — 映射到 timeline_events 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 F1 project.py / F9 character.py / F10 world.py / F11 outline.py）。

设计约定（F12 spec §2）:
- DB 主键为 int 自增；领域层 id 为 UUID，
  映射规则: domain_id = uuid.UUID(int=orm.id)
  （int↔UUID 转换函数在 repositories/timeline_repo.py，
  参照 project_repo.py / character_repo.py 惯例）
- 本表不设任何唯一约束（spec §2.4）: title / narrative_position /
  time_value 均允许重复——时间线事件是「实例」而非「档案」，
  无 partial unique index（区别于 F9/F10/F11 的同名唯一语义）
- 四个非唯一索引: project_id / (project_id, narrative_position) /
  (project_id, time_value) / source_chapter_id，支撑项目隔离、叙事排序、
  事件时间线排序与 F14 按来源章拉取（list_by_chapter）
- FK 级联: 项目硬删除 → 事件级联物理删除；章节硬删除 →
  source_chapter_id 置 NULL（事件保留，spec §5.5 联动语义）；无子实体、
  无级联软删
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class TimelineEventORM(Base):
    """时间线事件 ORM 模型 — 映射到 timeline_events 表.

    Maps to the ``timeline_events`` table. Each row corresponds to one
    timeline event within a project. No unique constraint (spec §2.4):
    titles, narrative positions and time values may all repeat.
    """

    __tablename__ = "timeline_events"

    __table_args__ = (
        Index("ix_timeline_events_project_id", "project_id"),
        Index(
            "ix_timeline_events_project_narrative",
            "project_id",
            "narrative_position",
        ),
        Index(
            "ix_timeline_events_project_time",
            "project_id",
            "time_value",
        ),
    )
    """非唯一索引: 项目隔离 / 叙事排序 / 事件时间线排序（spec §8）."""

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
    )
    """所属项目（项目硬删除级联删除；索引见 __table_args__）."""

    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    """事件标题 (1–100 字符，去空白；允许重复)."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """事件描述 (≤ 5000 字符，该时刻发生了什么)."""

    time_value: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    """世界内时间数值键（可排序/可比较；None = 时间未知，排末尾、不参与一致性检查）."""

    time_unit: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="",
    )
    """时间单位标签 (≤ 20 字符，去空白；仅语义说明，不参与排序)."""

    time_display: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
    )
    """原始时间表达 (≤ 100 字符，如「青元历 317 年秋」；time_value 的人工可读镜像)."""

    narrative_position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """叙事位置（单一线性序号，小者在前；允许重复，稳定排序靠 created_at）."""

    timeline_flag: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="",
    )
    """时间线标记 (≤ 20 字符，去空白；""=正叙 / flashback=倒叙 / flashforward=插叙)."""

    source_chapter_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("chapters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """来源章节（F14 提取锚点；章节硬删 → 置 NULL 事件保留；索引支撑 list_by_chapter）."""

    extra: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    """扩展字典（参与角色、地点、标签等 Phase 2+ 字段预留）."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    """软删除标记（软删事件不进入双线视图与一致性检查）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）. """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）. """

    def __repr__(self) -> str:
        return f"<TimelineEventORM id={self.id} title={self.title!r}>"
