"""#547/#744 chat 消息服务 -- 鸭子 repo 透传（add/list/conversations 线程级）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.chat_message import ChatMessage, ChatMessageCreate
from inkflow.domain.models.conversation import Conversation


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为存储层 int id（沿用 F1 `_to_int_id` 模式）。"""
    return value.int if isinstance(value, uuid.UUID) else int(value)


def _is_random_overflow(value: uuid.UUID) -> bool:
    """#578/#744 会话级溢出预检：随机 uuid4 超出 SQLite 64 位 INTEGER 范围。

    会话级删除/恢复收到的 conversation_id 来自路由 path（任意 128 位 UUID）。
    随机 uuid4（version==4 且 int > 2**63-1）必然不存在于 conversations 表
    （autoincrement 生成的小 int 线程 id），短路返回「不存在」语义，不调用 repo
    （避免 SQLite OverflowError 500）。固定 version-5 测试 UUID 视为合法 id 透传。
    """
    return value.version == 4 and value.int > 2**63 - 1


class ChatMessageService:
    """chat 消息持久化服务（repo 为鸭子对象）。

    Args:
        repo: 鸭子 repo——提供 add(message) -> ChatMessage；
            list_by_conversation(conversation_id, offset, limit) -> (list, int)；
            list_conversations(include_deleted) -> list[dict]；
            get_active_conversation / create_conversation / archive /
            force_delete / restore / archive_conversation / force_delete_conversation /
            restore_conversation。
    """

    def __init__(self, *, repo: object) -> None:
        self._repo = repo

    async def add_message(self, data: ChatMessageCreate) -> ChatMessage:
        """构造实体（id=uuid4 + created_at=now UTC）-> repo.add -> 返回落库实体。

        data.conversation_id 为空时经 get_or_create_conversation 自动解析
        （归档后无活跃线程 -> 自动新建）。
        """
        conversation_id = data.conversation_id
        if conversation_id is None:
            conversation_id = (await self.get_or_create_conversation(data.project_id)).id
        message = ChatMessage(
            id=uuid.uuid4(),
            project_id=data.project_id,
            conversation_id=conversation_id,
            role=data.role,
            content=data.content,
            intent=data.intent,
            created_at=_utcnow(),
        )
        created: ChatMessage = await self._repo.add(message)  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 add
        return created

    async def get_or_create_conversation(self, project_id: uuid.UUID) -> Conversation:
        """有活跃线程 -> 复用；无 -> 新建（#744 归档后开新线程）。"""
        active = await self._repo.get_active_conversation(project_id)  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 get_active_conversation
        if active is not None:
            return active  # type: ignore[no-any-return]  # 鸭子类型：repo 返回领域 Conversation
        return await self._repo.create_conversation(project_id)  # type: ignore[attr-defined, no-any-return]  # 鸭子类型：repo 提供 create_conversation

    async def create_conversation(self, project_id: uuid.UUID, title: str = "") -> Conversation:
        """直接创建新线程（#744 归档后开新线程：不复用旧 conversation；title 可选，#770）。"""
        created: Conversation = await self._repo.create_conversation(project_id, title)  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 create_conversation
        return created

    async def rename_conversation(self, conversation_id: uuid.UUID, title: str) -> bool:
        """会话改名（#770）：溢出 uuid4 短路「不存在」，否则透传 repo.rename_conversation。"""
        if _is_random_overflow(conversation_id):
            return False
        renamed: bool = await self._repo.rename_conversation(_to_int_id(conversation_id), title)  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 rename_conversation
        return renamed

    async def list_messages(
        self, conversation_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[ChatMessage], int]:
        """项目级消息列表（#748 agent 聊天历史；位置透传 repo.list_by_project）。"""
        items, total = await self._repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 list_by_project
            conversation_id, offset, limit
        )
        return items, total

    async def list_messages_by_conversation(
        self, conversation_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[ChatMessage], int]:
        """线程消息列表（位置透传 repo.list_by_conversation）。"""
        items, total = await self._repo.list_by_conversation(  # type: ignore[attr-defined]  # 鸭子类型：repo 提供 list_by_conversation
            conversation_id, offset, limit
        )
        return items, total

    async def list_conversations(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        """会话页聚合（repo 聚合结果原样透传；include_deleted 控制是否含已归档）。"""
        return await self._repo.list_conversations(include_deleted=include_deleted)  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 list_conversations

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

    async def archive_conversation(self, conversation_id: uuid.UUID) -> bool:
        """线程级归档（软删 conversation + 其消息）。repo 收到 int 主键。"""
        if _is_random_overflow(conversation_id):
            return False
        return await self._repo.archive_conversation(_to_int_id(conversation_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 archive_conversation

    async def force_delete_conversation(self, conversation_id: uuid.UUID) -> bool:
        """线程级真删（删消息 + 会话行）。repo 收到 int 主键。"""
        if _is_random_overflow(conversation_id):
            return False
        return await self._repo.force_delete_conversation(_to_int_id(conversation_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 force_delete_conversation

    async def restore_conversation(self, conversation_id: uuid.UUID) -> bool:
        """线程级恢复（取消归档 conversation + 其消息）。repo 收到 int 主键。"""
        if _is_random_overflow(conversation_id):
            return False
        return await self._repo.restore_conversation(_to_int_id(conversation_id))  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 restore_conversation

    async def update_delete_permission(
        self, *, conversation_id: uuid.UUID, delete_permission: str
    ) -> dict | None:
        """#766 阶段③：更新线程删除授权；不存在返回 None（404 语义）。"""
        return await self._repo.update_delete_permission(  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 提供 update_delete_permission
            conversation_id=conversation_id,
            delete_permission=delete_permission,
        )
