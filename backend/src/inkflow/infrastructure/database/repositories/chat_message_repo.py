"""#547 chat 消息仓储 — SQLite 实现（int↔UUID 转换在 repo 层）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.chat_message import ChatMessage
from inkflow.infrastructure.database.models.chat_message import ChatMessageORM
from inkflow.infrastructure.database.models.project import ProjectORM


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _orm_to_domain(row: ChatMessageORM) -> ChatMessage:
    """ORM → 领域实体（int→UUID 转换）。"""
    return ChatMessage(
        id=uuid.UUID(int=row.id),
        project_id=uuid.UUID(int=row.project_id),
        # role/intent 由 ORM str 列读出，运行时恒为合法枚举值（写入前经 DTO Literal 校验），
        # mypy 需显式收窄为领域 Literal（mypy 无法从 Mapped[str] 推断字面量）
        role=cast(Literal["user", "ai"], row.role),
        content=row.content,
        intent=cast(Literal["content", "conversation"] | None, row.intent),
        created_at=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC),
    )


class SQLiteChatMessageRepository:
    """chat 消息仓储（鸭子：add / list_by_project / list_conversations）。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, message: ChatMessage) -> ChatMessage:
        row = ChatMessageORM(
            project_id=message.project_id.int,
            role=message.role,
            content=message.content,
            intent=message.intent,
            created_at=message.created_at,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return _orm_to_domain(row)

    async def list_by_project(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[ChatMessage], int]:
        stmt = (
            select(ChatMessageORM)
            .where(ChatMessageORM.project_id == project_id.int)
            .order_by(ChatMessageORM.created_at.asc(), ChatMessageORM.id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        total = (
            await self._db.execute(
                select(func.count()).select_from(ChatMessageORM).where(
                    ChatMessageORM.project_id == project_id.int
                )
            )
        ).scalar_one()
        return [_orm_to_domain(r) for r in rows], int(total)

    async def list_conversations(self) -> list[dict[str, Any]]:
        """按项目聚合（最新消息/条数/更新时间降序；project_name 可空 join）。"""
        stmt = (
            select(ChatMessageORM)
            .order_by(ChatMessageORM.created_at.desc(), ChatMessageORM.id.desc())
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        aggregated: dict[int, dict[str, Any]] = {}
        for r in rows:
            agg = aggregated.setdefault(
                r.project_id,
                {"project_id": r.project_id, "project_name": None,
                 "last_message": r.content, "message_count": 0,
                 "updated_at": r.created_at},
            )
            agg["message_count"] += 1
        # project_name join（项目不存在/失败 → None 可空）
        if aggregated:
            ids = list(aggregated.keys())
            name_stmt = select(ProjectORM.id, ProjectORM.name).where(
                ProjectORM.id.in_(ids)
            )
            for pid, name in (await self._db.execute(name_stmt)).all():
                aggregated[pid]["project_name"] = name
        items = [
            {
                "project_id": str(uuid.UUID(int=k)),
                "project_name": v["project_name"],
                "last_message": v["last_message"],
                "message_count": v["message_count"],
                "updated_at": (
                    v["updated_at"].isoformat()
                    if hasattr(v["updated_at"], "isoformat")
                    else v["updated_at"]
                ),
            }
            for k, v in aggregated.items()
        ]
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items
