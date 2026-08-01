"""SQLite 大纲/情节点/弧线仓储 — 实现 OutlineRepositoryProtocol 全部 28 个方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参照 project_repo.py / chapter_repo.py / character_repo.py）。

级联语义（spec §2.3/§6/§7）:
- 大纲软删除 → 其全部情节点级联软删（soft_delete_points_of）；大纲恢复 → 级联恢复
- 弧线软删除/硬删除 → 成员情节点 arc_id 置 NULL（情节点本身保留）
- 大纲硬删除 → 情节点物理删除（DB FK CASCADE）；项目删除 → 三实体物理级联
- 活动记录 partial unique：项目内活动大纲/弧线同名唯一，软删后可重建（spec §2.4）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/outline_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.outline import Outline, PlotPoint, StoryArc
from inkflow.infrastructure.database.models.outline import (
    OutlineORM,
    PlotPointORM,
    StoryArcORM,
)


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


def _outline_orm_to_domain(orm: OutlineORM) -> Outline:
    """大纲 ORM 行 → 领域实体（int PK → UUID）."""
    return Outline(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        description=orm.description,
        sort_order=orm.sort_order,
        extra=orm.extra or {},
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _outline_domain_to_orm(domain: Outline) -> OutlineORM:
    """大纲领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return OutlineORM(
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        description=domain.description,
        sort_order=domain.sort_order,
        extra=domain.extra,
        is_deleted=domain.is_deleted,
    )


