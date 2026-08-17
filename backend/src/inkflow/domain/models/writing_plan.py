"""F44 长任务编排 WritingPlan 领域模型 - 计划编排元数据与多维上限.

WritingPlan 只存编排元数据（结构锚点/进度/上限/执行引用/thread_id），
大纲与角色实体由 planner 直接写 outline/character 表（spec 搂2.1 决策论证表）。

依据: specs/f44-long-task-orchestrator/spec.md 搂2.1/搂2.4（v1.1）.
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class PlanNodeStatus(StrEnum):
    """计划节点进度状态机（设计 搂2.2 + #335 要点）.

    Values:
        PENDING: 待执行.
        IN_PROGRESS: 执行中.
        DONE: 已完成.
        FAILED: 失败.
        SKIPPED: 跳过.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WritingPlan(BaseModel):
    """书级编排元数据（新建表 writing_plans）.

    Attributes:
        id: 计划 UUID.
        project_id: 所属项目 UUID.
        title: 书名/计划名（planner 访谈产出，或用户一句话标题）.
        status: 计划状态（drafting/auto/ready/running/completed/aborted）.
        root_outline_id: 书级大纲（level=overall）UUID - 结构树锚点.
        character_ids: 主角/配角 character 实体 id 列表（planner 产出）.
        limits: 多维上限计数器（搂2.4；int 计数 + tokens_warning 布尔告警）.
        progress: 节点进度快照 {outline_id: PlanNodeStatus}（权威进度）.
        execution_refs: 章执行引用 {outline_id: execution_id}.
        thread_id: LangGraph checkpoint thread_id（阶段 4 落库）.
        hitl_payload: 卷级 HITL 暂停 payload（waiting_hitl 时非空，§3/§13.3 M8）.
        created_at / updated_at: 时间戳.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    status: str = "drafting"
    root_outline_id: uuid.UUID | None = None
    character_ids: list[uuid.UUID] = Field(default_factory=list)
    limits: dict[str, int | bool] = Field(default_factory=dict)
    progress: dict[str, str] = Field(default_factory=dict)  # outline_id -> status
    execution_refs: dict[str, str] = Field(default_factory=dict)  # outline_id -> execution_id
    thread_id: str | None = None
    hitl_payload: dict[str, Any] | None = None  # 卷级 HITL 暂停 payload（waiting_hitl 时非空）
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class BookLimits(BaseModel):
    """书级运行上限配置（请求体可传；缺省取 ProjectConfig.extra 项目级默认）.

    Attributes:
        max_chapters: 硬护栏 - 章节数上限（默认 100）.
        max_agent_calls: 硬护栏 - 子 agent 调用次数上限（默认 200）.
        max_tokens: 软护栏 - 累计 token 预算（默认 200000，超限告警不强制终止）.
        max_sessions: 硬护栏 - 访谈轮次上限（默认 5 轮 x 5 问）.
    """

    max_chapters: int = 100
    max_agent_calls: int = 200
    max_tokens: int = 200_000
    max_sessions: int = 5


def validate_at_least_one_hard_limit(limits: BookLimits) -> None:
    """「至少一道有限护栏」不变量（#336 启动前校验）.

    max_chapters / max_agent_calls 至少一个为有限值（>0）；
    全部无上限（0 或 None）时抛出 ValueError 拒绝启动.

    Args:
        limits: 待校验的书级上限.

    Raises:
        ValueError: 两道硬护栏均为 0（含 None）.
    """
    if not (limits.max_chapters > 0 or limits.max_agent_calls > 0):
        raise ValueError("至少一道有限护栏：max_chapters 或 max_agent_calls 必须大于 0")


def merge_book_limits(
    request_limits: BookLimits | None,
    project_extra: dict[str, Any] | None = None,
) -> BookLimits:
    """多维上限读取优先级 = 请求显式 > 项目级 extra > 默认常量（§2.4/D11 Q2=C）。
    默认 BookLimits() 起步 → project_extra 键
        book_max_chapters/book_max_agent_calls/book_max_tokens/book_max_sessions
    覆盖（值 int() 转换，缺键跳过）→ 请求 BookLimits 显式字段
        （model_fields_set）覆盖。纯函数：不修改入参、无副作用、无 IO。
    """
    merged = BookLimits()
    if project_extra:
        extra_keys = {
            "max_chapters": "book_max_chapters",
            "max_agent_calls": "book_max_agent_calls",
            "max_tokens": "book_max_tokens",
            "max_sessions": "book_max_sessions",
        }
        for field, extra_key in extra_keys.items():
            if extra_key in project_extra and project_extra[extra_key] is not None:
                setattr(merged, field, int(project_extra[extra_key]))
    if request_limits is not None:
        for field in request_limits.model_fields_set:
            setattr(merged, field, getattr(request_limits, field))
    return merged


STAGE1_LIMITS = BookLimits(max_chapters=1, max_agent_calls=1)
"""阶段 1 写死上限：max_chapters=1 / max_agent_calls=1（#335「上限写死但计数器立起来」）."""
