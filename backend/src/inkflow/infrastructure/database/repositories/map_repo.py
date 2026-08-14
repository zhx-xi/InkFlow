"""SQLite 地图仓储 — 实现 MapRepositoryProtocol 全部 19 个方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参考 world_repo.py）。

语义（spec §2.4 + 父侧定稿契约）:
- maps/map_pins 均【无 is_deleted 列】（真删语义）——repo 方法无任何软删过滤
- delete/delete_many/delete_by_project 单事务显式级联：先删 pins 再删 maps 行
  （D10=b，不依赖 DB FK 动作；生产连接 FK OFF）
- children 单 SQL JOIN 关联地点（v1.1 真删语义无 is_deleted 过滤）+ DISTINCT
- list 过滤三态: root_location_id=None + top_level_only=False = 全量;
  top_level_only=True = 全局图（root_location_id IS NULL）;
  root_location_id 非 None = 精确过滤
- 排序: maps 列表 created_at DESC、pins/children/list_by_root_locations
  created_at ASC

注: 方法名 ``list`` 会遮蔽作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/map_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.map import MapPin, WorldMap
from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
from inkflow.infrastructure.database.models.world import WorldSettingORM


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


def _orm_to_domain(orm: MapORM) -> WorldMap:
    """地图 ORM 行 → 领域实体（int PK → UUID）."""
    return WorldMap(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        image_path=orm.image_path,
        description=orm.description,
        root_location_id=_int_to_uuid(orm.root_location_id),
        parent_map_id=_int_to_uuid(orm.parent_map_id),  # #368 v1.3
        bg_source=orm.bg_source,
        extra=orm.extra or {},
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: WorldMap) -> MapORM:
    """地图领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）.

    created_at/updated_at 不传——由 ORM 默认 _utcnow 生成（契约 8，F35 同款）。
    """
    return MapORM(
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        image_path=domain.image_path,
        description=domain.description,
        root_location_id=_uuid_to_int(domain.root_location_id)
        if domain.root_location_id is not None
        else None,
        parent_map_id=_uuid_to_int(domain.parent_map_id)
        if domain.parent_map_id is not None
        else None,  # #368 v1.3
        bg_source=domain.bg_source,
        extra=domain.extra,
    )


def _pin_orm_to_domain(orm: MapPinORM) -> MapPin:
    """pin ORM 行 → 领域实体（int PK → UUID）."""
    return MapPin(
        id=uuid.UUID(int=orm.id),
        map_id=uuid.UUID(int=orm.map_id),
        location_id=_int_to_uuid(orm.location_id),
        type=orm.type,
        ref_id=_int_to_uuid(orm.ref_id),
        x=orm.x,
        y=orm.y,
        label=orm.label,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _pin_domain_to_orm(domain: MapPin) -> MapPinORM:
    """pin 领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return MapPinORM(
        map_id=_uuid_to_int(domain.map_id),
        location_id=_uuid_to_int(domain.location_id) if domain.location_id is not None else None,
        type=domain.type,
        ref_id=_uuid_to_int(domain.ref_id) if domain.ref_id is not None else None,
        x=domain.x,
        y=domain.y,
        label=domain.label,
    )


