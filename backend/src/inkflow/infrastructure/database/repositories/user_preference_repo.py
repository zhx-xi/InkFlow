"""SQLite 用户级偏好仓储 — F45 M1 用户级偏好闭环的持久化（全局跨项目表）.

转换函数（_orm_to_domain）按项目惯例放在本仓储层（参照 preference_repo.py）.

语义（spec §2.1/§2.4，父侧契约 test_user_preference_repo.py docstring）：
- create: 落库用户级偏好（id 由 ORM default 生成 uuid4 字符串；created_at/
  updated_at=UTC），单次 commit + refresh（单工具单事务，ADR-F 约束①）
- get: 按偏好 id（uuid4 字符串）查询
- list_all: category 可空过滤（不传 = 全部），count desc 排序（同 count 按
  created_at asc），返回 (列表, 总数)
- update: 更新 count/confidence/project_count/source_projects/source_events；
  preference_id 不存在 → None
- delete: 返回是否删除（rowcount > 0）
- delete_by_project_ref: 删除 source_projects JSON 中含该项目 id 的行，返回
  删除行数（Q1=B 惰性重算：项目删除钩子零成本，查询/collect 时全量过滤）
- 全局表无 project_id 列；uuid4 字符串列形态与 F28 preference_repo 一致

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与既有仓储惯例一致）。
"""

from __future__ import annotations

import builtins
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.preference import PreferenceCategory
from inkflow.domain.models.user_preference import UserPreference
from inkflow.infrastructure.database.models.user_preference import UserPreferenceORM


def _orm_to_domain(orm: UserPreferenceORM) -> UserPreference:
    """UserPreference ORM 行 → 领域实体（分类字符串 → 枚举；JSON 列表原样）."""
    return UserPreference(
        id=orm.id,
        category=PreferenceCategory(orm.category),
        pattern=orm.pattern,
        value=orm.value,
        confidence=orm.confidence,
        count=orm.count,
        project_count=orm.project_count,
        source_projects=orm.source_projects,
        source_events=orm.source_events,
        active_watermark_at_last_access=orm.active_watermark_at_last_access,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SQLiteUserPreferenceRepository:
    """SQLite 用户级偏好仓储（session 注入，镜像 F28 preference_repo 模式）."""

    def __init__(self, db_session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = db_session

    async def create(
        self,
        *,
        category: PreferenceCategory,
        pattern: str,
        value: str,
        confidence: float,
        count: int,
        project_count: int,
        source_projects: list[str],
        source_events: list[str],
        active_watermark_at_last_access: float = 0.0,
    ) -> UserPreference:
        """创建用户级偏好（id 由 ORM default 生成 uuid4 字符串），单次 commit + refresh.

        Args:
            category: 偏好分类.
            pattern: 模式描述（被替换的旧文本片段）.
            value: 偏好值（保留的新文本）.
            confidence: 置信度（0-1）.
            count: 支撑事件数（跨项目累计）.
            project_count: 支撑项目数.
            source_projects: 支撑项目 id 字符串列表（JSON 快照）.
            source_events: 支撑事件 id 列表（JSON 快照）.
            active_watermark_at_last_access: 上次注入/访问时的项目活跃水位（float，默认 0.0）.

        Returns:
            已落库的 UserPreference（id 为 uuid4 字符串，created_at/updated_at
            由 ORM default 生成的 UTC 时间）.
        """
        orm = UserPreferenceORM(
            category=category.value,
            pattern=pattern,
            value=value,
            confidence=confidence,
            count=count,
            project_count=project_count,
            source_projects=source_projects,
            source_events=source_events,
            active_watermark_at_last_access=active_watermark_at_last_access,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, preference_id: str) -> UserPreference | None:
        """按偏好 id（uuid4 字符串）查询；缺失 → None."""
        stmt = select(UserPreferenceORM).where(UserPreferenceORM.id == preference_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list_all(
        self,
        category: PreferenceCategory | None = None,
    ) -> tuple[builtins.list[UserPreference], int]:
        """查询用户级偏好（全局表无项目过滤），count desc（同 count 按 created_at asc）.

        Args:
            category: 分类精确过滤（不传 = 全部）.

        Returns:
            (偏好列表, 偏好总数).
        """
        stmt = select(UserPreferenceORM)
        if category is not None:
            stmt = stmt.where(UserPreferenceORM.category == category.value)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(
            UserPreferenceORM.count.desc(),
            UserPreferenceORM.created_at.asc(),
        )
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()], total

    async def update(
        self,
        preference_id: str,
        *,
        count: int,
        confidence: float,
        project_count: int,
        source_projects: list[str],
        source_events: list[str],
        active_watermark_at_last_access: float | None = None,
        category: PreferenceCategory | None = None,
        pattern: str | None = None,
        value: str | None = None,
    ) -> UserPreference | None:
        """更新统计字段及编辑字段（#521）；preference_id 不存在 → None.

        Args:
            preference_id: 偏好 id（uuid4 字符串）.
            count: 新的支撑事件数.
            confidence: 新的置信度.
            project_count: 新的支撑项目数.
            source_projects: 新的支撑项目 id 列表.
            source_events: 新的支撑事件 id 列表.
            active_watermark_at_last_access: 刷新水位字段（非 None 覆盖；F49 #617「用即保鲜」）.
            category: 编辑字段（非 None 覆盖；存枚举 value 字符串）.
            pattern: 编辑字段（非 None 覆盖）.
            value: 编辑字段（非 None 覆盖）.

        Returns:
            更新后的 UserPreference（updated_at 由 ORM onupdate 自动刷新）；
            preference_id 不存在 → None.
        """
        orm = await self._session.get(UserPreferenceORM, preference_id)
        if orm is None:
            return None
        orm.count = count
        orm.confidence = confidence
        orm.project_count = project_count
        orm.source_projects = source_projects
        orm.source_events = source_events
        if active_watermark_at_last_access is not None:
            orm.active_watermark_at_last_access = active_watermark_at_last_access
        if category is not None:
            orm.category = category.value
        if pattern is not None:
            orm.pattern = pattern
        if value is not None:
            orm.value = value
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def delete(self, preference_id: str) -> bool:
        """按 id 删除用户级偏好，返回是否删除（rowcount > 0）."""
        result = await self._session.execute(
            delete(UserPreferenceORM).where(UserPreferenceORM.id == preference_id)
        )
        await self._session.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def delete_by_project_ref(self, project_id: uuid.UUID) -> int:
        """删除 source_projects JSON 中含该项目 id 的行，返回删除行数（Q1=B 惰性重算）.

        SQLAlchemy 无跨方言 JSON contains 函数——全量 list + 逐条判断（简单可测），
        一次 commit 批量删除。删除后 source_projects 含该项目的偏好即刻消失，
        其余行不受影响.

        Args:
            project_id: 被删除项目的 UUID.

        Returns:
            删除的用户级偏好行数（0 = 无偏好引用该项目）.
        """
        project_str = str(project_id)
        stmt = select(UserPreferenceORM)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        to_delete = [orm for orm in rows if project_str in (orm.source_projects or [])]
        for orm in to_delete:
            await self._session.delete(orm)
        await self._session.commit()
        return len(to_delete)
