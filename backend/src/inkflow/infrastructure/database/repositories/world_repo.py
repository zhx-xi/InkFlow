"""SQLite 世界观条目仓储 — 实现 WorldRepositoryProtocol 全部 11 个方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参照 character_repo.py）。

语义（spec §2.4/§6/§7）:
- 项目内活动条目 name 唯一（partial unique index，ORM 层定义）；软删后可重建同名
- soft_delete = UPDATE is_deleted=1；hard_delete = DELETE
- get/get_by_name/list 一律排除已软删除条目
- list_categories 聚合活动条目类别计数（排除空类别 = 未分类，spec §6.1/§6.2）
- FK 级联: 项目物理删除 → 条目级联物理删除（DB FK CASCADE）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/world_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.world import WorldSetting
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


def _orm_to_domain(orm: WorldSettingORM) -> WorldSetting:
    """世界观条目 ORM 行 → 领域实体（int PK → UUID）."""
    return WorldSetting(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        category=orm.category,
        content=orm.content,
        extra=orm.extra or {},
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: WorldSetting) -> WorldSettingORM:
    """世界观条目领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return WorldSettingORM(
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        category=domain.category,
        content=domain.content,
        extra=domain.extra,
        is_deleted=domain.is_deleted,
    )


class SQLiteWorldRepository:
    """SQLite 世界观条目仓储 — 实现 WorldRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── WorldSetting ──

    async def add(self, setting: WorldSetting) -> WorldSetting:
        """插入新条目（id 由 DB 自增分配，读回时映射为 UUID）."""
        orm = _domain_to_orm(setting)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, setting_id: int) -> WorldSetting | None:
        """按主键查询条目（不含已软删除）."""
        stmt = select(WorldSettingORM).where(
            WorldSettingORM.id == setting_id,
            ~WorldSettingORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_name(self, project_id: int, name: str) -> WorldSetting | None:
        """按项目内条目名查询活动条目（不含已软删除）."""
        stmt = select(WorldSettingORM).where(
            WorldSettingORM.project_id == project_id,
            WorldSettingORM.name == name,
            ~WorldSettingORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        category: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[WorldSetting], int]:
        """分页查询项目内条目列表，支持搜索与类别过滤（不含已软删除）.

        Args:
            project_id: 项目主键（int）.
            search: 条目名模糊搜索（icontains，可选）.
            category: 类别精确过滤（可选；空串 = 未分类条目）.
            sort_by: 排序字段（updated_at / name / category / created_at）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (当前页条目列表, 符合条件的总记录数).
        """
        base = select(WorldSettingORM).where(
            WorldSettingORM.project_id == project_id,
            ~WorldSettingORM.is_deleted,
        )

        # 搜索: name icontains
        if search:
            base = base.where(WorldSettingORM.name.icontains(search))
        # 类别精确过滤（category= 空串 → 未分类条目）
        if category is not None:
            base = base.where(WorldSettingORM.category == category)

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页
        sort_col = getattr(WorldSettingORM, sort_by, WorldSettingORM.updated_at)
        base = base.order_by(sort_col.desc() if sort_desc else sort_col.asc())
        base = base.offset(offset).limit(limit)

        result = await self._session.execute(base)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total

    async def list_categories(self, project_id: int) -> builtins.list[tuple[str, int]]:
        """聚合项目内活动条目的类别计数（排除空类别 = 未分类）.

        按 spec §6.1/§6.2: 空类别视为未分类，不参与类别汇总（未分类条目
        通过 list(category=\"\") 查询）；返回 (类别, 条目数) 列表，
        按计数降序、类别名升序.

        Args:
            project_id: 项目主键（int）.

        Returns:
            (类别, 条目数) 列表，按计数降序、类别名升序.
        """
        stmt = (
            select(WorldSettingORM.category, func.count())
            .where(
                WorldSettingORM.project_id == project_id,
                ~WorldSettingORM.is_deleted,
                WorldSettingORM.category != "",
            )
            .group_by(WorldSettingORM.category)
            .order_by(func.count().desc(), WorldSettingORM.category.asc())
        )
        result = await self._session.execute(stmt)
        return [(category, count) for category, count in result.all()]

    async def update(self, setting: WorldSetting) -> WorldSetting:
        """更新条目（按 id 定位，updated_at 自动刷新）.

        Raises:
            ValueError: 条目不存在.
        """
        setting_id = _uuid_to_int(setting.id)
        stmt = (
            sa_update(WorldSettingORM)
            .where(WorldSettingORM.id == setting_id)
            .values(
                name=setting.name,
                category=setting.category,
                content=setting.content,
                extra=setting.extra,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"WorldSetting {setting_id} not found")

        stmt2 = select(WorldSettingORM).where(WorldSettingORM.id == setting_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"WorldSetting {setting_id} not found after update")
        return _orm_to_domain(orm)

    async def soft_delete(self, setting_id: int) -> bool:
        """软删除条目（is_deleted=True）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到/已删除.
        """
        stmt = (
            sa_update(WorldSettingORM)
            .where(WorldSettingORM.id == setting_id, ~WorldSettingORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def restore(self, setting_id: int) -> WorldSetting | None:
        """恢复已软删除条目.

        Returns:
            恢复后的 WorldSetting；记录不存在或未删除时返回 None（重复操作无毒）.
            若恢复导致项目内活动同名冲突（partial unique），commit 时抛 IntegrityError.
        """
        stmt = (
            sa_update(WorldSettingORM)
            .where(WorldSettingORM.id == setting_id, WorldSettingORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            await self._session.commit()
            return None
        await self._session.commit()
        return await self.get(setting_id)

    async def hard_delete(self, setting_id: int) -> bool:
        """物理删除条目（仅用于 force 场景）.

        Returns:
            True 表示删除成功，False 表示不存在.
        """
        stmt = select(WorldSettingORM).where(WorldSettingORM.id == setting_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True
