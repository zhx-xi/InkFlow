"""SQLite 偏好仓储 — F28 偏好学习闭环的持久化（结构化偏好表，非向量）.

转换函数（_orm_to_domain）按项目惯例放在本仓储层（参照 draft_repo.py /
foreshadowing_repo.py）.

语义（spec §5.2，父侧契约 test_preference_repo.py docstring）：
- create: 落库偏好（id 由 ORM default 生成 uuid4 字符串；created_at/updated_at=UTC），
  单次 commit + refresh（单工具单事务，ADR-F 约束①）
- get: 按偏好 id（uuid4 字符串）查询
- list_by_project: 按 project_id 过滤（category 可空=全部），count desc 排序
  （同 count 按 created_at asc），返回 (页内列表, 该项目偏好总数)
- update: 更新 count/confidence/source_events；preference_id 不存在 → None
- delete: 返回是否删除（rowcount > 0）
- delete_by_project: 删除该项目全部偏好，返回删除行数（服务层级联用）
- 领域 UUID → uuid4 字符串转换在仓储层（project_id 列存 str(uuid)，与 F27 先例一致）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与既有仓储惯例一致）。
"""

from __future__ import annotations

import builtins
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.preference import (
    PreferenceCategory,
    ProjectPreference,
)
from inkflow.infrastructure.database.models.preference import ProjectPreferenceORM


def _orm_to_domain(orm: ProjectPreferenceORM) -> ProjectPreference:
    """ProjectPreference ORM 行 → 领域实体（uuid 字符串 → UUID，分类字符串 → 枚举）."""
    return ProjectPreference(
        id=orm.id,
        project_id=uuid.UUID(orm.project_id),
        category=PreferenceCategory(orm.category),
        pattern=orm.pattern,
        value=orm.value,
        confidence=orm.confidence,
        count=orm.count,
        source_events=orm.source_events,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SQLitePreferenceRepository:
    """SQLite 偏好仓储（session 注入，镜像 F27 draft_repo 模式）."""

    def __init__(self, db_session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = db_session

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        category: PreferenceCategory,
        pattern: str,
        value: str,
        confidence: float,
        count: int,
        source_events: list[str],
    ) -> ProjectPreference:
        """创建偏好（id 由 ORM default 生成 uuid4 字符串），单次 commit + refresh.

        Args:
            project_id: 所属项目 UUID.
            category: 偏好分类.
            pattern: 模式描述（被替换的旧文本片段）.
            value: 偏好值（保留的新文本）.
            confidence: 置信度（0-1）.
            count: 支持事件数.
            source_events: 支持事件 id 列表（JSON 快照）.

        Returns:
            已落库的 ProjectPreference（id 为 uuid4 字符串，created_at/updated_at
            由 ORM default 生成的 UTC 时间）.
        """
        orm = ProjectPreferenceORM(
            project_id=str(project_id),
            category=category.value,
            pattern=pattern,
            value=value,
            confidence=confidence,
            count=count,
            source_events=source_events,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, preference_id: str) -> ProjectPreference | None:
        """按偏好 id（uuid4 字符串）查询；缺失 → None."""
        stmt = select(ProjectPreferenceORM).where(ProjectPreferenceORM.id == preference_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        category: PreferenceCategory | None = None,
    ) -> tuple[builtins.list[ProjectPreference], int]:
        """按项目 + 分类过滤查询偏好，count desc（同 count 按 created_at asc）.

        Args:
            project_id: 所属项目 UUID.
            category: 分类精确过滤（不传 = 全部）.

        Returns:
            (偏好列表, 该项目偏好总数).
        """
        stmt = select(ProjectPreferenceORM).where(
            ProjectPreferenceORM.project_id == str(project_id)
        )
        if category is not None:
            stmt = stmt.where(ProjectPreferenceORM.category == category.value)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(
            ProjectPreferenceORM.count.desc(),
            ProjectPreferenceORM.created_at.asc(),
        )
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()], total

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """统计该项目偏好总数（#252：memory_service.stats 按契约调用，方法缺失 → 500）.

        Args:
            project_id: 所属项目 UUID.

        Returns:
            该项目偏好总数（0 = 无偏好）.
        """
        stmt = (
            select(func.count())
            .select_from(ProjectPreferenceORM)
            .where(ProjectPreferenceORM.project_id == str(project_id))
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def update(
        self,
        preference_id: str,
        *,
        count: int,
        confidence: float,
        source_events: list[str],
        category: PreferenceCategory | None = None,
        pattern: str | None = None,
        value: str | None = None,
    ) -> ProjectPreference | None:
        """更新 count/confidence/source_events 及编辑字段（#521）；preference_id 不存在 → None.

        Args:
            preference_id: 偏好 id（uuid4 字符串）.
            count: 新的支持事件数.
            confidence: 新的置信度.
            source_events: 新的支持事件 id 列表.
            category: 编辑字段（非 None 覆盖；存枚举 value 字符串）.
            pattern: 编辑字段（非 None 覆盖）.
            value: 编辑字段（非 None 覆盖）.

        Returns:
            更新后的 ProjectPreference（updated_at 由 ORM onupdate 自动刷新）；
            preference_id 不存在 → None.
        """
        orm = await self._session.get(ProjectPreferenceORM, preference_id)
        if orm is None:
            return None
        orm.count = count
        orm.confidence = confidence
        orm.source_events = source_events
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
        """按 id 删除偏好，返回是否删除（rowcount > 0）."""
        result = await self._session.execute(
            delete(ProjectPreferenceORM).where(ProjectPreferenceORM.id == preference_id)
        )
        await self._session.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def delete_by_project(self, project_id: uuid.UUID) -> int:
        """删除该项目全部偏好，返回删除行数（服务层级联用）.

        Args:
            project_id: 所属项目 UUID.

        Returns:
            删除的偏好行数（0 = 项目原本无偏好）.
        """
        result = await self._session.execute(
            delete(ProjectPreferenceORM).where(ProjectPreferenceORM.project_id == str(project_id))
        )
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
