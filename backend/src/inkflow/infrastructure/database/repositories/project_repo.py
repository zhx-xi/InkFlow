"""SQLite 项目仓储实现 — 基于 SQLAlchemy async session.

实现 ProjectRepositoryProtocol 的全部 7 个方法:
add, get, list_all, update, soft_delete, restore, hard_delete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.database.models.agent import AgentExecutionORM, AgentStageResultORM
from inkflow.infrastructure.database.models.agent_run import AgentRunORM, DraftORM
from inkflow.infrastructure.database.models.planner_session import PlannerSessionORM
from inkflow.infrastructure.database.models.preference import MemoryEventORM, ProjectPreferenceORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.semantic_summary import SemanticSummaryORM
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM
from inkflow.infrastructure.database.repositories._id_guard import require_uuid_pk


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _orm_to_domain(orm: ProjectORM) -> Project:
    """Convert ORM row to domain model.

    Handles type conversions: ORM uses int PK, domain expects UUID.
    """
    return Project(
        id=uuid.UUID(int=orm.id) if isinstance(orm.id, int) else orm.id,
        name=orm.name,
        tags=orm.tags or [],
        language=orm.language,
        target_words=orm.target_words,
        config=ProjectConfig(**orm.config) if orm.config else ProjectConfig(),
        active_watermark=orm.active_watermark,
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _get_config_dict(config: Any) -> dict:
    """Extract a plain dict from ProjectConfig or dict."""
    if isinstance(config, ProjectConfig):
        return config.model_dump()
    if isinstance(config, dict):
        return config
    return {}


# #1371：无 FK 子表族表名 —— project_id 是 String(36) 存 str(uuid)，而 projects.id 是 int
# （列类型不匹配 → 无法加 FK），故 #327 的 DB 级 CASCADE 覆盖不到，硬删项目须显式清理。
# 新增此类表（project_id 为 String 且无 FK）时必须同步登记：漂移由
# tests/unit/infrastructure/database/test_project_cascade.py 的元数据守护断言拦截。
STRING_PID_CHILD_TABLES: frozenset[str] = frozenset(
    {
        "agent_executions",
        "agent_runs",
        "drafts",
        "memory_events",
        "planner_sessions",
        "project_preferences",
        "semantic_summaries",
        "writing_plans",
    }
)


class SQLiteProjectRepository:
    """SQLite 项目仓储 — 实现 ProjectRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> Project:
        """新增项目.

        创建 ORM 对象，commit，refresh，返回 domain 对象.
        """
        orm = ProjectORM(
            name=project.name,
            tags=project.tags,
            language=project.language,
            target_words=project.target_words,
            config=_get_config_dict(project.config),
            active_watermark=project.active_watermark,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, project_id: uuid.UUID) -> Project | None:
        """按主键查询项目（排除软删除记录）。超 int64 范围视为不存在（SQLite 整数溢出防御）.

        #1134 批 4（#1291）：入参收窄为 ``uuid.UUID`` —— #1230 ⑤ 的 int 兼容面已退役。
        """
        pid = require_uuid_pk(project_id)
        if pid is None:
            return None
        stmt = select(ProjectORM).where(
            ProjectORM.id == pid,
            ~ProjectORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return _orm_to_domain(orm)

    async def list_all(
        self,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Project], int]:
        """分页列举项目，支持搜索、排序.

        Returns:
            (当前页项目列表, 符合条件的总记录数).
        """
        # Base query: exclude soft-deleted
        base = select(ProjectORM).where(~ProjectORM.is_deleted)

        # Search filter: name icontains
        if search:
            base = base.where(ProjectORM.name.icontains(search))

        # Count total matching records (before pagination)
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # Sorting
        sort_col = getattr(ProjectORM, sort_by, ProjectORM.updated_at)
        base = base.order_by(sort_col.desc()) if sort_desc else base.order_by(sort_col.asc())

        # Pagination
        base = base.offset(offset).limit(limit)

        # Execute and convert
        result = await self._session.execute(base)
        orms = result.scalars().all()

        return [_orm_to_domain(o) for o in orms], total

    async def update(self, project: Project) -> Project:
        """更新项目.

        使用 sqlalchemy.update 更新指定字段，然后重新查询返回完整 Project.
        """
        project_id = project.id

        # Convert id to int if it's a UUID (reverse the int→UUID mapping)
        actual_id = project_id.int if isinstance(project_id, uuid.UUID) else project_id

        values: dict[str, Any] = {
            "name": project.name,
            "tags": project.tags,
            "language": project.language,
            "target_words": project.target_words,
            "config": _get_config_dict(project.config),
            "active_watermark": project.active_watermark,
            "updated_at": _utcnow(),
        }

        stmt = sa_update(ProjectORM).where(ProjectORM.id == actual_id).values(**values)
        await self._session.execute(stmt)
        await self._session.commit()

        # Re-query and return domain model
        result = await self._session.execute(select(ProjectORM).where(ProjectORM.id == actual_id))
        orm = result.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"Project with id {actual_id} not found after update")
        return _orm_to_domain(orm)

    async def soft_delete(self, project_id: uuid.UUID) -> bool:
        """软删除项目（标记 is_deleted=True）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        pid = require_uuid_pk(project_id)
        if pid is None:
            return False
        stmt = (
            sa_update(ProjectORM)
            .where(ProjectORM.id == pid, ~ProjectORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def restore(self, project_id: uuid.UUID) -> Project | None:
        """恢复软删除的项目（设置 is_deleted=False）.

        Returns:
            恢复后的 Project，若记录不存在则返回 None.
        """
        pid = require_uuid_pk(project_id)
        if pid is None:
            return None
        stmt = (
            sa_update(ProjectORM)
            .where(ProjectORM.id == pid, ProjectORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()

        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
            return None

        return await self.get(project_id)

    async def _purge_string_pid_children(self, pid: int) -> None:
        """按 project_id 清理无 FK 子表族（#1371）.

        - 列存 ``str(uuid)`` → 删除条件用 ``str(uuid.UUID(int=pid))``（与写入同源）；
        - ``agent_stage_results`` 无 project_id，经 ``execution_id``（FK 无 ondelete →
          RESTRICT）挂在 agent_executions 下：必须先按 execution_id 清，否则 DB FK 拦截；
        - ``semantic_summaries`` 的 scope=user 行 project_id 为 NULL（用户级总结）→
          条件不匹配，天然保留；
        - 覆盖表集与模块常量 ``STRING_PID_CHILD_TABLES`` 一致。
        """
        key = str(uuid.UUID(int=pid))
        execution_ids = select(AgentExecutionORM.id).where(AgentExecutionORM.project_id == key)
        await self._session.execute(
            sa_delete(AgentStageResultORM).where(
                AgentStageResultORM.execution_id.in_(execution_ids)
            )
        )
        await self._session.execute(
            sa_delete(AgentExecutionORM).where(AgentExecutionORM.project_id == key)
        )
        await self._session.execute(sa_delete(AgentRunORM).where(AgentRunORM.project_id == key))
        await self._session.execute(sa_delete(DraftORM).where(DraftORM.project_id == key))
        await self._session.execute(
            sa_delete(MemoryEventORM).where(MemoryEventORM.project_id == key)
        )
        await self._session.execute(
            sa_delete(PlannerSessionORM).where(PlannerSessionORM.project_id == key)
        )
        await self._session.execute(
            sa_delete(ProjectPreferenceORM).where(ProjectPreferenceORM.project_id == key)
        )
        await self._session.execute(
            sa_delete(SemanticSummaryORM).where(SemanticSummaryORM.project_id == key)
        )
        await self._session.execute(
            sa_delete(WritingPlanORM).where(WritingPlanORM.project_id == key)
        )

    async def hard_delete(self, project_id: uuid.UUID) -> bool:
        """物理删除项目（从数据库中永久移除）.

        先按 project_id 清理无 FK 子表族（#1371，见 ``_purge_string_pid_children``），
        再删 projects 行；其余 int+FK 子表由 DB 级 ON DELETE CASCADE 处理（#327）。

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        pid = require_uuid_pk(project_id)
        if pid is None:
            return False
        stmt = select(ProjectORM).where(ProjectORM.id == pid)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False

        await self._purge_string_pid_children(pid)
        await self._session.delete(orm)
        await self._session.commit()
        return True
