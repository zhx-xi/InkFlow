"""AgentTemplate 领域模型 — 模板实体与请求 DTO.

AgentTemplate 是持久化实体（对应 agent_templates 表，通过 SQLAlchemy ORM
映射），承载引用式模板配置（名称唯一）与四角色子模型（architect/writer/
auditor/reviser）。RoleTemplate 为单个角色子模型，roles 以 JSON 列存储
（镜像 ProjectORM.config 风格）。AgentTemplateCreate / AgentTemplateUpdate
为请求 DTO；Create 无 id/时间戳字段，Update 全字段可选（exclude_unset
语义，同 F1/F13）。

依据: specs/f19-gui/spec.md §9.2。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _validate_name(v: str) -> str:
    """共享的模板名称校验：去空白后非空（§9.2 契约仅「非空白」）."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("模板名称不能为空")
    return stripped


class RoleTemplate(BaseModel):
    """单个角色子模型（§9.2 roles 元素契约）.

    Attributes:
        model: 角色模型（None = 跟随默认）.
        temperature: 独立温度（None = 跟随默认，显式语义，spec §9.2.3）.
        enabled: False = 该角色 model 不覆盖，用默认模型（spec §9.2.5）.
    """

    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    enabled: bool = True


class AgentTemplate(BaseModel):
    """模板实体（§9.2 字段全集）.

    Attributes:
        id: 主键（None = 未落库；repo.add 后由 DB 自增分配）.
        name: 模板名称，唯一.
        description: 描述.
        main_model: 主模型（None = 跟随默认）.
        default_temperature: 全角色兜底温度（None = 跟随默认）.
        roles: 四角色子模型 dict（JSON 列存储；缺省 key 的读取返回默认
            RoleTemplate() 属装配层语义，模型层不提供访问器）.
        default_words: 章节默认字数.
        is_default: 是否当前默认模板（单例，repo 层保证）.
        created_at: 创建时间 (UTC)（服务层落库时填充）.
        updated_at: 最后更新时间 (UTC).
    """

    model_config = {"from_attributes": True}

    id: int | None = None
    name: str
    description: str = ""
    main_model: str | None = None
    default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    roles: dict[str, RoleTemplate] = Field(default_factory=dict)
    default_words: int | None = Field(default=None, ge=1000, le=10_000_000)
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证模板名称：去空白后非空."""
        return _validate_name(v)


class AgentTemplateCreate(BaseModel):
    """创建模板请求 DTO — 无 id/is_default/created_at/updated_at 字段.

    name 必填，去空白后非空（空白拒绝，422 语义）；其余字段默认值与实体
    一致（description=""/main_model=None/default_temperature=None/roles={}/
    default_words=None）。id 由 repo 分配，is_default 服务层固定 False，
    时间戳服务层填充。
    """

    name: str
    description: str = ""
    main_model: str | None = None
    default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    roles: dict[str, RoleTemplate] = Field(default_factory=dict)
    default_words: int | None = Field(default=None, ge=1000, le=10_000_000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证模板名称：去空白后非空."""
        return _validate_name(v)


class AgentTemplateUpdate(BaseModel):
    """更新模板请求 DTO — 全字段可选（exclude_unset 语义，同 F1/F13）.

    None 值表示不修改（与未传入等价，服务层合并时剔除）；is_default
    允许显式 False 取消默认（PATCH {"is_default": false} → exclude_unset
    含 False，服务层应用）。
    """

    name: str | None = None
    description: str | None = None
    main_model: str | None = None
    default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    roles: dict[str, RoleTemplate] | None = None
    default_words: int | None = Field(default=None, ge=1000, le=10_000_000)
    is_default: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证模板名称：None（未提供）直接返回；否则复用共享校验."""
        return _validate_name(v) if v is not None else None
