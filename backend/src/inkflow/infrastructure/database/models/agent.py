"""Agent 管线 ORM 模型."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON
from inkflow.infrastructure.database.models.agent_entity import AgentORM

__all__ = ["AgentExecutionORM", "AgentORM", "AgentStageResultORM"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentExecutionORM(Base):
    """一次管线执行记录 — 映射到 agent_executions 表."""

    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """执行记录 UUID 主键（uuid4 字符串，兼容 SQLite）."""

    pipeline: Mapped[str] = mapped_column(String(100), nullable=False)
    """管线标识（如 builtin:write_chapter）."""

    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    """所属项目 ID（已索引）."""

    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    """关联章节 ID（可选，取决于管线类型）."""

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    """管线整体状态（pending/running/completed/failed/skipped）."""

    stages: Mapped[list] = mapped_column(LenientJSON(fallback=[]), nullable=False, default=list)
    """各阶段快照（StageResult 字典列表，JSON 序列化）."""

    final_output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """管线最终输出."""

    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """错误信息（失败时填充）."""

    total_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """管线总耗时（毫秒）."""

    hitl_payload: Mapped[dict | None] = mapped_column(
        LenientJSON(fallback=None), nullable=True, default=None
    )
    """HITL interrupt payload 快照（waiting_hitl 时填充）。"""

    relations: Mapped[list] = mapped_column(LenientJSON(fallback=[]), nullable=False, default=list)
    """本次执行的 agent_relations 边 + conditional gate 判定快照（F46 #270，spec §5.4）。
    元素形态 {from, to, type, gate_result}（gate_result: passed/skipped，仅 conditional 边有值）。
    """

    trace: Mapped[list] = mapped_column(LenientJSON(fallback=[]), nullable=False, default=list)
    """本次执行的轨迹快照（TraceEntry 列表：
    node/type/reasoning/tool_calls/output/duration_ms/ts）。
    """

    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    """LangGraph checkpoint thread_id（书级运行 ↔ 图 checkpoint 一一映射；None = 非书级运行）"""

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    """记录创建时间（UTC）."""

    def __repr__(self) -> str:
        return (
            f"<AgentExecutionORM id={self.id!r} pipeline={self.pipeline!r} status={self.status!r}>"
        )


class AgentStageResultORM(Base):
    """单个管线阶段的执行结果记录 — 映射到 agent_stage_results 表."""

    __tablename__ = "agent_stage_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    """自增主键."""

    execution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_executions.id"),
        nullable=False,
        index=True,
    )
    """所属执行记录 ID（外键 → agent_executions.id，已索引）."""

    stage_id: Mapped[str] = mapped_column(String(50), nullable=False)
    """阶段标识（如 outline / chapter_write / style_review）."""

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    """阶段状态（pending/running/completed/failed/skipped）."""

    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """阶段输出."""

    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """阶段错误信息."""

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """重试次数."""

    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """阶段耗时（毫秒）."""

    def __repr__(self) -> str:
        return (
            f"<AgentStageResultORM id={self.id} stage_id={self.stage_id!r} status={self.status!r}>"
        )