def _point_orm_to_domain(orm: PlotPointORM) -> PlotPoint:
    """情节点 ORM 行 → 领域实体（int PK → UUID）."""
    return PlotPoint(
        id=uuid.UUID(int=orm.id),
        outline_id=uuid.UUID(int=orm.outline_id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        type=orm.type,
        description=orm.description,
        position=orm.position,
        arc_id=_int_to_uuid(orm.arc_id),
        extra=orm.extra or {},
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _point_domain_to_orm(domain: PlotPoint) -> PlotPointORM:
    """情节点领域实体 → ORM 行（UUID → int；id 由 DB 自增分配）."""
    return PlotPointORM(
        outline_id=_uuid_to_int(domain.outline_id),
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        type=domain.type,
        description=domain.description,
        position=domain.position,
        arc_id=_uuid_to_int(domain.arc_id) if domain.arc_id is not None else None,
        extra=domain.extra,
        is_deleted=domain.is_deleted,
    )


def _arc_orm_to_domain(orm: StoryArcORM) -> StoryArc:
    """弧线 ORM 行 → 领域实体（int PK → UUID）."""
    return StoryArc(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        description=orm.description,
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _arc_domain_to_orm(domain: StoryArc) -> StoryArcORM:
    """弧线领域实体 → ORM 行（UUID → int；id 由 DB 自增分配）."""
    return StoryArcORM(
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        description=domain.description,
        is_deleted=domain.is_deleted,
    )


class SQLiteOutlineRepository:
    """SQLite 大纲/情节点/弧线仓储 — 实现 OutlineRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Outline ──

    async def add(self, outline: Outline) -> Outline:
        """插入新大纲（id 由 DB 自增分配，读回时映射为 UUID）."""
        orm = _outline_domain_to_orm(outline)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _outline_orm_to_domain(orm)

    async def get(self, outline_id: int) -> Outline | None:
        """按主键查询大纲（不含已软删除）."""
        stmt = select(OutlineORM).where(
            OutlineORM.id == outline_id,
            ~OutlineORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _outline_orm_to_domain(orm) if orm else None

    async def get_by_name(self, project_id: int, name: str) -> Outline | None:
        """按项目内大纲名查询活动大纲（不含已软删除）."""
        stmt = select(OutlineORM).where(
            OutlineORM.project_id == project_id,
            OutlineORM.name == name,
            ~OutlineORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _outline_orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[Outline], int]:
        """分页查询项目内大纲列表，支持名称模糊搜索（不含已软删除）.

        Returns:
            (当前页大纲列表, 符合条件的总记录数).
        """
        base = select(OutlineORM).where(
            OutlineORM.project_id == project_id,
            ~OutlineORM.is_deleted,
        )

        # 搜索: name icontains
        if search:
            base = base.where(OutlineORM.name.icontains(search))

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页
        sort_col = getattr(OutlineORM, sort_by, OutlineORM.updated_at)
        base = base.order_by(sort_col.desc() if sort_desc else sort_col.asc())
        base = base.offset(offset).limit(limit)

        result = await self._session.execute(base)
        orms = result.scalars().all()
        return [_outline_orm_to_domain(o) for o in orms], total

    async def update(self, outline: Outline) -> Outline:
        """更新大纲（按 id 定位，updated_at 自动刷新）."""
        outline_id = _uuid_to_int(outline.id)
        stmt = (
            sa_update(OutlineORM)
            .where(OutlineORM.id == outline_id)
            .values(
                name=outline.name,
                description=outline.description,
                sort_order=outline.sort_order,
                extra=outline.extra,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"Outline {outline_id} not found")

        stmt2 = select(OutlineORM).where(OutlineORM.id == outline_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"Outline {outline_id} not found after update")
        return _outline_orm_to_domain(orm)

    async def soft_delete(self, outline_id: int) -> bool:
        """软删除大纲（is_deleted=True，级联软删其全部情节点）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到/已删除.
        """
        stmt = (
            sa_update(OutlineORM)
            .where(OutlineORM.id == outline_id, ~OutlineORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount > 0:  # type: ignore[attr-defined]
            # 级联软删情节点；该方法内部 commit，大纲 UPDATE 一并提交（单事务）
            await self.soft_delete_points_of(outline_id)
        else:
            await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def restore(self, outline_id: int) -> Outline | None:
        """恢复已软删除大纲（含级联恢复其全部情节点）.

        Returns:
            恢复后的 Outline；记录不存在或未删除时返回 None（重复操作无毒）.
        """
        stmt = (
            sa_update(OutlineORM)
            .where(OutlineORM.id == outline_id, OutlineORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount > 0:  # type: ignore[attr-defined]
            # 级联恢复情节点；该方法内部 commit，大纲 UPDATE 一并提交（单事务）
            await self.restore_points_of(outline_id)
        else:
            await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        return await self.get(outline_id)

    async def hard_delete(self, outline_id: int) -> bool:
        """物理删除大纲（其情节点由 DB FK CASCADE 物理删除）."""
        stmt = select(OutlineORM).where(OutlineORM.id == outline_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def soft_delete_points_of(self, outline_id: int) -> None:
        """级联软删某大纲的全部活动情节点（大纲软删除时调用）.

        内部执行 UPDATE 并 commit（与调用方 pending 变更同一事务）。
        """
        await self._session.execute(
            sa_update(PlotPointORM)
            .where(
                PlotPointORM.outline_id == outline_id,
                ~PlotPointORM.is_deleted,
            )
            .values(is_deleted=True, updated_at=_utcnow())
        )
        await self._session.commit()

    async def restore_points_of(self, outline_id: int) -> None:
        """级联恢复某大纲的全部已软删情节点（大纲恢复时调用）.

        内部执行 UPDATE 并 commit（与调用方 pending 变更同一事务）。
        """
        await self._session.execute(
            sa_update(PlotPointORM)
            .where(
                PlotPointORM.outline_id == outline_id,
                PlotPointORM.is_deleted,
            )
            .values(is_deleted=False, updated_at=_utcnow())
        )
        await self._session.commit()

    # ── PlotPoint ──

    async def add_point(self, point: PlotPoint) -> PlotPoint:
        """插入新情节点（id 由 DB 自增分配）."""
        orm = _point_domain_to_orm(point)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _point_orm_to_domain(orm)

    async def get_point(self, point_id: int) -> PlotPoint | None:
        """按主键查询情节点（不含已软删除）."""
        stmt = select(PlotPointORM).where(
            PlotPointORM.id == point_id,
            ~PlotPointORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _point_orm_to_domain(orm) if orm else None

    async def list_points(self, outline_id: int) -> builtins.list[PlotPoint]:
        """列出大纲内全部活动情节点，按 (position ASC, created_at ASC) 稳定排序."""
        stmt = (
            select(PlotPointORM)
            .where(
                PlotPointORM.outline_id == outline_id,
                ~PlotPointORM.is_deleted,
            )
            .order_by(
                PlotPointORM.position.asc(),
                PlotPointORM.created_at.asc(),
                PlotPointORM.id.asc(),
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_point_orm_to_domain(o) for o in orms]

    async def list_points_by_arc(self, arc_id: int) -> builtins.list[PlotPoint]:
        """列出挂载到指定弧线的全部活动情节点，按 position ASC 排序."""
        stmt = (
            select(PlotPointORM)
            .where(
                PlotPointORM.arc_id == arc_id,
                ~PlotPointORM.is_deleted,
            )
            .order_by(
                PlotPointORM.position.asc(),
                PlotPointORM.created_at.asc(),
                PlotPointORM.id.asc(),
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_point_orm_to_domain(o) for o in orms]

    async def next_position(self, outline_id: int) -> int:
        """计算大纲内下一个排序位置：max(position)+1（无情节点时 = 1）.

        只统计活动情节点（软删不计入）。
        """
        stmt = select(func.coalesce(func.max(PlotPointORM.position), 0) + 1).where(
            PlotPointORM.outline_id == outline_id,
            ~PlotPointORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def update_point(self, point: PlotPoint) -> PlotPoint:
        """更新情节点（按 id 定位，updated_at 自动刷新）."""
        point_id = _uuid_to_int(point.id)
        stmt = (
            sa_update(PlotPointORM)
            .where(PlotPointORM.id == point_id)
            .values(
                name=point.name,
                type=point.type,
                description=point.description,
                position=point.position,
                arc_id=_uuid_to_int(point.arc_id) if point.arc_id is not None else None,
                extra=point.extra,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"PlotPoint {point_id} not found")

        stmt2 = select(PlotPointORM).where(PlotPointORM.id == point_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"PlotPoint {point_id} not found after update")
        return _point_orm_to_domain(orm)

    async def soft_delete_point(self, point_id: int) -> bool:
        """软删除情节点（is_deleted=True）."""
        stmt = (
            sa_update(PlotPointORM)
            .where(PlotPointORM.id == point_id, ~PlotPointORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def restore_point(self, point_id: int) -> PlotPoint | None:
        """恢复已软删除情节点.

        Returns:
            恢复后的 PlotPoint；记录不存在或未删除时返回 None（重复操作无毒）.
        """
        stmt = (
            sa_update(PlotPointORM)
            .where(PlotPointORM.id == point_id, PlotPointORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        return await self.get_point(point_id)

    async def hard_delete_point(self, point_id: int) -> bool:
        """物理删除情节点."""
        stmt = select(PlotPointORM).where(PlotPointORM.id == point_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def clear_arc_of_points(self, arc_id: int) -> None:
        """弧线删除时把成员情节点的 arc_id 置 NULL（不级联删情节点）.

        内部执行 UPDATE 并 commit（与调用方 pending 变更同一事务）。
        """
        await self._session.execute(
            sa_update(PlotPointORM)
            .where(PlotPointORM.arc_id == arc_id)
            .values(arc_id=None, updated_at=_utcnow())
        )
        await self._session.commit()

    # ── StoryArc ──

    async def add_arc(self, arc: StoryArc) -> StoryArc:
        """插入新故事弧线（id 由 DB 自增分配）."""
        orm = _arc_domain_to_orm(arc)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _arc_orm_to_domain(orm)

    async def get_arc(self, arc_id: int) -> StoryArc | None:
        """按主键查询故事弧线（不含已软删除）."""
        stmt = select(StoryArcORM).where(
            StoryArcORM.id == arc_id,
            ~StoryArcORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _arc_orm_to_domain(orm) if orm else None

    async def get_arc_by_name(self, project_id: int, name: str) -> StoryArc | None:
        """按项目内弧线名查询活动故事弧线（不含已软删除）."""
        stmt = select(StoryArcORM).where(
            StoryArcORM.project_id == project_id,
            StoryArcORM.name == name,
            ~StoryArcORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _arc_orm_to_domain(orm) if orm else None

    async def list_arcs(self, project_id: int) -> builtins.list[StoryArc]:
        """查询项目内全部活动故事弧线，按 name 升序."""
        stmt = (
            select(StoryArcORM)
            .where(
                StoryArcORM.project_id == project_id,
                ~StoryArcORM.is_deleted,
            )
            .order_by(StoryArcORM.name.asc(), StoryArcORM.id.asc())
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_arc_orm_to_domain(o) for o in orms]

    async def update_arc(self, arc: StoryArc) -> StoryArc:
        """更新故事弧线（按 id 定位，updated_at 自动刷新）."""
        arc_id = _uuid_to_int(arc.id)
        stmt = (
            sa_update(StoryArcORM)
            .where(StoryArcORM.id == arc_id)
            .values(
                name=arc.name,
                description=arc.description,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"StoryArc {arc_id} not found")

        stmt2 = select(StoryArcORM).where(StoryArcORM.id == arc_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"StoryArc {arc_id} not found after update")
        return _arc_orm_to_domain(orm)

    async def soft_delete_arc(self, arc_id: int) -> bool:
        """软删除故事弧线（is_deleted=True，成员情节点 arc_id 置 NULL）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到/已删除.
        """
        stmt = (
            sa_update(StoryArcORM)
            .where(StoryArcORM.id == arc_id, ~StoryArcORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount > 0:  # type: ignore[attr-defined]
            # 成员情节点 arc_id 置 NULL；该方法内部 commit，弧线 UPDATE 一并提交（单事务）
            await self.clear_arc_of_points(arc_id)
        else:
            await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def restore_arc(self, arc_id: int) -> StoryArc | None:
        """恢复已软删除故事弧线（仅恢复弧线本身，成员 arc_id 保持 NULL）.

        Returns:
            恢复后的 StoryArc；记录不存在或未删除时返回 None（重复操作无毒）.
        """
        stmt = (
            sa_update(StoryArcORM)
            .where(StoryArcORM.id == arc_id, StoryArcORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        return await self.get_arc(arc_id)

    async def hard_delete_arc(self, arc_id: int) -> bool:
        """物理删除故事弧线（成员情节点 arc_id 由 DB FK SET NULL 置空）."""
        stmt = select(StoryArcORM).where(StoryArcORM.id == arc_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True
