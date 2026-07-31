"""SQLite 摘要仓储 — 实现 SummaryRepositoryProtocol 的全部方法."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.context import ChapterSummary
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.context import ChapterSummaryORM


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _summary_orm_to_domain(orm: ChapterSummaryORM) -> ChapterSummary:
    """ORM → 领域模型：int 主键背书为 uuid.UUID(int=...)，时间戳转 ISO 字符串."""
    return ChapterSummary(
        id=uuid.UUID(int=orm.id),
        chapter_id=uuid.UUID(int=orm.chapter_id),
        summary=orm.summary,
        model=orm.model,
        created_at=orm.created_at.isoformat(),
        updated_at=orm.updated_at.isoformat(),
    )


class SQLiteSummaryRepository:
    """SQLite 摘要仓储实现."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, chapter_id: int) -> ChapterSummary | None:
        stmt = select(ChapterSummaryORM).where(ChapterSummaryORM.chapter_id == chapter_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _summary_orm_to_domain(orm) if orm else None

    async def upsert(self, chapter_id: int, summary: str, model: str) -> ChapterSummary:
        result = await self._session.execute(
            select(ChapterSummaryORM).where(ChapterSummaryORM.chapter_id == chapter_id)
        )
        orm = result.scalar_one_or_none()
        now = _utcnow()
        if orm is None:
            orm = ChapterSummaryORM(chapter_id=chapter_id, summary=summary, model=model)
            self._session.add(orm)
        else:
            orm.summary = summary
            orm.model = model
            orm.updated_at = now
        await self._session.commit()
        await self._session.refresh(orm)
        return _summary_orm_to_domain(orm)

    async def list_recent(self, project_id: int, limit: int = 10) -> list[ChapterSummary]:
        stmt = (
            select(ChapterSummaryORM)
            .join(ChapterORM, ChapterORM.id == ChapterSummaryORM.chapter_id)
            .where(ChapterORM.project_id == project_id)
            .order_by(ChapterORM.order_index.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_summary_orm_to_domain(o) for o in result.scalars().all()]
