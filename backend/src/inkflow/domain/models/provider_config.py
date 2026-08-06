"""ProviderConfig 注册表领域模型 — Provider 配置实体与请求 DTO.

ProviderConfig 是持久化实体（对应 provider_configs 表，通过 SQLAlchemy ORM
映射），承载多 Provider 注册（名称唯一）与模型条目（chat/embedding 二值 +
角色用途标记）。ProviderModel 为单个模型条目，models 以 JSON 列存储（仿
ProjectORM.config）。ProviderConfigCreate / ProviderConfigUpdate 为请求 DTO：
Create 无 id/时间戳字段，Update 全字段可选（exclude_unset 语义，同 F1/F13）。

依据: specs/f19-gui/spec.md §8.2。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _validate_name(v: str) -> str:
    """共享的 provider 名校验：去空白后非空（§8.2 契约仅「非空白」）."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("Provider 名称不能为空")
    return stripped


def _validate_model_id(v: str) -> str:
    """共享的模型 ID 校验：去空白后非空."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("模型 ID 不能为空")
    return stripped


class ProviderModel(BaseModel):
    """单个模型条目（§8.2① models 元素契约）.

    Attributes:
        id: 模型标识（如 "gpt-4o"），必填非空白.
        type: 模型类型，仅 chat / embedding 二值.
        roles: 角色用途标记列表，默认空.
    """

    id: str
    type: Literal["chat", "embedding"]
    roles: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """验证模型 ID：去空白后非空."""
        return _validate_model_id(v)


class ProviderConfig(BaseModel):
    """Provider 注册表实体（§8.2① 字段全集）.

    Attributes:
        id: 主键（None = 未落库；repo.add 后由 DB 自增分配）.
        name: provider 名，唯一.
        base_url: OpenAI 兼容端点（None = 用 SDK/内置默认）.
        default_model: 默认模型字符串（provider/model 格式）.
        models: 模型条目列表（JSON 列存储）.
        max_retries: 重试次数，默认 3.
        timeout: 请求超时秒数，默认 120.
        created_at: 创建时间 (UTC)（服务层落库时填充）.
        updated_at: 最后更新时间 (UTC).
    """

    model_config = {"from_attributes": True}

    id: int | None = None
    name: str
    base_url: str | None = None
    default_model: str | None = None
    models: list[ProviderModel] = Field(default_factory=list)
    max_retries: int = 3
    timeout: int = 120
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProviderConfigCreate(BaseModel):
    """创建 Provider 请求 DTO — 无 id/created_at/updated_at 字段.

    name 必填，去空白后非空（空白拒绝，422 语义）；格式校验不在本批契约
    范围（YAGNI，§8.2①）。其余字段默认值与实体一致。
    """

    name: str
    base_url: str | None = None
    default_model: str | None = None
    models: list[ProviderModel] = Field(default_factory=list)
    max_retries: int = 3
    timeout: int = 120

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证 provider 名：去空白后非空."""
        return _validate_name(v)


class ProviderConfigUpdate(BaseModel):
    """更新 Provider 请求 DTO — 全字段可选（exclude_unset 语义，同 F1/F13）.

    None 值表示不修改（与未传入等价，服务层合并时剔除）。
    """

    name: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    models: list[ProviderModel] | None = None
    max_retries: int | None = None
    timeout: int | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证 provider 名：None（未提供）直接返回；否则复用共享校验."""
        return _validate_name(v) if v is not None else None
