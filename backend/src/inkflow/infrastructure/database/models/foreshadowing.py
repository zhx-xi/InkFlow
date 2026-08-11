"""伏笔 ORM 模型 — 映射到 foreshadowings 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 F1 project.py / F9 character.py / F12 timeline.py）。

设计约定（F13 spec §2 / §8）:
- DB 主键为 int 自增；领域层 id 为 UUID，
  映射规则: domain_id = uuid.UUID(int=orm.id)
  （int↔UUID 转换函数在 repositories/foreshadowing_repo.py，
  参照 project_repo.py / character_repo.py 惯例）
- partial unique index（sqlite_where）保证「项目内活动伏笔同名唯一、
  软删除后可重建同名」的语义（spec §2.3: 伏笔是档案，「同名 = 同一伏笔」）
- 索引（spec §8）: project_id / (project_id, status) /
  (project_id, priority) / (project_id, event_id)，支撑项目隔离、
  状态过滤、注入优先级排序与事件锚点查询
- FK 级联: 项目硬删除 → 伏笔级联物理删除；事件硬删（force）→
  event_id 置 NULL（挂接解除，软删事件不影响锚点，spec §2.1）
- event_id 列类型为 int（与 F12 timeline_events.id 自增主键一致）；
  领域层 UUID 与 int 的映射由 repo 层转换
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


class ForeshadowingORM(Base):
    """伏笔档案 ORM 模型 — 映射到 foreshadowings 表.

    Maps to the ``foreshadowings`` table. Each row corresponds to one
    foreshadowing archive within a project (a single lifecycle:
    埋设 → 追踪 → 回收), so active titles are unique per project
    (spec §2.3).
    """

    __tablename__ = "foreshadowings"

    __table_args__ = (
        Index(
            "uq_foreshadowings_active_title",
            "project_id",
            "title",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
        Index("ix_foreshadowings_project_id", "project_id"),
        Index("ix_foreshadowings_project_status", "project_id", "status"),
        Index("ix_foreshadowings_project_priority", "project_id", "priority"),
        Index("ix_foreshadowings_project_event_id", "project_id", "event_id"),
    )
    """项目内活动伏笔同名唯一（软删除后允许重建同名，spec §2.3）+
    项目隔离 / 状态过滤 / 注入优先级排序 / 事件锚点查询索引（spec §8）."""

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
    """伏笔名 (1–100 字符，去空白；项目内活动伏笔唯一)."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """伏笔详情 (≤ 5000 字符：埋设内容、预期回收方式)."""

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
    )
    """注入优先级 (0–100，大者先注入；F6 dynamic 层排序契约的键)."""

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
    )
    """伏笔状态 (open 已埋设未回收 / resolved 已回收，spec §2.4 状态机)."""

    location: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
    )
    """埋设位置自由文本 (≤ 200 字符；空 = 未记录)."""

    event_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("timeline_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    """F12 时间线事件锚点（事件硬删 → 置 NULL 解除挂接；软删不影响锚点）.
    事件叙事位置从事件获取，本表不存独立 narrative_position（spec §2.2）."""

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    """回收时间 (UTC；仅状态迁移维护：resolve 设置 / reopen 清空，已索引)."""

    extra: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """扩展字典（标签、关联角色名等 Phase 2+ 字段预留）."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    """软删除标记（已索引，用于过滤查询；软删伏笔不进入注入与列表）."""

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
        return f"<ForeshadowingORM id={self.id} title={self.title!r}>"
