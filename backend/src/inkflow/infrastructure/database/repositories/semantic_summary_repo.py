"""SQLite 语义总结仓储 — F45 M2 语义风格提取的持久化（semantic_summaries 表）.

转换函数（_orm_to_domain）按项目惯例放在本仓储层（参照 preference_repo.py /
user_preference_repo.py）。

语义（spec §2.4/§5.3/§5.4，父侧契约 test_semantic_summary_repo.py docstring）：
- upsert: 按 (scope, project_id) 查找——存在 → 更新 content/anchor_hash/
  anchor_count/model（created_at 保留，updated_at 由 ORM onupdate 自动刷新）；
  不存在 → 插入新行（id 用 summary.id 否则 ORM default；created_at 用
  summary.created_at 否则 ORM default）；单次 commit + refresh（单工具单事务，
  ADR-F 约束①）
- get: 按 (scope, project_id) 精确匹配（scope=USER 时 project_id=None 查全局
  记录，spec §5.3 用户级总结全局单一性）
- list_all: scope 可空过滤，created_at asc 排序，返回 (列表, 总数)
- delete_by_project: 删除 scope=project 且 project_id 匹配的行（项目删除级联
  清理，spec §7 边界表）；scope=user 行不受影响

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与既有仓储惯例一致）。
"""

from __future__ import annotations

import builtins
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.semantic_summary import SemanticSummary, SummaryScope
from inkflow.infrastructure.database.models.semantic_summary import SemanticSummaryORM


def _orm_to_domain(orm: SemanticSummaryORM) -> SemanticSummary:
    """SemanticSummary ORM 行 → 领域实体（scope 字符串 → 枚举；project_id 字符串 → UUID）."""
    return SemanticSummary(
        id=orm.id,
        scope=SummaryScope(orm.scope),
        project_id=uuid.UUID(orm.project_id) if orm.project_id else None,
        content=orm.content,
        anchor_hash=orm.anchor_hash,
        anchor_count=orm.anchor_count,
        model=orm.model,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SQLiteSemanticSummaryRepository:
    """SQLite 语义总结仓储（session 注入，镜像 user_preference_repo 模式）."""

    def __init__(self, db_session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = db_session

    async def upsert(self, summary: SemanticSummary) -> SemanticSummary:
        """按 (scope, project_id) 幂等落库语义总结；存在 → 更新，不存在 → 插入.

        Args:
            summary: 待落库的领域实体（id/created_at 缺省时回退 ORM default）.

        Returns:
            落库后的 SemanticSummary（updated_at 由 ORM onupdate 自动刷新）.
        """
        stmt = select(SemanticSummaryORM).where(
            SemanticSummaryORM.scope == summary.scope.value
        )
        if summary.scope == SummaryScope.USER:
            stmt = stmt.where(SemanticSummaryORM.project_id.is_(None))
        else:
            stmt = stmt.where(SemanticSummaryORM.project_id == str(summary.project_id))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is not None:
            orm.content = summary.content
            orm.anchor_hash = summary.anchor_hash
            orm.anchor_count = summary.anchor_count
            orm.model = summary.model
        else:
            orm = SemanticSummaryORM(
                id=summary.id,
                scope=summary.scope.value,
                project_id=str(summary.project_id) if summary.project_id else None,
                content=summary.content,
                anchor_hash=summary.anchor_hash,
                anchor_count=summary.anchor_count,
                model=summary.model,
                created_at=summary.created_at,
            )
            self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(
        self,
        scope: SummaryScope,
        project_id: uuid.UUID | None = None,
    ) -> SemanticSummary | None:
        """按 (scope, project_id) 精确查询语义总结；缺失 → None.

        Args:
            scope: 归属范围（SummaryScope）.
            project_id: scope=PROJECT 时的项目 UUID；scope=USER 时传 None
                （查全局记录，spec §5.3 用户级总结全局单一性）.

        Returns:
            匹配的 SemanticSummary；无记录 → None.
        """
        stmt = select(SemanticSummaryORM).where(
            SemanticSummaryORM.scope == scope.value
        )
        if project_id is None:
            stmt = stmt.where(SemanticSummaryORM.project_id.is_(None))
        else:
            stmt = stmt.where(SemanticSummaryORM.project_id == str(project_id))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list_all(
        self,
        scope: SummaryScope | None = None,
    ) -> tuple[builtins.list[SemanticSummary], int]:
        """查询语义总结（scope 可空过滤），created_at asc 排序.

        Args:
            scope: 归属范围过滤（不传 = 全部）.

        Returns:
            (总结列表, 总结总数).
        """
        stmt = select(SemanticSummaryORM)
        if scope is not None:
            stmt = stmt.where(SemanticSummaryORM.scope == scope.value)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(SemanticSummaryORM.created_at.asc())
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()], total

    async def delete_by_project(self, project_id: uuid.UUID) -> int:
        """删除 scope=project 且 project_id 匹配的行，返回删除行数.

        Args:
            project_id: 被删除项目的 UUID.

        Returns:
            删除的语义总结行数（0 = 无该项目总结；scope=user 行不受影响）.
        """
        result = await self._session.execute(
            delete(SemanticSummaryORM).where(
                SemanticSummaryORM.scope == SummaryScope.PROJECT.value,
                SemanticSummaryORM.project_id == str(project_id),
            )
        )
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
