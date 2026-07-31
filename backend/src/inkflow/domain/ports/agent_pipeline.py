"""
Agent 管线端口 — 定义领域层与 Agent 编排引擎之间的契约。

基础设施层（LangGraph StateGraph）实现此 Protocol。
领域层只依赖此接口，不感知 LangGraph。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class StageStatus(StrEnum):
    """管线阶段状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentRole(BaseModel):
    """Agent 角色定义 — 一个管线阶段中执行的 Agent。

    对应用户配置中的一个角色：
        name: "架构师"
        system_prompt: "你是一位资深小说架构师..."
        model: "openai/gpt-4o"
        temperature: 0.8
    """

    id: str
    """角色唯一标识（如 architect / writer / auditor / reviser）。"""

    name: str
    """角色显示名称（如 "架构师" / "写手" / "审阅" / "修订"）。"""

    system_prompt: str
    """系统 Prompt 模板（支持 {variable} 占位符）。"""

    model: str = "openai/gpt-4o"
    """LLM 模型（LiteLLM 格式：provider/model_name）。"""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    """LLM 温度参数，范围 [0.0, 2.0]。"""

    max_tokens: int | None = None
    """最大输出 Token 数，None 表示不限制。"""


@dataclass
class PipelineStage:
    """管线阶段定义 — 管线中的一个执行步骤。

    每个阶段包含一个 Agent 角色，从上游阶段获取输入，向下游阶段传递输出。
    """

    id: str
    """阶段唯一标识（如 outline / chapter_write / style_review）。"""

    name: str
    """阶段显示名称。"""

    agent: AgentRole
    """该阶段使用的 Agent 角色。"""

    input_from: list[str] = field(default_factory=list)
    """上游阶段的 id 列表。空列表表示管线入口阶段。"""

    output_to: list[str] = field(default_factory=list)
    """下游阶段的 id 列表。空列表表示管线终点阶段。"""

    max_retries: int = 3
    """该阶段失败后的最大重试次数。"""

    required: bool = True
    """该阶段是否必须成功。False 时失败可跳过。"""


@dataclass
class StageResult:
    """单个管线阶段的执行结果。"""

    stage_id: str
    status: StageStatus
    output: str = ""
    error: str = ""
    retry_count: int = 0
    duration_ms: int = 0


@dataclass
class PipelineResult:
    """管线执行结果。"""

    stages: list[StageResult]
    """各阶段执行结果列表。"""

    final_output: str = ""
    """最终阶段的输出。"""

    status: StageStatus = StageStatus.PENDING
    """管线整体状态。"""

    total_duration_ms: int = 0
    """管线总耗时（毫秒）。"""


@dataclass
class PipelineContext:
    """管线执行上下文 — 在各阶段间传递的数据。

    这是领域层的上下文，与 LangGraph 的 State 解耦。
    """

    project_id: str
    """项目 ID。"""

    chapter_id: str | None = None
    """当前章节 ID（可选，取决于管线类型）。"""

    variables: dict[str, str] = field(default_factory=dict)
    """用户定义的变量，可在 Prompt 中使用 {variable} 引用。"""


class AgentPipelineProtocol(Protocol):
    """Agent 管线端口 — 编排多阶段 Agent 执行流程。

    基础设施层实现示例：
        from langgraph.graph import StateGraph
        class LangGraphAgentPipeline: ...

    测试时可注入 Mock 实现，不依赖实际 LLM。
    """

    async def execute(
        self,
        stages: Sequence[PipelineStage],
        context: PipelineContext,
    ) -> PipelineResult:
        """执行管线。

        Args:
            stages: 管线阶段定义列表。
            context: 管线执行上下文。

        Returns:
            PipelineResult: 包含各阶段状态和最终输出的结果。

        Raises:
            PipelineError: 管线执行失败（所有重试耗尽）。
        """
        ...

    def validate(self, stages: Sequence[PipelineStage]) -> list[str]:
        """验证管线定义的合法性。

        Args:
            stages: 待验证的阶段列表。

        Returns:
            错误信息列表。空列表表示管线定义有效。
        """
        ...


class PipelineError(Exception):
    """管线执行错误 — 所有重试耗尽后抛出。"""

    pass
