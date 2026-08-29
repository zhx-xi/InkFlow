"""角色管理领域模型 — 角色/分组/关系实体与提取相关 DTO.

Character / CharacterGroup / CharacterRelation 是持久化实体（对应
characters / character_groups / character_relations 表，通过 SQLAlchemy
ORM 映射），CharacterCreate / CharacterUpdate / CharacterRelationCreate
是请求 DTO，ExtractedCharacter / ExtractedRelation 是 LLM 提取结果的
schema 校验模型，CharacterExtractRequest / CharacterExtractionResult
是提取服务的入参/出参。

依据: specs/f9-character/spec.md §2.5/§2.6。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _validate_name(v: str) -> str:
    """共享的角色名校验：去空白后非空且不超过 50 字符.

    Args:
        v: 原始输入名称.

    Returns:
        去空白后的角色名.

    Raises:
        ValueError: 名称为空/纯空白，或超过 50 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError("角色名不能为空")
    if len(stripped) > 50:
        raise ValueError("角色名不能超过 50 个字符")
    return stripped


def _validate_relation_type(v: str) -> str:
    """共享的关系类型校验：去空白后非空且不超过 20 字符.

    Args:
        v: 原始输入关系类型.

    Returns:
        去空白后的关系类型.

    Raises:
        ValueError: 关系类型为空/纯空白，或超过 20 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError("关系类型不能为空")
    if len(stripped) > 20:
        raise ValueError("关系类型不能超过 20 个字符")
    return stripped


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


class Character(BaseModel):
    """角色领域实体 — 对应 characters 表.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        name: 角色名；项目内唯一（全唯一索引，见 spec §2.4）.
        personality: 性格描述.
        background: 背景设定.
        goals: 目标/动机.
        brief: 一句话简介（F6 上下文轻量化注入用，未填时降级 personality）.
        group_ids: 所属角色分组 UUID 列表（可为空；N:M，v1.1 #701）.
        extra: 扩展属性字典.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    personality: str = ""
    background: str = ""
    goals: str = ""
    brief: str = ""  # v1.1（#593）：一句话简介，F6 上下文轻量化注入
    group_ids: list[uuid.UUID] = []
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CharacterCreate(BaseModel):
    """创建角色请求 DTO.

    Attributes:
        project_id: 所属项目 UUID，必填.
        name: 角色名，必填，1-50 字符，去空白.
        personality: 性格描述，默认为空串.
        background: 背景设定，默认为空串.
        goals: 目标/动机，默认为空串.
        brief: 一句话简介，默认为空串，≤ 500 字符（去空白）.
        group_ids: 所属角色分组 UUID 列表（可为空；N:M，v1.1 #701）.
        extra: 扩展属性字典（如 role_rank/groups），默认为空 dict.
    """

    project_id: uuid.UUID
    name: str
    personality: str = ""
    background: str = ""
    goals: str = ""
    brief: str = ""
    group_ids: list[uuid.UUID] = []
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证角色名：去空白后非空且不超过 50 字符."""
        return _validate_name(v)

    @field_validator("brief")
    @classmethod
    def validate_brief(cls, v: str) -> str:
        """v1.1（#593）：brief 去空白且不超过 500 字符（F6 注入轻量化）."""
        stripped = v.strip()
        if len(stripped) > 500:
            raise ValueError("角色简介不能超过 500 个字符")
        return stripped


class CharacterUpdate(BaseModel):
    """更新角色请求 DTO — 所有字段均为可选项（exclude_unset 语义，同 F1）.

    group_ids: None 表示不修改；[] 表示清空全部分组；[uuid1, uuid2] 表示全量替换。
    只有传入的字段会被更新，未传入的字段保持不变。
    extra: 传 dict 整体替换；不传该字段表示不修改（exclude_unset 语义）。
    """

    name: str | None = None
    personality: str | None = None
    background: str | None = None
    goals: str | None = None
    brief: str | None = None  # v1.1（#593）
    group_ids: list[uuid.UUID] | None = None
    extra: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证角色名：None（未提供/显式清除）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_name(v)


class CharacterGroup(BaseModel):
    """角色分组领域实体 — 对应 character_groups 表.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        name: 分组名称.
        description: 分组描述.
        sort_order: 排序权重（小在前）.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str = ""
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class CharacterRelation(BaseModel):
    """角色关系领域实体 — 关系图谱的有向边，对应 character_relations 表.

    关系中 (project_id, from_character_id, to_character_id,
    relation_type) 唯一（全唯一索引，见 spec §2.4）。

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        from_character_id: 关系起点角色 UUID.
        to_character_id: 关系终点角色 UUID.
        relation_type: 关系类型（自由文本，1-20 字符）.
        description: 关系描述.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    from_character_id: uuid.UUID
    to_character_id: uuid.UUID
    relation_type: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class CharacterRelationCreate(BaseModel):
    """创建关系请求 DTO — from 端由路径参数（所属角色）决定.

    Attributes:
        to_character_id: 关系终点角色 UUID，必填.
        relation_type: 关系类型，必填，1-20 字符，去空白.
        description: 关系描述，可选，≤ 500 字符.
    """

    to_character_id: uuid.UUID
    relation_type: str
    description: str = ""

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        """验证关系类型：去空白后非空且不超过 20 字符."""
        return _validate_relation_type(v)


class ExtractedCharacter(BaseModel):
    """LLM 提取出的单个角色（schema 校验用）.

    name 非法（空/超长）时该条被跳过并记录 warning，不影响其余条目落库。
    """

    name: str
    personality: str | None = None
    background: str | None = None
    goals: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证角色名：去空白后非空且不超过 50 字符."""
        return _validate_name(v)


class ExtractedRelation(BaseModel):
    """LLM 提取出的关系（schema 校验用；名称引用，落库前解析为 id）.

    Attributes:
        from_name: 关系起点角色名.
        to_name: 关系终点角色名.
        relation_type: 关系类型，1-20 字符，去空白.
        description: 关系描述，可空.
    """

    from_name: str
    to_name: str
    relation_type: str
    description: str | None = None

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        """验证关系类型：去空白后非空且不超过 20 字符."""
        return _validate_relation_type(v)


class CharacterExtractRequest(BaseModel):
    """角色提取请求.

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


class CharacterExtractionResult(BaseModel):
    """角色提取结果 — 合并落库后的报告.

    Attributes:
        created: 本次新建的角色列表.
        updated: 本次更新（同名合并）的角色列表.
        relations_created: 本次新建的关系列表.
        relations_updated: 本次更新（同键合并）的关系列表.
        warnings: 提取/合并过程中的警告信息（跳过条目、不可解析引用等）.
        model: 实际使用的模型.
    """

    created: list[Character]
    updated: list[Character]
    relations_created: list[CharacterRelation]
    relations_updated: list[CharacterRelation]
    warnings: list[str]
    model: str
