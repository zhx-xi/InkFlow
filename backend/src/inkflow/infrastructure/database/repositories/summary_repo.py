"""SQLite 摘要仓储 — 实现 SummaryRepositoryProtocol 的全部方法."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.context import ChapterSummary
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.context import ChapterSummaryORM
from inkflow.infrastructure.database.repositories._id_guard import require_uuid_pk


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

    async def get(self, chapter_id: uuid.UUID) -> ChapterSummary | None:
        """按主键查询章节摘要。超 int64 范围视为不存在（SQLite 整数溢出防御）.

        #1134 批 4（#1291）：入参收窄为 ``uuid.UUID``（#1230 的 int 兼容面已退役）。
        """
        cid = require_uuid_pk(chapter_id)
        if cid is None:
            return None
        stmt = select(ChapterSummaryORM).where(ChapterSummaryORM.chapter_id == cid)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _summary_orm_to_domain(orm) if orm else None

    async def upsert(self, chapter_id: uuid.UUID, summary: str, model: str) -> ChapterSummary:
        """插入或更新摘要缓存（章节主键为领域 UUID，见 #1291）."""
        cid = require_uuid_pk(chapter_id)
        if cid is None:
            raise ValueError(f"ChapterSummary 章节主键超出 int64 范围：{chapter_id}")
        result = await self._session.execute(
            select(ChapterSummaryORM).where(ChapterSummaryORM.chapter_id == cid)
        )
        orm = result.scalar_one_or_none()
        now = _utcnow()
        if orm is None:
            orm = ChapterSummaryORM(chapter_id=cid, summary=summary, model=model)
            self._session.add(orm)
        else:
            orm.summary = summary
            orm.model = model
            orm.updated_at = now
        await self._session.commit()
        await self._session.refresh(orm)
        return _summary_orm_to_domain(orm)

    async def list_recent(self, project_id: uuid.UUID, limit: int = 10) -> list[ChapterSummary]:
        """按章节顺序倒序取项目内最近摘要（项目主键为领域 UUID，见 #1291）."""
        pid = require_uuid_pk(project_id)
        if pid is None:
            return []
        stmt = (
            select(ChapterSummaryORM)
            .join(ChapterORM, ChapterORM.id == ChapterSummaryORM.chapter_id)
            .where(ChapterORM.project_id == pid)
            .order_by(ChapterORM.order_index.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_summary_orm_to_domain(o) for o in result.scalars().all()]
