"""SQLite 记忆事件仓储 — F28 偏好学习闭环的事件源（Q2 独立 memory_events 表）.

转换函数（_orm_to_domain）按项目惯例放在本仓储层（参照 draft_repo.py）.

语义（spec §5.1，父侧契约 test_memory_event_repo.py docstring）：
- create: 落库事件（字段展开形态；diff_chars 由本方法内部计算 =
  len(after_content or "") - len(before_content or "")），单次 commit + refresh
- list_by_project: project_id + event_type（可空）过滤，created_at desc，
  offset/limit 分页，返回 (列表, 该项目事件总数)
- list_edited_by_project: 只 DRAFT_EDITED，created_at asc（提取顺序稳定）
- count_by_project: 项目事件总数
- delete_by_project: 删除该项目全部事件，返回删除行数
- 领域 UUID → uuid4 字符串转换在仓储层（project_id/chapter_id 列存 str(uuid)，
  与 F27 先例一致；draft_id/agent_run_id 本就为字符串 id）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与既有仓储惯例一致）。
"""

from __future__ import annotations

import builtins
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.memory_event import MemoryEvent, MemoryEventType
from inkflow.infrastructure.database.models.preference import MemoryEventORM


def _orm_to_domain(orm: MemoryEventORM) -> MemoryEvent:
    """MemoryEvent ORM 行 → 领域实体（uuid 字符串 → UUID，类型字符串 → 枚举）."""
    return MemoryEvent(
        id=orm.id,
        project_id=uuid.UUID(orm.project_id),
        draft_id=orm.draft_id,
        chapter_id=uuid.UUID(orm.chapter_id) if orm.chapter_id is not None else None,
        agent_run_id=orm.agent_run_id,
        event_type=MemoryEventType(orm.event_type),
        before_content=orm.before_content,
        after_content=orm.after_content,
        diff_chars=orm.diff_chars,
        created_at=orm.created_at,
    )


class SQLiteMemoryEventRepository:
    """SQLite 记忆事件仓储（session 注入，镜像 F27 draft_repo 模式）."""

    def __init__(self, db_session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = db_session

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        draft_id: str | None = None,
        chapter_id: uuid.UUID | None = None,
        agent_run_id: str | None = None,
        event_type: MemoryEventType,
        before_content: str | None = None,
        after_content: str | None = None,
    ) -> MemoryEvent:
        """创建事件（diff_chars 由本方法计算），单次 commit + refresh.

        Args:
            project_id: 所属项目 UUID.
            draft_id: 关联草稿 id（可空）.
            chapter_id: 目标章节 UUID（可空）.
            agent_run_id: 来源 agent run id（可空）.
            event_type: 事件类型.
            before_content: 修改前内容（可空）.
            after_content: 修改后内容（可空）.

        Returns:
            已落库的 MemoryEvent（diff_chars = len(after_content or "") -
            len(before_content or "")，created_at 由 ORM default 生成 UTC 时间）.
        """
        orm = MemoryEventORM(
            project_id=str(project_id),
            draft_id=draft_id,
            chapter_id=str(chapter_id) if chapter_id is not None else None,
            agent_run_id=agent_run_id,
            event_type=event_type.value,
            before_content=before_content,
            after_content=after_content,
            diff_chars=len(after_content or "") - len(before_content or ""),
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        event_type: MemoryEventType | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[MemoryEvent], int]:
        """按项目 + 事件类型过滤分页查询事件，created_at desc（最新在前）.

        Args:
            project_id: 所属项目 UUID.
            event_type: 事件类型精确过滤（不传 = 全部）.
            offset: 分页偏移（默认 0）.
            limit: 每页条数（默认 50）.

        Returns:
            (页内 MemoryEvent 列表, 该项目事件总数).
        """
        stmt = select(MemoryEventORM).where(MemoryEventORM.project_id == str(project_id))
        if event_type is not None:
            stmt = stmt.where(MemoryEventORM.event_type == event_type.value)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(MemoryEventORM.created_at.desc())
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()], total

    async def list_edited_by_project(self, project_id: uuid.UUID) -> builtins.list[MemoryEvent]:
        """返回项目全部 DRAFT_EDITED 事件，created_at asc（提取顺序稳定）.

        Args:
            project_id: 所属项目 UUID.

        Returns:
            DRAFT_EDITED 事件列表（按时间正序，供 difflib 规则化提取）.
        """
        stmt = (
            select(MemoryEventORM)
            .where(
                MemoryEventORM.project_id == str(project_id),
                MemoryEventORM.event_type == MemoryEventType.DRAFT_EDITED.value,
            )
            .order_by(MemoryEventORM.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """返回项目事件总数（不含分页）."""
        stmt = (
            select(func.count())
            .select_from(MemoryEventORM)
            .where(MemoryEventORM.project_id == str(project_id))
        )
        # int() 收敛 Any（CI 全量 mypy no-any-return 防御）
        return int((await self._session.execute(stmt)).scalar_one())

    async def delete_by_project(self, project_id: uuid.UUID) -> int:
        """删除该项目全部事件，返回删除行数（服务层级联用）.

        Args:
            project_id: 所属项目 UUID.

        Returns:
            删除的事件行数（0 = 项目原本无事件）.
        """
        result = await self._session.execute(
            delete(MemoryEventORM).where(MemoryEventORM.project_id == str(project_id))
        )
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
