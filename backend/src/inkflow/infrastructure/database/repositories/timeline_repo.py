"""SQLite 时间线事件仓储 — 实现 TimelineRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参照 world_repo.py / outline_repo.py）。

语义（spec §2/§6/§7）:
- 无任何唯一约束（spec §2.4）: title / narrative_position / time_value
  均允许重复——时间线事件是「实例」而非「档案」，无同名冲突检查
- soft_delete = UPDATE is_deleted=1；hard_delete = DELETE
- get/list/list_all 一律排除已软删除事件
- list 默认按 narrative_position ASC 排序（spec §6.3）；
  sort_by=time_value 时未知时间始终排末尾（NULLS LAST，升/降序均适用）
- list_all 按 (narrative_position ASC, created_at ASC) 稳定排序（叙事顺序），
  供双线视图/一致性检查消费
- next_position = 项目内活动事件 max(narrative_position)+1（空项目 = 1）
- FK 级联: 项目物理删除 → 事件级联物理删除（DB FK CASCADE）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/timeline_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.timeline import TimelineEvent
from inkflow.infrastructure.database.models.timeline import TimelineEventORM


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _int_to_uuid(value: int | uuid.UUID | None) -> uuid.UUID | None:
    """DB int → 领域 UUID（F1 映射: uuid.UUID(int=...)）."""
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(int=value)


def _uuid_to_int(value: uuid.UUID | int) -> int:
    """领域 UUID → DB int（F1 映射: uuid.int）."""
    return value.int if isinstance(value, uuid.UUID) else int(value)


def _orm_to_domain(orm: TimelineEventORM) -> TimelineEvent:
    """时间线事件 ORM 行 → 领域实体（int PK → UUID）."""
    return TimelineEvent(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        title=orm.title,
        description=orm.description,
        time_value=orm.time_value,
        time_unit=orm.time_unit,
        time_display=orm.time_display,
        narrative_position=orm.narrative_position,
        timeline_flag=orm.timeline_flag,
        extra=orm.extra or {},
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: TimelineEvent) -> TimelineEventORM:
    """时间线事件领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return TimelineEventORM(
        project_id=_uuid_to_int(domain.project_id),
        title=domain.title,
        description=domain.description,
        time_value=domain.time_value,
        time_unit=domain.time_unit,
        time_display=domain.time_display,
        narrative_position=domain.narrative_position,
        timeline_flag=domain.timeline_flag,
        extra=domain.extra,
        is_deleted=domain.is_deleted,
    )


class SQLiteTimelineRepository:
    """SQLite 时间线事件仓储 — 实现 TimelineRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── TimelineEvent ──

    async def add(self, event: TimelineEvent) -> TimelineEvent:
        """插入新事件（id 由 DB 自增分配，读回时映射为 UUID）."""
        orm = _domain_to_orm(event)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, event_id: int) -> TimelineEvent | None:
        """按主键查询事件（不含已软删除）."""
        stmt = select(TimelineEventORM).where(
            TimelineEventORM.id == event_id,
            ~TimelineEventORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        sort_by: str = "narrative_position",
        sort_desc: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[TimelineEvent], int]:
        """分页查询项目内活动事件列表，支持标题模糊搜索与排序（不含已软删除）.

        Args:
            project_id: 项目主键（int）.
            search: 事件标题模糊搜索（icontains，可选）.
            sort_by: 排序字段（narrative_position / time_value / title /
                updated_at / created_at；默认 narrative_position）.
            sort_desc: 是否倒序（默认升序）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (当前页事件列表, 符合条件的总记录数).
        """
        base = select(TimelineEventORM).where(
            TimelineEventORM.project_id == project_id,
            ~TimelineEventORM.is_deleted,
        )

        # 搜索: title icontains
        if search:
            base = base.where(TimelineEventORM.title.icontains(search))

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页
        sort_col = getattr(TimelineEventORM, sort_by, TimelineEventORM.narrative_position)
        if sort_by == "time_value":
            # 未知时间（NULL）始终排末尾（升/降序均 NULLS LAST）
            order = sort_col.desc().nulls_last() if sort_desc else sort_col.asc().nulls_last()
        elif sort_by == "narrative_position":
            # 稳定排序: 同位置按 created_at ASC（spec §2.1）
            order = (
                (sort_col.desc(), TimelineEventORM.created_at.asc())
                if sort_desc
                else (sort_col.asc(), TimelineEventORM.created_at.asc())
            )
        else:
            order = sort_col.desc() if sort_desc else sort_col.asc()
        base = base.order_by(*order) if isinstance(order, tuple) else base.order_by(order)
        base = base.offset(offset).limit(limit)

        result = await self._session.execute(base)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total

    async def list_all(self, project_id: int) -> builtins.list[TimelineEvent]:
        """列出项目内全部活动事件，按 (narrative_position ASC, created_at ASC) 稳定排序.

        双线视图/一致性检查直接消费此全量结果（软删除事件不进入）。
        """
        stmt = (
            select(TimelineEventORM)
            .where(
                TimelineEventORM.project_id == project_id,
                ~TimelineEventORM.is_deleted,
            )
            .order_by(
                TimelineEventORM.narrative_position.asc(),
                TimelineEventORM.created_at.asc(),
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms]

    async def next_position(self, project_id: int) -> int:
        """计算项目内下一个叙事位置: max(narrative_position)+1（无事件时 = 1）.

        只统计活动事件（软删不计入 max）。
        """
        stmt = select(func.coalesce(func.max(TimelineEventORM.narrative_position), 0) + 1).where(
            TimelineEventORM.project_id == project_id,
            ~TimelineEventORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def update(self, event: TimelineEvent) -> TimelineEvent:
        """更新事件（按 id 定位，updated_at 自动刷新）.

        Raises:
            ValueError: 事件不存在.
        """
        event_id = _uuid_to_int(event.id)
        stmt = (
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == event_id)
            .values(
                title=event.title,
                description=event.description,
                time_value=event.time_value,
                time_unit=event.time_unit,
                time_display=event.time_display,
                narrative_position=event.narrative_position,
                timeline_flag=event.timeline_flag,
                extra=event.extra,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"TimelineEvent {event_id} not found")

        stmt2 = select(TimelineEventORM).where(TimelineEventORM.id == event_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"TimelineEvent {event_id} not found after update")
        return _orm_to_domain(orm)

    async def soft_delete(self, event_id: int) -> bool:
        """软删除事件（is_deleted=True）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到/已删除.
        """
        stmt = (
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == event_id, ~TimelineEventORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def restore(self, event_id: int) -> TimelineEvent | None:
        """恢复已软删除事件.

        Returns:
            恢复后的 TimelineEvent；记录不存在或未删除时返回 None（重复操作无毒）.
        """
        stmt = (
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == event_id, TimelineEventORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            await self._session.commit()
            return None
        await self._session.commit()
        return await self.get(event_id)

    async def hard_delete(self, event_id: int) -> bool:
        """物理删除事件（仅用于 force 场景）.

        Returns:
            True 表示删除成功，False 表示不存在.
        """
        stmt = select(TimelineEventORM).where(TimelineEventORM.id == event_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True
