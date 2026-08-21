"""#547 chat 消息服务 — 鸭子 repo 透传（add/list/conversations）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.chat_message import ChatMessage, ChatMessageCreate


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为存储层 int id（沿用 F1 `_to_int_id` 模式）。"""
    return value.int if isinstance(value, uuid.UUID) else int(value)


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

    async def archive_message(self, message_id: uuid.UUID) -> bool:
        """归档消息（软删 is_deleted=true）。repo.archive 收到 int 主键。"""
        if _to_int_id(message_id) > 2**63 - 1:
            return False
        return await self._repo.archive(_to_int_id(message_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 archive

    async def force_delete_message(self, message_id: uuid.UUID) -> bool:
        """真删消息。repo.force_delete 收到 int 主键。"""
        if _to_int_id(message_id) > 2**63 - 1:
            return False
        return await self._repo.force_delete(_to_int_id(message_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 force_delete

    async def restore_message(self, message_id: uuid.UUID) -> ChatMessage | None:
        """解除归档。repo.restore 收到 int 主键；返回 ChatMessage | None。"""
        if _to_int_id(message_id) > 2**63 - 1:
            return None
        return await self._repo.restore(_to_int_id(message_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 restore

    async def archive_conversation(self, project_id: uuid.UUID) -> int:
        """归档整项目活跃消息（会话级软删）。repo.archive_by_project 收到 int 主键。"""
        if _to_int_id(project_id) > 2**63 - 1:
            return 0
        return await self._repo.archive_by_project(_to_int_id(project_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 archive_by_project

    async def force_delete_conversation(self, project_id: uuid.UUID) -> int:
        """物理删除整项目消息（会话级真删）。repo.force_delete_by_project 收到 int 主键。"""
        if _to_int_id(project_id) > 2**63 - 1:
            return 0
        return await self._repo.force_delete_by_project(_to_int_id(project_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 force_delete_by_project
