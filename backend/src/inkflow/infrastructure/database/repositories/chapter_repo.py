"""SQLite 章节仓储 — 实现 ChapterRepositoryProtocol 的全部方法."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.chapter import (
    Chapter,
    ChapterStatus,
    StatusHistoryEntry,
    Volume,
)
from inkflow.domain.services._word_count import count_words
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _volume_orm_to_domain(orm: VolumeORM) -> Volume:
    return Volume(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        title=orm.title,
        order_index=orm.order_index,
    )


def _chapter_orm_to_domain(orm: ChapterORM) -> Chapter:
    return Chapter(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        volume_id=uuid.UUID(int=orm.volume_id) if orm.volume_id else None,
        title=orm.title,
        content=orm.content,
        status=ChapterStatus(orm.status),
        word_count=orm.word_count,
        order_index=orm.order_index,
        status_history=[StatusHistoryEntry(**e) for e in (orm.status_history or [])],
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SQLiteChapterRepository:
    """SQLite 章节仓储实现."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Volume CRUD ----

    async def add_volume(self, volume: Volume) -> Volume:
        orm = VolumeORM(
            project_id=volume.project_id.int,
            title=volume.title,
            order_index=volume.order_index,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _volume_orm_to_domain(orm)

    async def get_volume(self, volume_id: int) -> Volume | None:
        stmt = select(VolumeORM).where(VolumeORM.id == volume_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _volume_orm_to_domain(orm) if orm else None

    async def list_volumes(self, project_id: int) -> list[Volume]:
        stmt = (
            select(VolumeORM)
            .where(VolumeORM.project_id == project_id)
            .order_by(VolumeORM.order_index.asc())
        )
        result = await self._session.execute(stmt)
        return [_volume_orm_to_domain(o) for o in result.scalars().all()]

    async def update_volume(self, volume: Volume) -> Volume:
        vol_id = volume.id.int
        await self._session.execute(
            sa_update(VolumeORM)
            .where(VolumeORM.id == vol_id)
            .values(title=volume.title, order_index=volume.order_index)
        )
        await self._session.commit()
        result = await self._session.execute(select(VolumeORM).where(VolumeORM.id == vol_id))
        return _volume_orm_to_domain(result.scalar_one())

    async def delete_volume(self, volume_id: int) -> bool:
        await self._session.execute(
            sa_update(ChapterORM)
            .where(ChapterORM.volume_id == volume_id)
            .values(volume_id=None, updated_at=_utcnow())
        )
        result = await self._session.execute(select(VolumeORM).where(VolumeORM.id == volume_id))
        vol = result.scalar_one_or_none()
        if vol is None:
            return False
        await self._session.delete(vol)
        await self._session.commit()
        return True

    async def get_next_volume_order(self, project_id: int) -> float:
        stmt = select(func.max(VolumeORM.order_index)).where(VolumeORM.project_id == project_id)
        result = await self._session.execute(stmt)
        max_order = result.scalar_one()
        return (max_order or 0.0) + 1.0

    # ---- Chapter CRUD ----

    async def add_chapter(self, chapter: Chapter) -> Chapter:
        wc = count_words(chapter.content)
        orm = ChapterORM(
            project_id=chapter.project_id.int,
            volume_id=chapter.volume_id.int if chapter.volume_id else None,
            title=chapter.title,
            content=chapter.content,
            status=chapter.status.value,
            word_count=wc,
            order_index=chapter.order_index,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _chapter_orm_to_domain(orm)

    async def get_chapter(self, chapter_id: int) -> Chapter | None:
        stmt = select(ChapterORM).where(ChapterORM.id == chapter_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _chapter_orm_to_domain(orm) if orm else None

    async def list_chapters(
        self,
        project_id: int,
        volume_id: int | None = None,
        status: ChapterStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Chapter], int]:
        base = select(ChapterORM).where(ChapterORM.project_id == project_id)
        if volume_id is not None:
            base = base.where(ChapterORM.volume_id == volume_id)
        if status is not None:
            base = base.where(ChapterORM.status == status.value)

        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        base = base.order_by(ChapterORM.order_index.asc()).offset(offset).limit(limit)
        result = await self._session.execute(base)
        chapters = [_chapter_orm_to_domain(o) for o in result.scalars().all()]
        return chapters, total

    async def update_chapter(self, chapter: Chapter) -> Chapter:
        ch_id = chapter.id.int

        old_result = await self._session.execute(select(ChapterORM).where(ChapterORM.id == ch_id))
        old_orm = old_result.scalar_one_or_none()
        if old_orm is None:
            raise ValueError(f"Chapter {ch_id} not found")

        history = list(old_orm.status_history or [])
        if chapter.status.value != old_orm.status:
            history.append(
                {
                    "from_status": old_orm.status,
                    "to_status": chapter.status.value,
                    "at": _utcnow().isoformat(),
                }
            )

        wc = count_words(chapter.content)

        await self._session.execute(
            sa_update(ChapterORM)
            .where(ChapterORM.id == ch_id)
            .values(
                title=chapter.title,
                content=chapter.content,
                status=chapter.status.value,
                word_count=wc,
                order_index=chapter.order_index,
                volume_id=(chapter.volume_id.int if chapter.volume_id else None),
                status_history=history,
                updated_at=_utcnow(),
            )
        )
        await self._session.commit()

        result = await self._session.execute(select(ChapterORM).where(ChapterORM.id == ch_id))
        return _chapter_orm_to_domain(result.scalar_one())

    async def delete_chapter(self, chapter_id: int) -> bool:
        result = await self._session.execute(select(ChapterORM).where(ChapterORM.id == chapter_id))
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def move_chapter(self, chapter_id: int, target_volume_id: int | None) -> Chapter | None:
        await self._session.execute(
            sa_update(ChapterORM)
            .where(ChapterORM.id == chapter_id)
            .values(volume_id=target_volume_id, updated_at=_utcnow())
        )
        await self._session.commit()
        result = await self._session.execute(select(ChapterORM).where(ChapterORM.id == chapter_id))
        orm = result.scalar_one_or_none()
        return _chapter_orm_to_domain(orm) if orm else None

    async def get_next_chapter_order(self, project_id: int, volume_id: int | None = None) -> float:
        base = select(func.max(ChapterORM.order_index)).where(ChapterORM.project_id == project_id)
        if volume_id is not None:
            base = base.where(ChapterORM.volume_id == volume_id)
        result = await self._session.execute(base)
        max_order = result.scalar_one()
        return (max_order or 0.0) + 1.0

    async def get_project_word_count(self, project_id: int) -> int:
        stmt = select(func.sum(ChapterORM.word_count)).where(ChapterORM.project_id == project_id)
        result = await self._session.execute(stmt)
        total = result.scalar_one()
        return total or 0

    async def get_volume_word_count(self, volume_id: int) -> int:
        stmt = select(func.sum(ChapterORM.word_count)).where(ChapterORM.volume_id == volume_id)
        result = await self._session.execute(stmt)
        total = result.scalar_one()
        return total or 0
