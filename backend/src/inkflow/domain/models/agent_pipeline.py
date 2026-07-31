"""Agent 管线领域模型 — API 请求体与 YAML 解析后的统一载体 (spec §2.7, §3.2)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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


class PipelineExecuteRequest(BaseModel):
    """管线执行请求 DTO。"""

    project_id: uuid.UUID = Field(..., description="项目 ID")
    pipeline: str = Field(default="builtin:write_chapter", description="管线模板 ID")
    chapter_id: uuid.UUID | None = Field(default=None, description="章节 ID（可选）")
    variables: dict[str, str] = Field(default_factory=dict, description="Prompt 模板变量")
    role_overrides: dict[str, RoleOverride] | None = Field(default=None, description="角色覆盖")