class SQLiteMapRepository:
    """SQLite 地图仓储 — 实现 MapRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── maps CRUD ──

    async def add(self, map: WorldMap) -> WorldMap:
        """插入新地图（id 由 DB 自增分配，读回时映射为 UUID）."""
        orm = _domain_to_orm(map)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, map_id: int) -> WorldMap | None:
        """按主键查询地图（无软删过滤——真删语义）."""
        stmt = select(MapORM).where(MapORM.id == map_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_name(self, project_id: int, name: str) -> WorldMap | None:
        """按项目内地图名查询（name 项目内唯一，无软删过滤）."""
        stmt = select(MapORM).where(MapORM.project_id == project_id, MapORM.name == name).limit(1)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: int,
        root_location_id: int | None = None,
        top_level_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[WorldMap], int]:
        """分页查询项目内地图列表，过滤三态 + created_at DESC.

        过滤组合（spec §3.1 Q3=A + 父侧定稿）:
        - root_location_id=None + top_level_only=False = 不过滤（全量）
        - top_level_only=True = 仅全局图（root_location_id IS NULL）
        - root_location_id 非 None = 精确过滤（忽略 top_level_only）
        """
        base = select(MapORM).where(MapORM.project_id == project_id)
        if top_level_only:
            base = base.where(MapORM.root_location_id.is_(None))
        elif root_location_id is not None:
            base = base.where(MapORM.root_location_id == root_location_id)

        # 总数（分页前，同条件）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页
        base = base.order_by(MapORM.created_at.desc())
        base = base.offset(offset).limit(limit)
        result = await self._session.execute(base)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total

    async def update(self, map: WorldMap) -> WorldMap | None:
        """更新地图（按 id 定位全字段覆盖；不存在 → None）."""
        map_id = _uuid_to_int(map.id)
        stmt = select(MapORM).where(MapORM.id == map_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        orm.name = map.name
        orm.image_path = map.image_path
        orm.description = map.description
        orm.bg_source = map.bg_source
        orm.extra = map.extra
        orm.root_location_id = (
            _uuid_to_int(map.root_location_id) if map.root_location_id is not None else None
        )
        orm.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def delete(self, map_id: int) -> bool:
        """真删地图（单事务显式级联删其 pins，D10=b）.

        单事务: DELETE map_pins WHERE map_id=? + DELETE maps WHERE id=?
        （显式级联，不依赖 DB FK 动作）。
        """
        await self._session.execute(sa_delete(MapPinORM).where(MapPinORM.map_id == map_id))
        result = await self._session.execute(sa_delete(MapORM).where(MapORM.id == map_id))
        await self._session.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def delete_many(self, map_ids: builtins.list[int]) -> int:
        """单事务按 id 集合真删多张地图（先删 pins 再删 maps 行）.

        Returns:
            删除的 maps 行数（列表含不存在 id 不影响计数；空列表 = 0）。
        """
        if not map_ids:
            return 0
        await self._session.execute(sa_delete(MapPinORM).where(MapPinORM.map_id.in_(map_ids)))
        result = await self._session.execute(sa_delete(MapORM).where(MapORM.id.in_(map_ids)))
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    # ── pins CRUD ──

    async def list_pins(self, map_id: int) -> builtins.list[MapPin]:
        """列出地图全部 pin（created_at ASC）."""
        stmt = (
            select(MapPinORM).where(MapPinORM.map_id == map_id).order_by(MapPinORM.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_pin_orm_to_domain(o) for o in result.scalars().all()]

    async def add_pin(self, pin: MapPin) -> MapPin:
        """插入新 pin（id 由 DB 自增分配，读回时映射为 UUID）."""
        orm = _pin_domain_to_orm(pin)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _pin_orm_to_domain(orm)

    async def get_pin(self, pin_id: int) -> MapPin | None:
        """按主键查询 pin（不存在返回 None）."""
        stmt = select(MapPinORM).where(MapPinORM.id == pin_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _pin_orm_to_domain(orm) if orm else None

    async def update_pin(self, pin: MapPin) -> MapPin | None:
        """更新 pin（按 id 定位全字段覆盖；不存在 → None）."""
        pin_id = _uuid_to_int(pin.id)
        stmt = select(MapPinORM).where(MapPinORM.id == pin_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        orm.location_id = _uuid_to_int(pin.location_id) if pin.location_id is not None else None
        orm.type = pin.type
        orm.ref_id = _uuid_to_int(pin.ref_id) if pin.ref_id is not None else None
        orm.x = pin.x
        orm.y = pin.y
        orm.label = pin.label
        orm.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(orm)
        return _pin_orm_to_domain(orm)

    async def delete_pin(self, pin_id: int) -> bool:
        """真删 pin；重复删/不存在 → False."""
        result = await self._session.execute(sa_delete(MapPinORM).where(MapPinORM.id == pin_id))
        await self._session.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    # ── children（drill-down JOIN，评审 F2）──

    async def children(self, map_id: int) -> builtins.list[WorldMap]:
        """查询本图 pin 关联地点的子地图（drill-down，Q1=B）.

        单 SQL: JOIN map_pins p（p.map_id=:id AND p.location_id IS NOT NULL）
        JOIN world_settings w（w.id=p.location_id，v1.1 真删语义无 is_deleted 过滤）
        JOIN maps m2（m2.root_location_id=p.location_id）；
        DISTINCT；ORDER BY created_at ASC。
        """
        stmt = (
            select(MapORM)
            .join(
                MapPinORM,
                and_(
                    MapPinORM.map_id == map_id,
                    MapPinORM.location_id.isnot(None),
                ),
            )
            .join(
                WorldSettingORM,
                WorldSettingORM.id == MapPinORM.location_id,
            )
            .where(MapORM.root_location_id == MapPinORM.location_id)
            .distinct()
            .order_by(MapORM.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    # ── 共用查询 / 项目级操作（#175 / D10=b）──

    async def list_by_root_locations(
        self,
        project_id: int,
        location_ids: builtins.list[int],
        include_global: bool = True,
    ) -> builtins.list[WorldMap]:
        """按根地点集合查地图（#175 跨书复制共用查询；include_global=True 含全局图）.

        空列表入参 + include_global=False → 空列表；空列表 + True → 仅全局图；
        created_at ASC。
        """
        stmt = select(MapORM).where(MapORM.project_id == project_id)
        if not location_ids and not include_global:
            return []
        conds = []
        if location_ids:
            conds.append(MapORM.root_location_id.in_(location_ids))
        if include_global:
            conds.append(MapORM.root_location_id.is_(None))
        if conds:
            stmt = stmt.where(or_(*conds))
        stmt = stmt.order_by(MapORM.created_at.asc())
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def list_maps_by_project(self, project_id: int) -> builtins.list[WorldMap]:
        """收集项目全部地图（项目硬删钩子 cleanup 用，全量不分页）."""
        stmt = select(MapORM).where(MapORM.project_id == project_id)
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def delete_by_project(self, project_id: int) -> int:
        """单事务真删项目全部地图（先删 pins 再删 maps 行，D10=b）.

        Returns:
            删除的 maps 行数（项目硬删钩子）。
        """
        # 先删项目全部 pins（subquery 定位项目内 maps id）
        pin_stmt = sa_delete(MapPinORM).where(
            MapPinORM.map_id.in_(select(MapORM.id).where(MapORM.project_id == project_id))
        )
        await self._session.execute(pin_stmt)
        # 再删 maps 行
        result = await self._session.execute(
            sa_delete(MapORM).where(MapORM.project_id == project_id)
        )
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def clear_location_pins(self, location_id: int) -> int:
        """解除地点关联 pin（UPDATE map_pins SET location_id=NULL）.

        pin 保留、label 不变（D10=b 地点硬删钩子，SET NULL 由 service 显式执行）。
        """
        stmt = (
            sa_update(MapPinORM)
            .where(MapPinORM.location_id == location_id)
            .values(location_id=None, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def clear_ref_pins(self, ref_type: str, ref_ids: builtins.list[int]) -> int:
        """解除角色/事件关联 pin（UPDATE map_pins SET ref_id=NULL
        WHERE type=:t AND ref_id IN :ids）.

        pin 保留、label 不变（F43 P5 角色/事件硬删钩子，SET NULL 由 service
        显式执行，生产 foreign_keys=OFF 下不依赖 FK）。
        """
        stmt = (
            sa_update(MapPinORM)
            .where(MapPinORM.type == ref_type, MapPinORM.ref_id.in_(ref_ids))
            .values(ref_id=None, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def clear_map_root_locations(self, location_ids: builtins.list[int]) -> int:
        """解除地图根地点关联（UPDATE maps SET root_location_id=NULL
        WHERE root_location_id IN :ids）.

        F43 P5 地点硬删钩子扩展: 地点删除后其挂载图 root_location_id 置 NULL
        （图保留，仅解除根地点关联）。
        """
        stmt = (
            sa_update(MapORM)
            .where(MapORM.root_location_id.in_(location_ids))
            .values(root_location_id=None, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
