"""SQLite 伏笔仓储 — 实现 ForeshadowingRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参照 timeline_repo.py / character_repo.py / world_repo.py）。

语义（spec §2/§6/§8.1，v1.1 真删）:
- 项目内伏笔同名唯一（全唯一索引，spec §2.3）:
  「同名 = 同一伏笔」——伏笔是档案而非实例；删除 = 物理 DELETE
- get/get_by_title/list/list_open 查询全部伏笔（真删后不存在软删记录）
- list 默认按 priority DESC 排序（spec §6.3，与 F6 注入顺序一致）；
  sort_by 白名单 priority/title/status/updated_at/created_at
  （无 narrative_position——v1.1 已移除该字段）；status 精确过滤
  （不传 = 全部活动伏笔）
- list_open = F6 注入集合: status="open"，
  按 (priority DESC, updated_at DESC) 排序（spec §5.3/§8.1）
- event_id 为 nullable FK → timeline_events.id（ON DELETE SET NULL）:
  事件硬删 → event_id 自动置 NULL（挂接解除，软删事件不影响锚点，spec §2.1）
- FK 级联: 项目物理删除 → 伏笔级联物理删除（DB FK CASCADE）
- update 写 status/resolved_at（服务层状态迁移 resolve/reopen 经 update
  落库，spec §2.4/§5.2）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/foreshadowing_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingStatus
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM


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


def _orm_to_domain(orm: ForeshadowingORM) -> Foreshadowing:
    """伏笔 ORM 行 → 领域实体（int PK → UUID；event_id 可空）."""
    return Foreshadowing(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        title=orm.title,
        description=orm.description,
        priority=orm.priority,
        status=ForeshadowingStatus(orm.status),
        location=orm.location,
        event_id=_int_to_uuid(orm.event_id),
        resolved_at=orm.resolved_at,
        extra=orm.extra or {},
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: Foreshadowing) -> ForeshadowingORM:
    """伏笔领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return ForeshadowingORM(
        project_id=_uuid_to_int(domain.project_id),
        title=domain.title,
        description=domain.description,
        priority=domain.priority,
        status=domain.status.value,
        location=domain.location,
        event_id=_uuid_to_int(domain.event_id) if domain.event_id is not None else None,
        resolved_at=domain.resolved_at,
        extra=domain.extra,
    )


class SQLiteForeshadowingRepository:
    """SQLite 伏笔仓储 — 实现 ForeshadowingRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Foreshadowing ──

    async def add(self, f: Foreshadowing) -> Foreshadowing:
        """插入新伏笔（id 由 DB 自增分配，读回时映射为 UUID）.

        同名冲突（partial unique，spec §2.3）由 DB 抛出 IntegrityError 冒泡，
        服务层先经 get_by_title 检查给出友好 422 文案。
        """
        orm = _domain_to_orm(f)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, foreshadowing_id: int) -> Foreshadowing | None:
        """按主键查询伏笔."""
        stmt = select(ForeshadowingORM).where(ForeshadowingORM.id == foreshadowing_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_title(self, project_id: int, title: str) -> Foreshadowing | None:
        """按 (project_id, title) 查询伏笔.

        同名唯一性检查用（spec §2.3 全唯一索引语义）：真删后同名可重建。
        """
        stmt = select(ForeshadowingORM).where(
            ForeshadowingORM.project_id == project_id,
            ForeshadowingORM.title == title,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        status: str | None = None,
        sort_by: str = "priority",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[Foreshadowing], int]:
        """分页查询项目内伏笔列表，支持标题模糊搜索、状态过滤与排序.

        Args:
            project_id: 项目主键（int）.
            search: 伏笔名不区分大小写子串匹配（可选）.
            status: 状态精确过滤（open / resolved；不传 = 全部伏笔）.
            sort_by: 排序字段（priority / title / status / updated_at /
                created_at；伏笔语境下默认 priority，与注入顺序一致）.
            sort_desc: 是否倒序（默认 True，priority 大者在前；priority
                相等时按 updated_at DESC 兜底稳定排序，spec §6.2）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (伏笔列表, 总数) 元组.
        """
        base = select(ForeshadowingORM).where(ForeshadowingORM.project_id == project_id)

        # 搜索: title icontains
        if search:
            base = base.where(ForeshadowingORM.title.icontains(search))
        # 状态精确过滤（不传 = 全部活动）
        if status is not None:
            base = base.where(ForeshadowingORM.status == status)

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页（白名单之外的 sort_by 回退到 priority）
        sort_col = getattr(ForeshadowingORM, sort_by, ForeshadowingORM.priority)
        if sort_by == "priority":
            # 稳定排序: 同优先级按 updated_at DESC 兜底（spec §6.2）
            order: tuple = (
                (sort_col.desc(), ForeshadowingORM.updated_at.desc())
                if sort_desc
                else (sort_col.asc(), ForeshadowingORM.updated_at.desc())
            )
        else:
            order = (sort_col.desc() if sort_desc else sort_col.asc(),)
        base = base.order_by(*order)
        base = base.offset(offset).limit(limit)

        result = await self._session.execute(base)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total

    async def list_open(self, project_id: int) -> builtins.list[Foreshadowing]:
        """列出项目内全部未回收伏笔（status=open），供 F6 注入消费.

        返回顺序即 F6 注入顺序：按 (priority DESC, updated_at DESC) 排序
        （spec §6.2/§6.3；priority 为注入优先级键，大者先注入；相等时按
        updated_at 兜底稳定排序）。F6 dynamic 层直接消费此结果（spec §5.3）.
        """
        stmt = (
            select(ForeshadowingORM)
            .where(
                ForeshadowingORM.project_id == project_id,
                ForeshadowingORM.status == "open",
            )
            .order_by(
                ForeshadowingORM.priority.desc(),
                ForeshadowingORM.updated_at.desc(),
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms]

    async def update(self, f: Foreshadowing) -> Foreshadowing:
        """更新伏笔（按 id 定位，updated_at 自动刷新）.

        含 status/resolved_at（服务层状态迁移 resolve/reopen 经 update 落库，
        spec §2.4/§5.2）。

        Raises:
            ValueError: 伏笔不存在.
        """
        foreshadowing_id = _uuid_to_int(f.id)
        stmt = (
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == foreshadowing_id)
            .values(
                title=f.title,
                description=f.description,
                priority=f.priority,
                status=f.status.value,
                location=f.location,
                event_id=_uuid_to_int(f.event_id) if f.event_id is not None else None,
                resolved_at=f.resolved_at,
                extra=f.extra,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
            raise ValueError(f"Foreshadowing {foreshadowing_id} not found")

        stmt2 = select(ForeshadowingORM).where(ForeshadowingORM.id == foreshadowing_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"Foreshadowing {foreshadowing_id} not found after update")
        return _orm_to_domain(orm)

    async def hard_delete(self, foreshadowing_id: int) -> bool:
        """物理删除伏笔（v1.1 默认真删语义）.

        Returns:
            True 表示删除成功，False 表示不存在.
        """
        stmt = select(ForeshadowingORM).where(ForeshadowingORM.id == foreshadowing_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True
