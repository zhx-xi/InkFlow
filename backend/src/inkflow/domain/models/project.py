"""
项目/书籍领域模型 — 定义核心领域实体与数据传输对象.

Genre 枚举包含 11 种中文网络小说分类，
ProjectConfig 管理各项目的独立 AI 写作配置，
Project 是持久化实体，ProjectCreate/ProjectUpdate 是请求 DTO。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Genre(str, Enum):
    """中文网络小说分类枚举."""

    XUANHUAN = "玄幻"
    KEHUAN = "科幻"
    YANQING = "言情"
    XIANXIA = "仙侠"
    WUXIA = "武侠"
    DUSHI = "都市"
    LISHI = "历史"
    YOUXI = "游戏"
    XUANYI = "悬疑"
    QIHUAN = "奇幻"
    QITA = "其他"


class ProjectConfig(BaseModel):
    """项目 AI 写作配置，可序列化为 JSON 进行导入/导出.

    Attributes:
        model: 默认 AI 模型名称.
        agent_architect: 架构师 Agent 模型（可为 None，表示使用默认值）.
        agent_writer: 写手 Agent 模型.
        agent_auditor: 审阅 Agent 模型.
        agent_reviser: 修订 Agent 模型.
        temperature: 生成温度 (0.0 - 2.0).
        writing_style: 写作风格描述.
        extra: 扩展配置字典.
    """

    model: str = Field(default="gpt-4o", description="默认 AI 模型")
    agent_architect: str | None = None
    agent_writer: str | None = None
    agent_auditor: str | None = None
    agent_reviser: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    writing_style: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class Project(BaseModel):
    """项目/书籍领域实体.

    对应数据库中的 projects 表，通过 SQLAlchemy ORM 映射持久化。

    Attributes:
        id: 主键 UUID.
        name: 项目名称.
        genre: 小说分类.
        language: 写作语言（默认为 zh-CN）.
        target_words: 目标字数.
        config: AI 写作配置.
        is_deleted: 软删除标记.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    genre: Genre = Genre.QITA
    language: str = "zh-CN"
    target_words: int = 0
    config: ProjectConfig = Field(default_factory=ProjectConfig)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    """创建项目请求 DTO.

    Attributes:
        name: 项目名称，必填，1-100 字符，不能为空白.
        genre: 小说分类 默认为“其他”.
        language: 写作语言，默认为 zh-CN.
        target_words: 目标字数，默认为 0（不限）.
        config: AI 写作配置.
    """

    name: str
    genre: Genre = Genre.QITA
    language: str = "zh-CN"
    target_words: int = 0
    config: ProjectConfig = Field(default_factory=ProjectConfig)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证项目名称：去除前后空白后不能为空，长度 1-100 字符."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("项目名称不能为空")
        if len(stripped) > 100:
            raise ValueError("项目名称不能超过 100 个字符")
        return stripped


class ProjectUpdate(BaseModel):
    """更新项目请求 DTO — 所有字段均为可选项.

    只有传入的字段会被更新，未传入的字段保持不变.
    """

    name: str | None = None
    genre: Genre | None = None
    language: str | None = None
    target_words: int | None = None
    config: ProjectConfig | None = None
    is_deleted: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证项目名称：如果提供了值，去除空白后不能为空且不超过 100 字符."""
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("项目名称不能为空")
        if len(stripped) > 100:
            raise ValueError("项目名称不能超过 100 个字符")
        return stripped
