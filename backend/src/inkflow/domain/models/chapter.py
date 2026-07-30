"""卷/章节领域模型 — 定义核心领域实体与数据传输对象.

ChapterStatus 枚举包含 4 种章节写作状态，
Volume 和 Chapter 是持久化实体，
VolumeCreate/VolumeUpdate/ChapterCreate/ChapterUpdate 是请求 DTO。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChapterStatus(StrEnum):
    """章节写作状态：草稿 → 写作中 → 审阅中 → 定稿."""

    DRAFT = "draft"
    WRITING = "writing"
    REVIEW = "review"
    FINAL = "final"


class StatusHistoryEntry(BaseModel):
    """单条状态变更记录."""

    from_status: ChapterStatus
    to_status: ChapterStatus
    at: datetime


class Volume(BaseModel):
    """卷领域实体."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    order_index: float = 0.0


class VolumeCreate(BaseModel):
    """创建卷请求 DTO."""

    title: str
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("卷标题不能为空")
        if len(stripped) > 200:
            raise ValueError("卷标题不能超过 200 个字符")
        return stripped


class VolumeUpdate(BaseModel):
    """更新卷请求 DTO."""

    title: str | None = None
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("卷标题不能为空")
        if len(stripped) > 200:
            raise ValueError("卷标题不能超过 200 个字符")
        return stripped


class Chapter(BaseModel):
    """章节领域实体."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    volume_id: uuid.UUID | None = None
    title: str
    content: str = ""
    status: ChapterStatus = ChapterStatus.DRAFT
    word_count: int = 0
    order_index: float = 0.0
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ChapterCreate(BaseModel):
    """创建章节请求 DTO."""

    title: str
    volume_id: uuid.UUID | None = None
    content: str = ""
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("章节标题不能为空")
        if len(stripped) > 500:
            raise ValueError("章节标题不能超过 500 个字符")
        return stripped


class ChapterUpdate(BaseModel):
    """更新章节请求 DTO."""

    title: str | None = None
    volume_id: uuid.UUID | None = None
    content: str | None = None
    status: ChapterStatus | None = None
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("章节标题不能为空")
        if len(stripped) > 500:
            raise ValueError("章节标题不能超过 500 个字符")
        return stripped
