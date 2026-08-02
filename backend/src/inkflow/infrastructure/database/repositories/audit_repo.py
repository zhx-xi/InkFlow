"""SQLite 审计软删集合补充查询仓储 — 实现 AuditRepositoryProtocol.

F15 审计服务需要各模块既有查询默认不可见的软删集合（is_deleted=1），
本仓储直接对 characters / character_groups / timeline_events 三张既有表
做只读查询（按 project_id 过滤），返回 (软删角色 ids, 软删分组 ids,
软删事件 ids) 三元组。

只读语义:
- 仅执行 SELECT，不建表、不落库、不修改任何既有表/仓储（零跨模块 MODIFY）
- 查询结果按 id 升序，保证确定性

依据: specs/f15-audit-service/spec.md §8.2/§12（软删集合查询设计）。
"""

from __future__ import annotations

import builtins

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.infrastructure.database.models.character import (
    CharacterGroupORM,
    CharacterORM,
)
from inkflow.infrastructure.database.models.timeline import TimelineEventORM


class SQLiteAuditRepository:
    """SQLite 审计软删集合补充查询仓储（AuditRepositoryProtocol 结构化子类型）.

    不显式继承 Protocol（结构化子类型），由 F15 服务层按
    AuditRepositoryProtocol 注入使用。
    """

    def __init__(self, session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = session

    async def list_deleted(
        self, project_id: int
    ) -> tuple[builtins.list[int], builtins.list[int], builtins.list[int]]:
        """列出项目内三类软删实体 id（角色 / 分组 / 事件）.

        Args:
            project_id: 项目主键（int，与 ORM 层一致）.

        Returns:
            (软删角色 ids, 软删分组 ids, 软删事件 ids) 三元组——
            分别来自 characters / character_groups / timeline_events 表的
            is_deleted=1 行（按 project_id 过滤，id 升序）。
        """
        char_stmt = (
            select(CharacterORM.id)
            .where(
                CharacterORM.project_id == project_id,
                CharacterORM.is_deleted.is_(True),
            )
            .order_by(CharacterORM.id.asc())
        )
        group_stmt = (
            select(CharacterGroupORM.id)
            .where(
                CharacterGroupORM.project_id == project_id,
                CharacterGroupORM.is_deleted.is_(True),
            )
            .order_by(CharacterGroupORM.id.asc())
        )
        event_stmt = (
            select(TimelineEventORM.id)
            .where(
                TimelineEventORM.project_id == project_id,
                TimelineEventORM.is_deleted.is_(True),
            )
            .order_by(TimelineEventORM.id.asc())
        )

        char_result = await self._session.execute(char_stmt)
        group_result = await self._session.execute(group_stmt)
        event_result = await self._session.execute(event_stmt)

        return (
            list(char_result.scalars().all()),
            list(group_result.scalars().all()),
            list(event_result.scalars().all()),
        )
