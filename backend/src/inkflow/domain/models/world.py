"""世界观管理领域模型 — 条目实体与提取相关 DTO.

WorldSetting 是持久化实体（对应 world_settings 表，通过 SQLAlchemy ORM
映射），WorldCreate / WorldUpdate 是请求 DTO，ExtractedWorldSetting 是
LLM 提取结果的 schema 校验模型，WorldExtractRequest / WorldExtractionResult
是提取服务的入参/出参。

依据: specs/f10-world-service/spec.md §2.5/§2.6。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _validate_name(v: str) -> str:
    """共享的条目名校验：去空白后非空且不超过 50 字符.

    Args:
        v: 原始输入名称.

    Returns:
        去空白后的条目名.

    Raises:
        ValueError: 名称为空/纯空白，或超过 50 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError("条目名不能为空")
    if len(stripped) > 50:
        raise ValueError("条目名不能超过 50 个字符")
    return stripped


def _validate_category(v: str) -> str:
    """共享的类别校验：去空白且不超过 50 字符（空串 = 未分类，允许）.

    Args:
        v: 原始输入类别.

    Returns:
        去空白后的类别.

    Raises:
        ValueError: 类别超过 50 字符.
    """
    stripped = v.strip()
    if len(stripped) > 50:
        raise ValueError("类别不能超过 50 个字符")
    return stripped


def _validate_content(v: str) -> str:
    """共享的内容校验：不超过 20000 字符（不强制去空白，正文可能含排版空白）.

    Args:
        v: 原始输入内容.

    Returns:
        原样返回的内容.

    Raises:
        ValueError: 内容超过 20000 字符.
    """
    if len(v) > 20000:
        raise ValueError("内容不能超过 20000 个字符")
    return v


def _validate_text(v: str) -> str:
    """共享的提取文本校验：去空白后非空且不超过 50000 字符.

    Args:
        v: 原始输入文本.

    Returns:
        去空白后的提取文本.

    Raises:
        ValueError: 文本为空/纯空白，或超过 50000 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError("提取文本不能为空")
    if len(stripped) > 50000:
        raise ValueError("提取文本不能超过 50000 个字符")
    return stripped


class WorldSetting(BaseModel):
    """世界观条目领域实体 — 对应 world_settings 表.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        name: 条目名；同级（project_id, parent_id）内活动条目唯一
            （partial unique，见 spec §2.4）.
        parent_id: 父地点 UUID；None = 顶层（F35 新增）.
        category: 类别（建议值：设定/规则/约束/组织/地理/种族/文化/科技/
            魔法体系；自由文本，受控词表归 F14）；空串 = 未分类.
        content: 条目内容/详细设定.
        extra: 扩展属性字典（来源章节、标签、别名等 Phase 2+ 字段预留）.
        is_deleted: 软删除标记.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None  # ← F35 新增：父地点；None = 顶层
    category: str = ""
    content: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class WorldCreate(BaseModel):
    """创建世界观条目请求 DTO.

    Attributes:
        project_id: 所属项目 UUID，必填.
        name: 条目名，必填，1-50 字符，去空白.
        parent_id: 父地点 UUID；None = 顶层（F35 新增）.
        category: 类别，默认为空串（未分类），≤ 50 字符，去空白.
        content: 条目内容，默认为空串，≤ 20000 字符.
    """

    project_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None  # ← F35 新增（None = 顶层）
    category: str = ""
    content: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证条目名：去空白后非空且不超过 50 字符."""
        return _validate_name(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """验证类别：去空白且不超过 50 字符（空串合法）."""
        return _validate_category(v)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """验证内容：不超过 20000 字符."""
        return _validate_content(v)


class WorldUpdate(BaseModel):
    """更新世界观条目请求 DTO — 所有字段均为可选项（exclude_unset 语义，同 F1）.

    category: None 表示不修改；"" 表示清除类别（置为未分类）。
    只有传入的字段会被更新，未传入的字段保持不变。

    F35 parent_id 例外：与 category/content 的 None=不修改不同，parent_id
    出现即更新（service 用 model_fields_set 判断）：null=置顶、非 null=挂接。
    """

    name: str | None = None
    category: str | None = None
    content: str | None = None
    parent_id: uuid.UUID | None = None  # ← F35 新增

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证条目名：None（未提供）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_name(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        """验证类别：None（不修改）直接返回；""（清除类别）合法；否则复用共享校验."""
        if v is None:
            return v
        return _validate_category(v)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str | None) -> str | None:
        """验证内容：None（不修改）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_content(v)


class ExtractedWorldSetting(BaseModel):
    """LLM 提取出的单个世界观条目（schema 校验用）.

    name 非法（空/超长）时该条被跳过并记录 warning，不影响其余条目落库。
    category/content 为 None 或空串时落库为空串（未分类/无内容）。
    """

    name: str
    category: str | None = None
    content: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证条目名：去空白后非空且不超过 50 字符."""
        return _validate_name(v)


class WorldExtractRequest(BaseModel):
    """世界观信息提取请求.

    Attributes:
        project_id: 所属项目 UUID.
        text: 待提取文本，必填，去空白非空，≤ 50000 字符.
        model: 覆盖项目默认模型（格式 provider/model_name）；None 用默认.
    """

    project_id: uuid.UUID
    text: str
    model: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """验证提取文本：去空白后非空且不超过 50000 字符."""
        return _validate_text(v)


class WorldExtractionResult(BaseModel):
    """世界观提取结果 — 合并落库后的报告.

    （无 relations 字段：F10 不建条目关联表，见 spec §2.3）

    Attributes:
        created: 本次新建的世界观条目列表.
        updated: 本次更新（同名合并）的世界观条目列表.
        warnings: 提取/合并过程中的警告信息（跳过条目等）.
        model: 实际使用的模型.
    """

    created: list[WorldSetting]
    updated: list[WorldSetting]
    warnings: list[str]
    model: str
