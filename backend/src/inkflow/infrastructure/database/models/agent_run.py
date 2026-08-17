"""F27 Agent Run / Draft ORM 模型 — 映射到 agent_runs / drafts 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 F1 project.py / F13 foreshadowing.py）。

设计约定（spec §2/§8，父侧契约 test_agent_run_repo.py / test_draft_repo.py）:
- id 存储形态: uuid4 字符串（与 AgentExecutionORM.id 一致，SQLite 兼容）
- project_id / chapter_id 为 uuid4 字符串列（String(36) + index，镜像
  AgentExecutionORM 先例——F4 实测：agent_executions.project_id 即 String(36)
  无 FK），存 str(uuid)；领域 UUID ↔ 字符串转换在 repo 层
- 无 FK 声明：projects/chapters 主键为 int 自增，String(36) uuid 值与 int
  主键永不匹配，FK 声明会误导（PRAGMA foreign_keys=ON 时拦截插入）——
  级联删除语义由服务层承担（与 agent_executions 同构）
- steps 为 JSON 快照列（AgentStep 字典列表，Q4 拍板 A，与
  AgentExecutionORM.stages JSON 先例一致）
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
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


class AgentRunORM(Base):
    """一次 agentic 写作运行记录 — 映射到 agent_runs 表."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """run UUID 主键（uuid4 字符串，兼容 SQLite）."""

    project_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    """所属项目 UUID 字符串（已索引；无 FK——镜像 AgentExecutionORM 先例）."""

    chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    """目标章节 UUID 字符串（可选；无 FK——镜像 AgentExecutionORM 先例）."""

    mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="agentic",
    )
    """运行模式（默认 agentic）."""

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="running",
    )
    """运行状态（running/completed/failed/terminated_by_guardrail）."""

    steps: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """决策轨迹 JSON 快照（AgentStep 字典列表，run 结束后一次写回）."""

    final_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """最终正文产物（guardrail 终止可为空）."""

    draft_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """兜底保存的草稿 id（可空）."""

    model: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
    )
    """本次运行使用的模型标识."""

    token_usage_total: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """累计 token 消耗."""

    terminated_by: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="",
    )
    """终止原因（llm/max_steps/repeat_tool/total_tool_calls/empty_content/token_budget）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）."""

    def __repr__(self) -> str:
        return f"<AgentRunORM id={self.id!r} status={self.status!r}>"


class DraftORM(Base):
    """一份草稿记录 — 映射到 drafts 表."""

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """草稿 UUID 主键（uuid4 字符串，兼容 SQLite）."""

    project_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    """所属项目 UUID 字符串（已索引；无 FK——镜像 AgentExecutionORM 先例）."""

    chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    """目标章节 UUID 字符串（可选，None = 确认时指定；无 FK——镜像先例）."""

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """产生该草稿的 run id（可空，无 FK——草稿可在 run 前独立创建）."""

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    """草稿正文."""

    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """草稿摘要（默认空）."""

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
    )
    """草稿状态（draft/confirmed/rejected）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）."""

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    """确认时间（draft/rejected 为 None）."""

    def __repr__(self) -> str:
        return f"<DraftORM id={self.id!r} status={self.status!r}>"
