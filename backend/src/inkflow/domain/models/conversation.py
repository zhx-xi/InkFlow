"""#744 会话（线程）领域模型 -- conversations 表映射的领域实体与请求 DTO."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Conversation(BaseModel):
    """会话（线程）实体（对应 conversations 表）。"""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime
    is_deleted: bool = False
    delete_permission: str = "manual"  # "manual" | "ask_once" | "auto" (#766 阶段②)


class ConversationCreate(BaseModel):
    """创建会话请求 DTO。"""

    project_id: uuid.UUID
