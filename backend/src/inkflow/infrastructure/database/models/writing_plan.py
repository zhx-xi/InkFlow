"""F44 书级编排 WritingPlan ORM 模型 - 映射到 writing_plans 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 agent_run.py 先例）.

设计约定（spec §2.1/§8.1）：
- id 主键存 uuid4 字符串（String(36)），默认由 ORM 生成 str(uuid.uuid4())
- project_id 为 uuid4 字符串列（String(36) + index，存 str(uuid)），
  领域 UUID → 字符串转换在 repo 层
- character_ids / limits / progress / execution_refs 存 LenientJSON 列
  （fallback=[] / {}，容错空串与损坏 JSON，见 #261），转换函数在 repo 层
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层，防 ruff F821/UP037）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class WritingPlanORM(Base):
    """书级编排元数据 - 映射到 writing_plans 表."""

    __tablename__ = "writing_plans"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """计划 UUID 主键（uuid4 字符串，兼容 SQLite）."""

    project_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    """所属项目 UUID 字符串（已索引；无 FK - 镜像 AgentRunORM 先例）."""

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    """书名/计划名（planner 访谈产出，或用户一句话标题）."""

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="drafting",
    )
    """计划状态（drafting/auto/ready/running/completed/aborted）."""

    root_outline_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """书级大纲（level=overall）UUID 字符串 - 结构树锚点（可空）."""

    character_ids: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """主角/配角 character 实体 id 字符串列表（JSON 列）."""

    limits: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """多维上限（JSON 列，见 spec §2.4）."""

    progress: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """节点进度快照 {outline_id: PlanNodeStatus}（JSON 列）."""

    execution_refs: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """章执行引用 {outline_id: execution_id}（JSON 列）."""

    thread_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    """LangGraph checkpoint thread_id（阶段 4 落库；可空）."""

    hitl_payload: Mapped[dict | None] = mapped_column(
        LenientJSON(fallback=None),
        nullable=True,
        default=None,
    )
    """卷级 HITL 暂停 payload（JSON 列，waiting_hitl 时非空；可空）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动刷新）."""

    def __repr__(self) -> str:
        return f"<WritingPlanORM id={self.id!r} status={self.status!r}>"
