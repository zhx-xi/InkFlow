"""FastAPI 依赖注入 — 数据库 session 和 Service 获取."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.core.database import get_session
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.domain.services.project_service import ProjectService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库 session（FastAPI 依赖）."""
    async for session in get_session():
        yield session


def get_project_service(
    db: AsyncSession,
) -> ProjectService:
    """获取 ProjectService 实例（注入数据库 session）."""
    return ProjectService(db)


def get_chapter_service(
    db: AsyncSession,
) -> ChapterService:
    """获取 ChapterService 实例（注入数据库 session）."""
    return ChapterService(db)
