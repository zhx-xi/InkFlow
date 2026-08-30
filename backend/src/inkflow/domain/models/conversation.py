"""#744 会话（线程）领域模型 -- conversations 表映射的领域实体与请求 DTO."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _validate_title(v: str = "") -> str:
    """会话标题校验：去空白，上限 200 字符（#770，对齐章节标题）。

    显式空串允许（repo 回读默认列值 "" 经 _conv_to_domain 显式传入）；
    纯空白输入拒绝（默认值 "" 不触发 validator）。
    """
    stripped = v.strip()
    if v and not stripped:
        raise ValueError("会话标题不能为空")
    if len(stripped) > 200:
        raise ValueError("会话标题不能超过 200 个字符")
    return stripped


class Conversation(BaseModel):
    """会话（线程）实体（对应 conversations 表）。"""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime
    is_deleted: bool = False
    delete_permission: str = "manual"  # "manual" | "ask_once" | "auto" (#766 阶段②)
    title: str = ""

    @field_validator("title")
    @classmethod
    def _validate_title_field(cls, v: str) -> str:
        return _validate_title(v)


class ConversationCreate(BaseModel):
    """创建会话请求 DTO（title 可选，上限 200，去空白）。"""

    project_id: uuid.UUID
    title: str = ""

    @field_validator("title")
    @classmethod
    def _validate_title_field(cls, v: str) -> str:
        return _validate_title(v)
