"""SQLite 世界观条目仓储 — 实现 WorldRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参照 character_repo.py）。

语义（spec §2.4/§6/§7，v1.1 真删）:
- 项目内条目 name 唯一（全唯一索引，ORM 层定义）；删除 = 物理 DELETE
- get/get_by_name/list 查询全部条目（真删后不存在软删记录）
- list_categories 聚合条目类别计数（排除空类别 = 未分类，spec §6.1/§6.2）
- FK 级联: 项目物理删除 → 条目级联物理删除（DB FK CASCADE）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/world_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.world import WorldCategory, WorldSetting
from inkflow.infrastructure.database.models.world import WorldCategoryORM, WorldSettingORM


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
        parent_id=_int_to_uuid(orm.parent_id),
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
        parent_id=_uuid_to_int(domain.parent_id) if domain.parent_id is not None else None,
    )


def _category_orm_to_domain(orm: WorldCategoryORM) -> WorldCategory:
    """分类 ORM 行 → 领域实体（int PK → UUID）."""
    return WorldCategory(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        kind=orm.kind,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _category_domain_to_orm(domain: WorldCategory) -> WorldCategoryORM:
    """分类领域实体 → ORM 行（UUID → int；id/时间戳由 DB 自增/默认分配）."""
    return WorldCategoryORM(
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        kind=domain.kind,
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
        """按主键查询条目."""
        stmt = select(WorldSettingORM).where(WorldSettingORM.id == setting_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_name(self, project_id: int, name: str) -> WorldSetting | None:
        """按项目内条目名查询条目.

        跨层同名多条时返回最早创建（created_at ASC）的一条（spec §2.4 确定性）。
        """
        stmt = (
            select(WorldSettingORM)
            .where(
                WorldSettingORM.project_id == project_id,
                WorldSettingORM.name == name,
            )
            .order_by(WorldSettingORM.created_at.asc())
            .limit(1)
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
        parent_id: int | None = None,
        top_level_only: bool = False,
    ) -> tuple[builtins.list[WorldSetting], int]:
        """分页查询项目内条目列表，支持搜索、类别与 parent_id 过滤.

        Args:
            project_id: 项目主键（int）.
            search: 条目名模糊搜索（icontains，可选）.
            category: 类别精确过滤（可选；空串 = 未分类条目）.
            sort_by: 排序字段（updated_at / name / category / created_at）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.
            parent_id: 直接父级过滤（可选；top_level_only=False 时生效）.
            top_level_only: True 只返回顶层（parent_id IS NULL）.

        Returns:
            (当前页条目列表, 符合条件的总记录数).
        """
        base = select(WorldSettingORM).where(WorldSettingORM.project_id == project_id)

        # 搜索: name icontains
        if search:
            base = base.where(WorldSettingORM.name.icontains(search))
        # 类别精确过滤（category= 空串 → 未分类条目）
        if category is not None:
            base = base.where(WorldSettingORM.category == category)
        # F35: 列表 parent_id 过滤（Q3=A）——top_level_only 与 parent_id 为 AND 语义
        # （Protocol docstring: 「先 top_level_only 过滤再加 parent_id 条件」）；缺省全量向后兼容
        if top_level_only:
            base = base.where(WorldSettingORM.parent_id.is_(None))
        if parent_id is not None:
            base = base.where(WorldSettingORM.parent_id == parent_id)

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
        """聚合项目内条目的类别计数（排除空类别 = 未分类）.

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
        parent_id = _uuid_to_int(setting.parent_id) if setting.parent_id is not None else None
        stmt = (
            sa_update(WorldSettingORM)
            .where(WorldSettingORM.id == setting_id)
            .values(
                name=setting.name,
                category=setting.category,
                content=setting.content,
                extra=setting.extra,
                parent_id=parent_id,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
            raise ValueError(f"WorldSetting {setting_id} not found")

        stmt2 = select(WorldSettingORM).where(WorldSettingORM.id == setting_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"WorldSetting {setting_id} not found after update")
        return _orm_to_domain(orm)

    async def hard_delete(self, setting_id: int) -> bool:
        """物理删除条目（v1.1 默认真删语义）.

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

    async def get_by_parent_and_name(
        self, project_id: int, parent_id: int | None, name: str
    ) -> WorldSetting | None:
        """按 (project_id, parent_id, name) 查询条目（parent_id=None = 顶层）."""
        stmt = select(WorldSettingORM).where(
            WorldSettingORM.project_id == project_id,
            WorldSettingORM.name == name,
        )
        if parent_id is None:
            stmt = stmt.where(WorldSettingORM.parent_id.is_(None))
        else:
            stmt = stmt.where(WorldSettingORM.parent_id == parent_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def collect_ancestor_ids(self, setting_id: int) -> builtins.list[int]:
        """祖先链 id 列表，**不含自身**（父链 [父, 祖父, ...]，spec §5.2 循环防护用）.

        递归 CTE：起点 = 自身（仅当有父），结果排除自身。
        """
        sql = text(
            """
            WITH RECURSIVE ancestors(id, parent_id) AS (
              SELECT w.id, w.parent_id FROM world_settings w
              WHERE w.parent_id IS NOT NULL AND w.id = :sid
              UNION ALL
              SELECT w.id, w.parent_id FROM world_settings w
              JOIN ancestors a ON w.id = a.parent_id
            )
            SELECT id FROM ancestors WHERE id != :sid
            """
        )
        result = await self._session.execute(sql, {"sid": setting_id})
        return [row[0] for row in result.fetchall()]

    async def list_descendants(self, setting_id: int) -> builtins.list[WorldSetting]:
        """子树（**含自身**），层序（父先子后，同层 created_at ASC）.

        两段式：CTE 取层序 id 集合（depth 升序 + created_at ASC），再按 id 批量查 ORM
        行（类型处理完整），Python 侧按 CTE 顺序重排，确保层序稳定。
        """
        sql = text(
            """
            WITH RECURSIVE descendants(id, depth, created_at) AS (
              SELECT id, 0, created_at FROM world_settings WHERE id = :sid
              UNION ALL
              SELECT w.id, d.depth + 1, w.created_at FROM world_settings w
              JOIN descendants d ON w.parent_id = d.id
            )
            SELECT id FROM descendants
            ORDER BY depth ASC, created_at ASC
            """
        )
        result = await self._session.execute(sql, {"sid": setting_id})
        ordered_ids = [row[0] for row in result.fetchall()]
        if not ordered_ids:
            return []
        stmt = select(WorldSettingORM).where(WorldSettingORM.id.in_(ordered_ids))
        rows = (await self._session.execute(stmt)).scalars().all()
        by_id = {orm.id: _orm_to_domain(orm) for orm in rows}
        return [by_id[sid] for sid in ordered_ids if sid in by_id]

    async def list_all_active(self, project_id: int) -> builtins.list[WorldSetting]:
        """项目内全部条目，按 created_at ASC 稳定排序（copy 缺省起点用）."""
        stmt = (
            select(WorldSettingORM)
            .where(WorldSettingORM.project_id == project_id)
            .order_by(WorldSettingORM.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def hard_delete_many(self, setting_ids: builtins.list[int]) -> int:
        """单事务原子物理删除（DELETE WHERE id IN (...)），返回删除行数."""
        if not setting_ids:
            return 0
        stmt = sa_delete(WorldSettingORM).where(WorldSettingORM.id.in_(setting_ids))
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 未声明 rowcount（属性在底层 cursor）

    async def delete_with_reparent(self, setting_id: int, reparent_to: int) -> bool:
        """单事务: UPDATE 直接子地点 parent_id=reparent_to WHERE parent_id=setting_id
        + DELETE 自身；返回自身是否被删（不存在 → False）."""
        # ① 子地点改挂新父
        upd = (
            sa_update(WorldSettingORM)
            .where(WorldSettingORM.parent_id == setting_id)
            .values(parent_id=reparent_to, updated_at=_utcnow())
        )
        await self._session.execute(upd)
        # ② 删除自身
        stmt = select(WorldSettingORM).where(WorldSettingORM.id == setting_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            await self._session.commit()
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    # ── WorldCategory（v1.2，issue #389）──────────────────────────

    async def create_category(
        self, project_id: int | uuid.UUID, name: str, kind: str = "geo"
    ) -> WorldCategory:
        """创建分类（id 由 DB 自增分配；(project_id, name) 全唯一索引兜底同名冲突）.

        返回领域实体 WorldCategory（id 为 UUID，映射惯例同条目 `_orm_to_domain`；
        读取方法 get_category 以 `.id.int` 传 DB 主键）。
        """
        pid = _uuid_to_int(project_id)
        domain = WorldCategory(
            id=uuid.uuid4(),
            project_id=uuid.UUID(int=pid),
            name=name,
            kind=kind,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        orm = _category_domain_to_orm(domain)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _category_orm_to_domain(orm)

    async def get_category(self, category_id: uuid.UUID) -> WorldCategory | None:
        """按主键查询分类."""
        stmt = select(WorldCategoryORM).where(WorldCategoryORM.id == _uuid_to_int(category_id))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _category_orm_to_domain(orm) if orm else None

    async def get_category_by_name(
        self, project_id: int | uuid.UUID, name: str
    ) -> WorldCategory | None:
        """按 (project_id, name) 查询分类."""
        stmt = select(WorldCategoryORM).where(
            WorldCategoryORM.project_id == _uuid_to_int(project_id),
            WorldCategoryORM.name == name,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _category_orm_to_domain(orm) if orm else None

    async def list_world_categories(
        self, project_id: int | uuid.UUID
    ) -> builtins.list[tuple[WorldCategory, int]]:
        """分类实体列表 + 每个分类名匹配的条目计数（排除空类别，spec §6.1）."""
        pid = _uuid_to_int(project_id)
        cats_stmt = (
            select(WorldCategoryORM)
            .where(WorldCategoryORM.project_id == pid)
            .order_by(WorldCategoryORM.id.asc())
        )
        cats = (await self._session.execute(cats_stmt)).scalars().all()
        count_stmt = (
            select(WorldSettingORM.category, func.count())
            .where(
                WorldSettingORM.project_id == pid,
                WorldSettingORM.category != "",
            )
            .group_by(WorldSettingORM.category)
        )
        counts = {
            str(category): int(cnt)
            for category, cnt in (await self._session.execute(count_stmt)).all()
        }
        return [(_category_orm_to_domain(c), counts.get(c.name, 0)) for c in cats]

    async def rename_category(self, category_id: uuid.UUID, name: str) -> WorldCategory | None:
        """重命名分类 + 反向同步条目 category（同一事务，spec §6.1 D2=A）."""
        cid = _uuid_to_int(category_id)
        stmt = select(WorldCategoryORM).where(WorldCategoryORM.id == cid)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        old_name = orm.name
        # 先反向同步条目（category=<旧名> → <新名>），再改分类行（同一事务）
        await self._session.execute(
            sa_update(WorldSettingORM)
            .where(
                WorldSettingORM.project_id == orm.project_id,
                WorldSettingORM.category == old_name,
            )
            .values(category=name, updated_at=_utcnow())
        )
        orm.name = name
        await self._session.commit()
        await self._session.refresh(orm)
        return _category_orm_to_domain(orm)

    async def delete_category(self, category_id: uuid.UUID) -> bool:
        """删除分类 + 反向清空条目 category（同一事务，spec §6.1 D2=A）."""
        cid = _uuid_to_int(category_id)
        stmt = select(WorldCategoryORM).where(WorldCategoryORM.id == cid)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        # 先反向清空条目（category=<分类名> → '' 未分类），再物理删除分类行（同一事务）
        await self._session.execute(
            sa_update(WorldSettingORM)
            .where(
                WorldSettingORM.project_id == orm.project_id,
                WorldSettingORM.category == orm.name,
            )
            .values(category="", updated_at=_utcnow())
        )
        await self._session.delete(orm)
        await self._session.commit()
        return True
