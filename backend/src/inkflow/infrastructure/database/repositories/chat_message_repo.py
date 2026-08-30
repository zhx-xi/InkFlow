"""#547/#744 chat 消息仓储 -- SQLite 实现（int<->UUID 转换在 repo 层）。

#744 会话多实例：add 绑定 conversation_id + project_id；新增会话级
create_conversation / get_active_conversation / list_by_conversation /
list_conversations（按 conversation 分组）/ archive_conversation /
force_delete_conversation / restore_conversation。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.chat_message import ChatMessage
from inkflow.domain.models.conversation import Conversation
from inkflow.infrastructure.database.models.chat_message import ChatMessageORM
from inkflow.infrastructure.database.models.conversation import ConversationORM
from inkflow.infrastructure.database.models.project import ProjectORM


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite DateTime 读回为 naive（SQLite 无时区），统一补 UTC tzinfo."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_int(value: int | uuid.UUID) -> int:
    """仓库层 int 主键转换：UUID 取 .int，int 原样透传。"""
    return value.int if isinstance(value, uuid.UUID) else int(value)


def _orm_to_domain(row: ChatMessageORM) -> ChatMessage:
    """ORM -> 领域实体（int->UUID 转换）。"""
    assert row.conversation_id is not None  # #744 迁移回填后所有消息均有 conversation_id
    return ChatMessage(
        id=uuid.UUID(int=row.id),
        project_id=uuid.UUID(int=row.project_id),
        conversation_id=uuid.UUID(int=row.conversation_id),
        # role/intent 由 ORM str 列读出，运行时恒为合法枚举值（写入前经 DTO Literal 校验），
        # mypy 需显式收窄为领域 Literal（mypy 无法从 Mapped[str] 推断字面量）
        role=cast(Literal["user", "ai"], row.role),
        content=row.content,
        intent=cast(Literal["content", "conversation"] | None, row.intent),
        created_at=_as_utc(row.created_at),
        is_deleted=row.is_deleted,
    )


def _conv_to_domain(row: ConversationORM) -> Conversation:
    """ConversationORM -> 领域实体（int->UUID 转换 + tz 归一）。"""
    return Conversation(
        id=uuid.UUID(int=row.id),
        project_id=uuid.UUID(int=row.project_id),
        created_at=_as_utc(row.created_at),
        is_deleted=row.is_deleted,
        title=row.title,
    )


class SQLiteChatMessageRepository:
    """chat 消息仓储（鸭子：add / 会话生命周期 / list_conversations）。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, message: ChatMessage) -> ChatMessage:
        """落库消息（绑定 project_id + conversation_id）。

        若 conversation 行缺失（直插场景），先补建会话行，保证会话级归档/
        列表可命中该线程。
        """
        conv_id = message.conversation_id.int
        existing = (
            await self._db.execute(
                select(ConversationORM.id).where(ConversationORM.id == conv_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            self._db.add(ConversationORM(id=conv_id, project_id=message.project_id.int))
        row = ChatMessageORM(
            project_id=message.project_id.int,
            conversation_id=conv_id,
            role=message.role,
            content=message.content,
            intent=message.intent,
            created_at=message.created_at,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return _orm_to_domain(row)

    async def create_conversation(self, project_id: uuid.UUID, title: str = "") -> Conversation:
        """新建线程（落库），返回领域 Conversation（title 默认空，#770）。"""
        row = ConversationORM(project_id=project_id.int, title=title)
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return _conv_to_domain(row)

    async def rename_conversation(self, conversation_id: int | uuid.UUID, title: str) -> bool:
        """会话改名（#770）：更新 title 列；不存在 → False。"""
        cid = _to_int(conversation_id)
        stmt = (
            sa_update(ConversationORM)
            .where(ConversationORM.id == cid)
            .values(title=title)
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 未声明 rowcount（属性在底层 cursor）

    async def get_active_conversation(self, project_id: uuid.UUID) -> Conversation | None:
        """取该项目最近一条未归档线程；无则 None."""
        stmt = (
            select(ConversationORM)
            .where(ConversationORM.project_id == project_id.int, ~ConversationORM.is_deleted)
            .order_by(ConversationORM.id.desc())
            .limit(1)
        )
        row = (await self._db.execute(stmt)).scalar_one_or_none()
        return _conv_to_domain(row) if row else None

    async def list_by_conversation(
        self, conversation_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[ChatMessage], int]:
        """线程消息列表（按时间升序，分页；不含已归档消息）。"""
        cid = conversation_id.int
        stmt = (
            select(ChatMessageORM)
            .where(ChatMessageORM.conversation_id == cid, ~ChatMessageORM.is_deleted)
            .order_by(ChatMessageORM.created_at.asc(), ChatMessageORM.id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        total = (
            await self._db.execute(
                select(func.count()).select_from(ChatMessageORM).where(
                    ChatMessageORM.conversation_id == cid,
                    ~ChatMessageORM.is_deleted,
                )
            )
        ).scalar_one()
        return [_orm_to_domain(r) for r in rows], int(total)

    async def list_by_project(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[ChatMessage], int]:
        """项目级消息列表（#748 agent 聊天历史兼容；跨线程全部非归档消息）。"""
        pid = project_id.int if isinstance(project_id, uuid.UUID) else int(project_id)
        stmt = (
            select(ChatMessageORM)
            .where(ChatMessageORM.project_id == pid, ~ChatMessageORM.is_deleted)
            .order_by(ChatMessageORM.created_at.asc(), ChatMessageORM.id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        total = (
            await self._db.execute(
                select(func.count()).select_from(ChatMessageORM).where(
                    ChatMessageORM.project_id == pid,
                    ~ChatMessageORM.is_deleted,
                )
            )
        ).scalar_one()
        return [_orm_to_domain(r) for r in rows], int(total)

    async def list_conversations(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        """按 conversation 分组（#744 多线程），每线程一张卡。

        每项：conversation_id/project_id/project_name/last_message/message_count/
        is_deleted（由 conversation.is_deleted 决定）/updated_at（最新消息时间，
        无消息则 conversation.created_at），按 updated_at 降序。
        include_deleted=True 时含已归档线程（会话页恢复入口）。
        """
        conv_stmt = select(ConversationORM)
        if not include_deleted:
            conv_stmt = conv_stmt.where(~ConversationORM.is_deleted)
        conv_rows = (await self._db.execute(conv_stmt)).scalars().all()
        if not conv_rows:
            return []

        conv_ids = [c.id for c in conv_rows]
        msg_rows = (
            await self._db.execute(
                select(ChatMessageORM)
                .where(
                    ChatMessageORM.conversation_id.in_(conv_ids),
                    ~ChatMessageORM.is_deleted,
                )
                .order_by(ChatMessageORM.created_at.asc(), ChatMessageORM.id.asc())
            )
        ).scalars().all()
        count_by_conv: dict[int, int] = {c.id: 0 for c in conv_rows}
        last_by_conv: dict[int, ChatMessageORM] = {}
        for r in msg_rows:
            assert r.conversation_id is not None  # #744 迁移回填后消息均有所属线程
            cid = r.conversation_id
            count_by_conv[cid] = count_by_conv.get(cid, 0) + 1
            last_by_conv[cid] = r  # 升序遍历，最后一条即最新

        project_ids = {c.project_id for c in conv_rows}
        names: dict[int, str] = {}
        for pid, name in (
            await self._db.execute(
                select(ProjectORM.id, ProjectORM.name).where(ProjectORM.id.in_(project_ids))
            )
        ).all():
            names[pid] = name

        items: list[dict[str, Any]] = []
        for c in conv_rows:
            last = last_by_conv.get(c.id)
            updated_at = _as_utc(last.created_at if last else c.created_at)
            items.append(
                {
                    "conversation_id": str(uuid.UUID(int=c.id)),
                    "project_id": str(uuid.UUID(int=c.project_id)),
                    "project_name": names.get(c.project_id),
                    "title": c.title,
                    "last_message": last.content if last else "",
                    "message_count": count_by_conv.get(c.id, 0),
                    "is_deleted": c.is_deleted,
                    "updated_at": updated_at.isoformat(),
                }
            )
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    async def archive_message(self, message_id: int) -> bool:
        """归档消息（is_deleted=true）。返回 True 表示成功归档，False 表示未找到/已归档。"""
        stmt = (
            sa_update(ChatMessageORM)
            .where(ChatMessageORM.id == message_id, ~ChatMessageORM.is_deleted)
            .values(is_deleted=True)
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 未声明 rowcount（属性在底层 cursor）

    async def force_delete_message(self, message_id: int) -> bool:
        """物理删除消息。返回 True 表示删除成功，False 表示不存在。"""
        stmt = select(ChatMessageORM).where(ChatMessageORM.id == message_id)
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._db.delete(orm)
        await self._db.commit()
        return True

    async def restore_message(self, message_id: int) -> ChatMessage | None:
        """解除归档（is_deleted=false）。返回解除后的消息；不存在/未归档返回 None。"""
        stmt = (
            sa_update(ChatMessageORM)
            .where(ChatMessageORM.id == message_id, ChatMessageORM.is_deleted)
            .values(is_deleted=False)
        )
        result = await self._db.execute(stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 未声明 rowcount（属性在底层 cursor）
            await self._db.commit()
            return None
        await self._db.commit()
        row = (
            await self._db.execute(
                select(ChatMessageORM).where(ChatMessageORM.id == message_id)
            )
        ).scalar_one_or_none()
        return _orm_to_domain(row) if row else None

    # #744 兼容别名：service 鸭子委托走 archive/force_delete/restore（#566 旧名），
    # repo 语义名 archive_message/force_delete_message/restore_message 保留给测试与直接调用。
    archive = archive_message
    force_delete = force_delete_message
    restore = restore_message

    async def archive_conversation(self, conversation_id: int | uuid.UUID) -> bool:
        """线程级归档：conversation.is_deleted=True + 其消息 is_deleted=True。"""
        cid = _to_int(conversation_id)
        conv_stmt = (
            sa_update(ConversationORM)
            .where(ConversationORM.id == cid, ~ConversationORM.is_deleted)
            .values(is_deleted=True)
        )
        result = await self._db.execute(conv_stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 未声明 rowcount（属性在底层 cursor）
            await self._db.commit()
            return False
        await self._db.execute(
            sa_update(ChatMessageORM)
            .where(ChatMessageORM.conversation_id == cid, ~ChatMessageORM.is_deleted)
            .values(is_deleted=True)
        )
        await self._db.commit()
        return True

    async def force_delete_conversation(self, conversation_id: int | uuid.UUID) -> bool:
        """线程级真删：删除该线程全部消息 + 会话行。返回是否命中。"""
        cid = _to_int(conversation_id)
        exists = (
            await self._db.execute(
                select(ConversationORM.id).where(ConversationORM.id == cid)
            )
        ).scalar_one_or_none()
        if exists is None:
            return False
        await self._db.execute(
            sa_delete(ChatMessageORM).where(ChatMessageORM.conversation_id == cid)
        )
        await self._db.execute(
            sa_delete(ConversationORM).where(ConversationORM.id == cid)
        )
        await self._db.commit()
        return True

    async def restore_conversation(self, conversation_id: int | uuid.UUID) -> bool:
        """线程级恢复：conversation.is_deleted=False + 取消消息归档。"""
        cid = _to_int(conversation_id)
        conv_stmt = (
            sa_update(ConversationORM)
            .where(ConversationORM.id == cid, ConversationORM.is_deleted)
            .values(is_deleted=False)
        )
        result = await self._db.execute(conv_stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 未声明 rowcount（属性在底层 cursor）
            await self._db.commit()
            return False
        await self._db.execute(
            sa_update(ChatMessageORM)
            .where(ChatMessageORM.conversation_id == cid, ChatMessageORM.is_deleted)
            .values(is_deleted=False)
        )
        await self._db.commit()
        return True

    async def update_delete_permission(
        self, *, conversation_id: uuid.UUID, delete_permission: str
    ) -> dict | None:
        """更新线程删除授权（conversations 表）。不存在 → None。"""
        cid = _to_int(conversation_id)
        row = (
            await self._db.execute(
                select(ConversationORM).where(ConversationORM.id == cid)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.delete_permission = delete_permission
        await self._db.commit()
        return {
            "conversation_id": str(uuid.UUID(int=row.id)),
            "delete_permission": row.delete_permission,
        }
