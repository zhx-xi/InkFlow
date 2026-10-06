"""Agent 管线领域模型 — API 请求体与 YAML 解析后的统一载体 (spec §2.7, §3.2)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from inkflow.domain.models.context import ContextOverride
from inkflow.domain.ports.agent_pipeline import PipelineContext as PipelineContext
from inkflow.domain.ports.agent_pipeline import PipelineStage


class RoleOverride(BaseModel):
    """角色覆盖配置 — 单次执行中覆盖角色参数（优先级最高）。"""

    prompt: str | None = Field(default=None, description="覆盖 system_prompt")
    model: str | None = Field(default=None, description="覆盖模型")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="覆盖温度")


class PipelineConfig(BaseModel):
    """管线配置 — 用于 API 请求体和 YAML 解析。"""

    name: str = Field(..., description="管线名称")
    description: str = Field(default="", description="描述")
    stages: list[PipelineStage] = Field(..., description="阶段定义列表")
    source: Literal["builtin", "yaml"] = Field(default="builtin", description="管线来源")
    version: int = Field(default=1, ge=1, description="配置版本")

    @field_validator("stages")
    @classmethod
    def validate_stages_not_empty(cls, v: list[PipelineStage]) -> list[PipelineStage]:
        """管线至少需要一个阶段，且阶段 id 全局唯一。"""
        if not v:
            raise ValueError("管线至少需要一个阶段")
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("阶段 id 不能重复")
        return v


class SupervisorExecuteConfig(BaseModel):
    """Supervisor 模式执行配置。"""

    max_steps: int = Field(default=30, ge=1, le=100, description="路由步数上限（振荡护栏）")
    max_consecutive: int = Field(
        default=3,
        ge=1,
        le=10,
        description="同角色连续调度上限（振荡护栏）",
    )
    hitl_roles: list[str] = Field(
        default_factory=list,
        description="HITL 确认角色列表（这些角色执行前 interrupt 等待确认；空=无 HITL）",
    )
    fallback_on_error: bool = Field(
        default=True,
        description="异常/超限时回退固定链（deterministic 兜底）；False = 直接失败",
    )
    supervisor_prompt: str | None = Field(
        default=None, description="supervisor 决策 system prompt 覆盖（默认模板）"
    )


class PipelineExecuteRequest(BaseModel):
    """管线执行请求 DTO。"""

    project_id: uuid.UUID = Field(..., description="项目 ID")
    pipeline: str = Field(default="builtin:write_chapter", description="管线模板 ID")
    chapter_id: uuid.UUID | None = Field(default=None, description="章节 ID（可选）")
    variables: dict[str, str] = Field(default_factory=dict, description="Prompt 模板变量")
    role_overrides: dict[str, RoleOverride] | None = Field(default=None, description="角色覆盖")
    stages: list[str] | None = Field(
        default=None,
        description="自定义 stage role_key 序列（#1475；与 pipeline_config 互斥，仅 static 模式）",
    )
    pipeline_config: PipelineConfig | None = Field(
        default=None,
        description="自定义管线配置（#1475；与 stages 互斥，仅 static 模式）",
    )
    mode: Literal["static", "supervisor"] = Field(
        default="static",
        description="执行模式：static=既有静态 DAG（默认）；supervisor=动态路由编排",
    )
    supervisor: SupervisorExecuteConfig | None = Field(
        default=None, description="supervisor 模式配置（mode=supervisor 时生效）"
    )
    override: ContextOverride | None = Field(
        default=None,
        description="上下文注入勾选通道；None=全注入（默认），显式空列表=该源不注入",
    )

    @model_validator(mode="after")
    def validate_custom_stages(self) -> PipelineExecuteRequest:
        """#1475 自定义 stage 通道约束（spec §5.8.1）：互斥 / 仅 static / 非空。

        违反 → `ValidationError`（API 422，不经服务层）：`stages` 与 `pipeline_config`
        互斥；二者仅 `mode="static"` 可用（supervisor 角色池来自模板 stages）；
        `stages` 给定则须非空且元素去空白后非空串。内置请求（两字段均 None）零影响。
        """
        if self.stages is not None and self.pipeline_config is not None:
            raise ValueError("stages 与 pipeline_config 互斥")
        if self.mode == "supervisor" and (
            self.stages is not None or self.pipeline_config is not None
        ):
            raise ValueError("自定义 stage 仅支持 static 模式")
        if self.stages is not None and (
            not self.stages or any(not segment.strip() for segment in self.stages)
        ):
            raise ValueError("stages 不能为空")
        return self
