"""#547 chat 消息服务 — 鸭子 repo 透传（add/list/conversations）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.chat_message import ChatMessage, ChatMessageCreate


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChatMessageService:
    """chat 消息持久化服务（repo 为鸭子对象）。

    Args:
        repo: 鸭子 repo——add(message) -> ChatMessage；
            list_by_project(project_id, offset, limit) -> (list[ChatMessage], int)；
            list_conversations() -> list[dict]。
    """

    def __init__(self, *, repo: object) -> None:
        self._repo = repo

    async def add_message(self, data: ChatMessageCreate) -> ChatMessage:
        """构造实体（id=uuid4 + created_at=now UTC）→ repo.add → 返回落库实体。"""
        message = ChatMessage(
            id=uuid.uuid4(),
            project_id=data.project_id,
            role=data.role,
            content=data.content,
            intent=data.intent,
            created_at=_utcnow(),
        )
        created: ChatMessage = await self._repo.add(message)  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 add
        return created

    async def list_messages(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[ChatMessage], int]:
        """项目消息列表（位置透传 repo.list_by_project）。"""
        items, total = await self._repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 list_by_project
            project_id, offset, limit
        )
        return items, total

    async def list_conversations(self) -> list[dict[str, Any]]:
        """会话页聚合（repo 聚合结果原样透传）。"""
        return await self._repo.list_conversations()  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 list_conversations
