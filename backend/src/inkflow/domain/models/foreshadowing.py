"""伏笔管理领域模型 — 伏笔档案实体与请求 DTO.

Foreshadowing 是持久化实体（对应 foreshadowings 表，通过 SQLAlchemy ORM
映射），承载伏笔生命周期（open → resolved，§2.4 状态机）。ForeshadowingCreate /
ForeshadowingUpdate 是请求 DTO：Create 无 status 字段（创建即 open），Update
所有字段可选（exclude_unset 语义），其中 event_id 具有「None = 不修改，
\"\" = 解除事件挂接」双语义，与 F11 arc_id / F12 time_value 同构。

依据: specs/f13-foreshadowing-service/spec.md §2.5。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ForeshadowingStatus(StrEnum):
    """伏笔生命周期状态（§2.4 状态机）.

    Attributes:
        OPEN: 已埋设未回收（进入 F6 注入集合）.
        RESOLVED: 已回收（不注入；档案保留）.
    """

    OPEN = "open"
    RESOLVED = "resolved"


def _validate_title(v: str) -> str:
    """共享的伏笔名校验：去空白后非空且不超过 100 字符.

    Args:
        v: 原始输入伏笔名.

    Returns:
        去空白后的伏笔名.

    Raises:
        ValueError: 伏笔名为空/纯空白，或超过 100 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError("伏笔名不能为空")
    if len(stripped) > 100:
        raise ValueError("伏笔名不能超过 100 个字符")
    return stripped


def _validate_description(v: str) -> str:
    """共享的描述校验：不超过 5000 字符（不强制去空白）.

    Args:
        v: 原始输入描述.

    Returns:
        原样返回的描述.

    Raises:
        ValueError: 描述超过 5000 字符.
    """
    if len(v) > 5000:
        raise ValueError("伏笔描述不能超过 5000 个字符")
    return v


def _validate_priority(v: int) -> int:
    """共享的优先级校验：0-100 闭区间.

    Args:
        v: 原始输入优先级.

    Returns:
        原样返回的优先级.

    Raises:
        ValueError: 优先级超出 [0, 100] 范围.
    """
    if not 0 <= v <= 100:
        raise ValueError("优先级必须在 0-100 之间")
    return v


def _validate_location(v: str) -> str:
    """共享的埋设位置校验：去空白且不超过 200 字符（空串 = 未记录，允许）.

    Args:
        v: 原始输入埋设位置.

    Returns:
        去空白后的埋设位置.

    Raises:
        ValueError: 埋设位置超过 200 字符.
    """
    stripped = v.strip()
    if len(stripped) > 200:
        raise ValueError("埋设位置不能超过 200 个字符")
    return stripped


class Foreshadowing(BaseModel):
    """伏笔档案领域实体. 对应 foreshadowings 表.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        title: 伏笔名（如「林晚的身世」）；项目内活动伏笔唯一（服务层保证）.
        description: 伏笔详情（埋设内容、预期回收方式）.
        priority: 注入优先级（大者先注入；F6 dynamic 层排序契约的键）.
        status: 生命周期状态（open/resolved）.
        location: 埋设位置自由文本（空 = 未记录；不挂事件时仍可写「第 3 章」）.
        event_id: F12 时间线事件锚点（None = 未挂接；叙事位置从事件获取）.
        resolved_at: 回收时间 (UTC)（仅状态迁移维护）.
        extra: 扩展属性字典（标签、关联角色名等 Phase 2+ 字段预留）.
        is_deleted: 软删除标记.
        created_at: 创建时间 (UTC).
        updated_at: 最后更新时间 (UTC).
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str = ""
    priority: int = 50
    status: ForeshadowingStatus = ForeshadowingStatus.OPEN
    location: str = ""  # 埋设位置自由文本（空 = 未记录；不挂事件时仍可写「第 3 章」）
    event_id: uuid.UUID | None = None  # F12 时间线事件锚点（None = 未挂接；叙事位置从事件获取）
    resolved_at: datetime | None = None  # 回收时间（仅状态迁移维护）
    extra: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class ForeshadowingCreate(BaseModel):
    """创建伏笔请求 DTO — status 不可传（创建即 open，回收走 resolve 端点）.

    Attributes:
        project_id: 所属项目 UUID，必填.
        title: 伏笔名，必填，1-100 字符，去空白.
        description: 伏笔详情，默认为空串，≤ 5000 字符.
        priority: 注入优先级，默认 50，0-100.
        location: 埋设位置，默认为空串，≤ 200 字符，去空白.
        event_id: F12 事件锚点（None = 不挂接；存在性/同项目校验在服务层，§2.1）.
    """

    project_id: uuid.UUID
    title: str
    description: str = ""
    priority: int = 50
    location: str = ""
    event_id: uuid.UUID | None = None  # F12 事件锚点（None = 不挂接；存在性/同项目校验在服务层）

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """验证伏笔名：去空白后非空且不超过 100 字符."""
        return _validate_title(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证伏笔详情：不超过 5000 字符."""
        return _validate_description(v)

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        """验证注入优先级：0-100 闭区间."""
        return _validate_priority(v)

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str) -> str:
        """验证埋设位置：去空白且不超过 200 字符（空串合法）."""
        return _validate_location(v)


class ForeshadowingUpdate(BaseModel):
    """更新伏笔请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    location: None 表示不修改；\"\" 表示清除埋设位置（置为未记录）.
    event_id: None 表示不修改；\"\" 表示解除事件挂接（置为 None）.
    status/resolved_at 不可通过本 DTO 修改（状态迁移走 resolve/reopen 端点，§2.4）.
    只有传入的字段会被更新，未传入的字段保持不变.
    """

    title: str | None = None
    description: str | None = None
    priority: int | None = None
    location: str | None = None
    event_id: uuid.UUID | str | None = None  # str "" = 解除事件挂接

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        """验证伏笔名：None（未提供）直接返回；否则复用共享校验."""
        return _validate_title(v) if v is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证伏笔详情：None（不修改）直接返回；否则复用共享校验."""
        return _validate_description(v) if v is not None else None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int | None) -> int | None:
        """验证注入优先级：None（不修改）直接返回；否则复用共享校验."""
        return _validate_priority(v) if v is not None else None

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str | None) -> str | None:
        """验证埋设位置：None（不修改）直接返回；否则复用共享校验."""
        return _validate_location(v) if v is not None else None

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, v: uuid.UUID | str | None) -> uuid.UUID | str | None:
        """验证事件锚点：None（不修改）与 \"\"（解除挂接）合法；非空字符串拒绝.

        event_id 双语义与 F11 arc_id / F12 time_value 同构：合法 UUID 字符串
        会被 Pydantic 先行解析为 uuid.UUID，此处仅拦截残余的非空字符串.
        """
        if isinstance(v, str):
            if v != "":
                raise ValueError("解除事件挂接请传空字符串")
            return v
        return v
