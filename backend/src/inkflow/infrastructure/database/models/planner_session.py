"""F44 访谈会话 PlannerSession ORM 模型 - 映射到 planner_sessions 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 agent_run.py 先例）.

设计约定（spec §2.2/§8.1）：
- id 主键存 uuid4 字符串（String(36)），默认由 ORM 生成 str(uuid.uuid4())
- project_id 为 uuid4 字符串列（String(36) + index，存 str(uuid)），
  领域 UUID → 字符串转换在 repo 层
- asked_questions / answers / authorized 存 LenientJSON 列
  （fallback=[] / {}，容错空串与损坏 JSON，见 #261），转换函数在 repo 层
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层，防 ruff F821/UP037）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class PlannerSessionORM(Base):
    """访谈会话 - 映射到 planner_sessions 表."""

    __tablename__ = "planner_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """会话 UUID 主键（uuid4 字符串，兼容 SQLite）."""

    project_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    """所属项目 UUID 字符串（已索引；无 FK - 镜像 AgentRunORM 先例）."""

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="drafting",
    )
    """会话状态（drafting/completed/declined）."""

    one_liner: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    """用户一句话（题材/体裁/篇幅/主题等原始输入）."""

    round: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    """当前轮次（每轮 ≤5 问）."""

    asked_questions: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """已问问题快照（JSON 列表，供问题即模板复用）."""

    answers: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """用户回答快照 {question_id: answer}（JSON 列）."""

    authorized: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """显式授权项（JSON 列表，如「配角自定」「细节自定」）."""

    writing_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """会话完成后关联的 WritingPlan UUID 字符串（None = 未完成）."""

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
        return f"<PlannerSessionORM id={self.id!r} status={self.status!r}>"
