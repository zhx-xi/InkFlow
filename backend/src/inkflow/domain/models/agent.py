"""Agent 领域模型 — Agent 实体与请求 DTO.

Agent 是持久化实体（对应 agents 表，通过 SQLAlchemy ORM 映射），承载
能力白名单（tool_ids 工具目录 name 列表 / skill_ids skill 目录名列表，
ADR-039 #522）与自定义配置（名称唯一，去空白非空）。AgentCreate /
AgentUpdate 为请求 DTO；Create 无 id/builtin/时间戳字段，Update 全字段
可选（exclude_unset 语义，同 F1/F13）。

依据: specs/f39-multi-agent/spec.md §2.1。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _validate_name(v: str) -> str:
    """共享的 Agent 名称校验：去空白后非空（§2.1 契约仅「非空白」）。"""
    stripped = v.strip()
    if not stripped:
        raise ValueError("Agent 名称不能为空")
    return stripped


class Agent(BaseModel):
    """Agent 实体（§2.1 字段全集）.

    Attributes:
        id: 主键（None = 未落库；repo.add 后 DB 自增分配）.
        name: Agent 名（唯一，去空白非空）.
        description: 描述.
        icon: 图标（emoji 字符或图标键；空串 = 默认图标）.
        system_prompt: system prompt（内置 Agent 只读；自定义 Agent 可编辑）.
        tool_ids: 能力白名单，工具目录 name 列表.
        skill_ids: 能力白名单，skill 目录名列表（#522 文件系统真源引用）.
        model_override: 模型覆盖（provider/model 格式，None = 跟随默认）.
        temperature_override: 温度覆盖（None = 跟随默认）.
        builtin: 是否内置（True = 只读，出厂 seed；False = 用户自定义）.
        role_key: 链角色稳定标识（§5.7.1；None = 非链角色/未分配）.
        created_at: 创建时间 (UTC)（服务层落库时填充）.
        updated_at: 最后更新时间 (UTC).
    """

    model_config = {"from_attributes": True}

    id: int | None = None
    name: str
    description: str = ""
    icon: str = ""
    system_prompt: str = ""
    tool_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    model_override: str | None = None
    temperature_override: float | None = Field(default=None, ge=0.0, le=2.0)
    builtin: bool = False
    role_key: str | None = None
    """链角色稳定标识（§5.7.1；None = 非链角色/未分配，服务层自动分配不可变）."""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证 Agent 名称：去空白后非空."""
        return _validate_name(v)


class AgentCreate(BaseModel):
    """创建 Agent 请求 DTO — 无 id/builtin/created_at/updated_at 字段.

    name 必填，去空白后非空（空白拒绝，§7 语义）；其余字段默认值与实体
    一致（description=""/icon=""/system_prompt=""/tool_ids=[]/
    skill_ids=[]/model_override=None/temperature_override=None）。id 由
    repo 分配，builtin 服务层固定 False，时间戳服务层填充。
    """

    name: str
    description: str = ""
    icon: str = ""
    system_prompt: str = ""
    tool_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    model_override: str | None = None
    temperature_override: float | None = Field(default=None, ge=0.0, le=2.0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证 Agent 名称：去空白后非空."""
        return _validate_name(v)


class AgentUpdate(BaseModel):
    """更新 Agent 请求 DTO — 全字段可选（exclude_unset 语义，同 F1/F13）.

    None 值表示不修改（与未传入等价，服务层合并时剔除）；变更字段经
    服务层白名单/查重校验后以完整实体落库（updated_at 刷新、created_at
    保留）。
    """

    name: str | None = None
    description: str | None = None
    icon: str | None = None
    system_prompt: str | None = None
    tool_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    model_override: str | None = None
    temperature_override: float | None = Field(default=None, ge=0.0, le=2.0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证 Agent 名称：None（未提供）直接返回；否则复用共享校验."""
        return _validate_name(v) if v is not None else None
