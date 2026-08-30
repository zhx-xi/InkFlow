"""#547 chat 消息领域模型 — chat_messages 表映射的领域实体与请求 DTO."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _validate_content(v: str) -> str:
    stripped = v.strip()
    if not stripped:
        raise ValueError("chat 消息内容不能为空")
    if len(stripped) > 10000:
        raise ValueError("chat 消息内容不能超过 10000 字符")
    return stripped


class ChatMessage(BaseModel):
    """chat 消息实体（对应 chat_messages 表）。"""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "ai"]
    content: str
    intent: Literal["content", "conversation"] | None = None
    created_at: datetime
    is_deleted: bool = False


class ChatMessageCreate(BaseModel):
    """创建 chat 消息请求 DTO（content 校验；role 枚举）。"""

    project_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    role: Literal["user", "ai"]
    content: str
    intent: Literal["content", "conversation"] | None = None

    _content = field_validator("content")(_validate_content)
