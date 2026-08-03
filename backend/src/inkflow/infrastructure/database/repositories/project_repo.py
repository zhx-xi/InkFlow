"""SQLite 项目仓储实现 — 基于 SQLAlchemy async session.

实现 ProjectRepositoryProtocol 的全部 7 个方法:
add, get, list_all, update, soft_delete, restore, hard_delete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.project import Genre, Project, ProjectConfig
from inkflow.infrastructure.database.models.project import ProjectORM


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
        genre=Genre(orm.genre) if isinstance(orm.genre, str) else orm.genre,
        language=orm.language,
        target_words=orm.target_words,
        config=ProjectConfig(**orm.config) if orm.config else ProjectConfig(),
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


def _get_genre_str(genre: Any) -> str:
    """Extract string value from Genre enum or str."""
    if isinstance(genre, Genre):
        return genre.value
    return str(genre) if genre else "其他"


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
            genre=_get_genre_str(project.genre),
            language=project.language,
            target_words=project.target_words,
            config=_get_config_dict(project.config),
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, project_id: int) -> Project | None:
        """按 ID 查询项目（排除软删除记录）."""
        stmt = select(ProjectORM).where(
            ProjectORM.id == project_id,
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
            "genre": _get_genre_str(project.genre),
            "language": project.language,
            "target_words": project.target_words,
            "config": _get_config_dict(project.config),
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

    async def soft_delete(self, project_id: int) -> bool:
        """软删除项目（标记 is_deleted=True）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        stmt = (
            sa_update(ProjectORM)
            .where(ProjectORM.id == project_id, ~ProjectORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def restore(self, project_id: int) -> Project | None:
        """恢复软删除的项目（设置 is_deleted=False）.

        Returns:
            恢复后的 Project，若记录不存在则返回 None.
        """
        stmt = (
            sa_update(ProjectORM)
            .where(ProjectORM.id == project_id, ProjectORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()

        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
            return None

        return await self.get(project_id)

    async def hard_delete(self, project_id: int) -> bool:
        """物理删除项目（从数据库中永久移除）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        stmt = select(ProjectORM).where(ProjectORM.id == project_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False

        await self._session.delete(orm)
        await self._session.commit()
        return True
