"""F27 Writer Agent 运行领域模型 — Agentic 写作闭环的决策轨迹快照.

AgentRun 是一次 agentic 写作运行的全量记录（状态机 + 决策轨迹 + 最终产物）:
- steps: 每步 LLM 决策快照（message_content + tool_calls + tokens），
  run 结束后一次落库（ADR-D 产物保留）.
- status: 运行状态机（running → completed/failed/terminated_by_guardrail）.
- terminated_by: 终止原因（"llm"/"max_steps"/"repeat_tool"/"total_tool_calls"/
  "empty_content"/"token_budget"）.

依据: specs/f27-writer-agent/spec.md（父侧契约 test_agent_run_repo.py /
test_agentic_writer_service.py docstring 同源）。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AgentToolCall(BaseModel):
    """单次工具调用记录（决策轨迹原子单元）.

    Attributes:
        step_index: 所属步骤序号（与 AgentStep.index 一致）.
        tool_name: 工具名（如 search_characters / save_draft）.
        arguments: 工具调用参数（JSON 可序列化 dict）.
        result: 工具返回结果（JSON 字符串）.
        is_error: 工具执行是否失败（默认 False）.
    """

    step_index: int
    tool_name: str
    arguments: dict
    result: str
    is_error: bool = False  # 工具执行是否失败


class AgentStep(BaseModel):
    """单次 LLM 决策步骤快照.

    Attributes:
        index: 步骤序号（0 起）.
        message_content: 该步 AIMessage 文本（空 = 只调工具）.
        tool_calls: 该步发出的工具调用列表.
        tokens: 该步 token 消耗（默认 0）.
    """

    index: int
    message_content: str  # 该步 AIMessage 文本（空 = 只调工具）
    tool_calls: list[AgentToolCall]
    tokens: int = 0


class AgentRunStatus(StrEnum):
    """Agentic 运行状态机（spec §5.4）.

    Attributes:
        RUNNING: 运行中（初始态）.
        COMPLETED: LLM 自然终止（产出最终正文）.
        FAILED: 异常失败（异常抛出路径）.
        TERMINATED_BY_GUARDRAIL: 护栏终止（产物保留，非异常）.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED_BY_GUARDRAIL = "terminated_by_guardrail"


class AgentRun(BaseModel):
    """一次 agentic 写作运行记录（spec §5.7 决策轨迹）.

    Attributes:
        id: run UUID 字符串（uuid4）.
        project_id: 所属项目 UUID.
        chapter_id: 目标章节 UUID（None = 未绑定）.
        mode: 运行模式（默认 "agentic"）.
        status: 运行状态（默认 running）.
        steps: 决策轨迹全量快照（run 结束后一次写回）.
        final_content: 最终正文产物（guardrail 终止可为空）.
        draft_id: 兜底保存的草稿 id（消息历史含 save_draft 时回填）.
        model: 本次运行使用的模型标识.
        token_usage_total: 累计 token 消耗.
        terminated_by: 终止原因（"llm"/"max_steps"/"repeat_tool"/"total_tool_calls"/
            "empty_content"/"token_budget"）.
        created_at: 创建时间（UTC）.
        updated_at: 最后更新时间（UTC）.
    """

    model_config = {"from_attributes": True}

    id: str
    project_id: uuid.UUID
    chapter_id: uuid.UUID | None = None
    mode: str = "agentic"
    status: AgentRunStatus = AgentRunStatus.RUNNING
    steps: list[AgentStep] = []
    final_content: str = ""
    draft_id: str | None = None
    model: str = ""
    token_usage_total: int = 0
    terminated_by: str = ""  # "llm"/"max_steps"/"repeat_tool"/"total_tool_calls"/
    # "empty_content"/"token_budget"
    created_at: datetime
    updated_at: datetime


class AgenticWriteRequest(BaseModel):
    """agentic 写作请求 DTO（GUI/CLI 共用，spec §5.1）.

    Attributes:
        project_id: 所属项目 UUID.
        chapter_id: 目标章节 UUID（None = 未绑定）.
        outline: 本章大纲（必填）.
        context: 上下文文本（默认空）.
        min_words: 目标最低字数（默认 2000）.
        style_hint: 风格提示（可选）.
        max_steps: 最大工具步数（None = 读设置/默认 12）.
        token_budget: token 预算（None = 读设置/默认 32K）.
        max_total_tool_calls: 会话总工具调用上限（None = 读设置/默认 20）.
        memory_learning: F28 记忆学习显式覆盖（None = 读项目配置，F13 同构）.
    """

    project_id: uuid.UUID
    chapter_id: uuid.UUID | None = None
    outline: str
    context: str = ""
    min_words: int = 2000
    style_hint: str | None = None
    max_steps: int | None = Field(default=None, ge=1)  # None = 读设置/默认 12
    token_budget: int | None = Field(default=None, ge=1)  # None = 读设置/默认 32K
    max_total_tool_calls: int | None = Field(default=None, ge=1)  # None = 读设置/默认 20
    memory_learning: bool | None = None  # F28: None = 读项目配置 extra["memory_learning"]
