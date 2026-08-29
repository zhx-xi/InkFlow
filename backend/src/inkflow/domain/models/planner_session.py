"""F44 访谈式 Planner 会话领域模型 - 多轮访谈会话载体.

访谈会话（新建表 planner_sessions，阶段 1）：分批 <=5 问、问题即模板、
授权项记录、auto 兜底（「全部你决定」declined 后直接跑 F42 write_auto）.

依据: specs/f44-book-orchestrator/spec.md 搂2.2/搂5.1（v1.2 #475）.
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class PlannerSession(BaseModel):
    """访谈会话（新建表 planner_sessions，阶段 1；v1.2 #475 扩展确定项/冲突/总体确认）.

    Attributes:
        id: 会话 UUID.
        project_id: 所属项目 UUID.
        status: drafting / completed / declined（「全部你决定」declined 后直接跑 F42）.
        one_liner: 用户一句话（题材/体裁/篇幅/主题等原始输入）.
        round: 当前轮次（每轮 <=5 问）.
        asked_questions: 已问问题快照（JSON，供问题即模板复用）.
        answers: 用户回答快照 {question_id: answer}.
        authorized: 显式授权项（如「配角自定」「细节自定」）.
        confirmed_items: 已确定项快照（v1.2 #475：list[dict]，
            {"key", "value", "source"}，source 属于 user | llm_inferred | auto）.
        conflicts: 冲突/回问记录（v1.2 #475：list[dict]，
            {"round", "question_id", "answer", "conflict_with", "resolution"}）.
        confirming: 末尾总体确认阶段标志（v1.2 #475：必答项齐备后置 True，
            非 status 值）.
        start_type: 起点模式（#544）：new / continue / branch.
        source_outline_id: 起点源大纲（continue/branch 用；new 为 None）.
        copied_outline_id: branch 复制出的新大纲根 id（#544 命名裁定）.
        writing_plan_id: 会话完成后关联的 WritingPlan UUID（None = 未完成）.
        created_at / updated_at: 时间戳.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    status: str = "drafting"
    one_liner: str
    round: int = 1
    asked_questions: list[dict] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    authorized: list[str] = Field(default_factory=list)
    confirmed_items: list[dict] = Field(default_factory=list)
    """已确定项快照（v1.2 #475：{"key", "value", "source"}，source 属于
    user | llm_inferred | auto）."""
    conflicts: list[dict] = Field(default_factory=list)
    """冲突/回问记录（v1.2 #475：{"round", "question_id", "answer",
    "conflict_with", "resolution"}）."""
    confirming: bool = False
    """末尾总体确认阶段标志（v1.2 #475：必答项齐备后置 True，非 status 值）."""
    start_type: str = "new"
    """起点模式（#544）：new / continue / branch。"""
    source_outline_id: uuid.UUID | None = None
    """起点源大纲（continue/branch 用；new 为 None）。"""
    copied_outline_id: uuid.UUID | None = None
    """branch 复制出的新大纲根 id（#544 命名裁定，避免与 source 混淆）。"""
    writing_plan_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
