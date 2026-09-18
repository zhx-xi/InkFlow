"""SQLite 章节仓储 — 实现 ChapterRepositoryProtocol 的全部方法."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
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
from inkflow.infrastructure.database.models.agent_run import AgentRunORM, DraftORM
from inkflow.infrastructure.database.models.audit_log import AuditLogORM
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.context import ChapterSummaryORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.repositories._id_guard import require_uuid_pk


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
        writing_requirements=orm.writing_requirements,
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

    async def get_volume(self, volume_id: uuid.UUID) -> Volume | None:
        """按主键查询卷。超 int64 范围视为不存在（SQLite 整数溢出防御）.

        #1134 批 4（#1291）：入参收窄为 ``uuid.UUID``。
        """
        vid = require_uuid_pk(volume_id)
        if vid is None:
            return None
        stmt = select(VolumeORM).where(VolumeORM.id == vid)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _volume_orm_to_domain(orm) if orm else None

    async def list_volumes(self, project_id: uuid.UUID) -> list[Volume]:
        pid = require_uuid_pk(project_id)
        if pid is None:
            return []
        stmt = (
            select(VolumeORM)
            .where(VolumeORM.project_id == pid)
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

    async def delete_volume(self, volume_id: uuid.UUID) -> bool:
        vid = require_uuid_pk(volume_id)
        if vid is None:
            return False
        await self._session.execute(
            sa_update(OutlineORM).where(OutlineORM.volume_id == vid).values(volume_id=None)
        )
        await self._session.execute(
            sa_update(ChapterORM)
            .where(ChapterORM.volume_id == vid)
            .values(volume_id=None, updated_at=_utcnow())
        )
        result = await self._session.execute(select(VolumeORM).where(VolumeORM.id == vid))
        vol = result.scalar_one_or_none()
        if vol is None:
            return False
        await self._session.delete(vol)
        await self._session.commit()
        return True

    async def count_chapters_by_volume(self, volume_id: uuid.UUID) -> int:
        vid = require_uuid_pk(volume_id)
        if vid is None:
            return 0
        stmt = select(func.count()).select_from(ChapterORM).where(ChapterORM.volume_id == vid)
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def list_chapter_ids_by_volume(self, volume_id: uuid.UUID) -> list[uuid.UUID]:
        """返回卷内章节主键（领域 UUID，#1291 收窄）。"""
        vid = require_uuid_pk(volume_id)
        if vid is None:
            return []
        stmt = select(ChapterORM.id).where(ChapterORM.volume_id == vid)
        result = await self._session.execute(stmt)
        return [uuid.UUID(int=row) for row in result.scalars().all()]

    async def move_chapters_to_volume(
        self, source_volume_id: uuid.UUID, target_volume_id: uuid.UUID
    ) -> int:
        src = require_uuid_pk(source_volume_id)
        tgt = require_uuid_pk(target_volume_id)
        if src is None or tgt is None:
            return 0
        result = await self._session.execute(
            sa_update(ChapterORM)
            .where(ChapterORM.volume_id == src)
            .values(volume_id=tgt, updated_at=_utcnow())
        )
        await self._session.commit()
        count: int = result.rowcount if result.rowcount is not None else 0  # type: ignore[attr-defined]  # SQLAlchemy execute() 静态类型为 Result，rowcount 仅在 CursorResult 上声明，运行时实际可用
        return count

    async def get_next_volume_order(self, project_id: uuid.UUID) -> float:
        pid = require_uuid_pk(project_id)
        if pid is None:
            return 1.0
        stmt = select(func.max(VolumeORM.order_index)).where(VolumeORM.project_id == pid)
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
            writing_requirements=chapter.writing_requirements,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _chapter_orm_to_domain(orm)

    async def get_chapter(self, chapter_id: uuid.UUID) -> Chapter | None:
        """按主键查询章节。超 int64 范围视为不存在（SQLite 整数溢出防御）.

        #1134 批 4（#1291）：入参收窄为 ``uuid.UUID``。
        """
        cid = require_uuid_pk(chapter_id)
        if cid is None:
            return None
        stmt = select(ChapterORM).where(ChapterORM.id == cid)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _chapter_orm_to_domain(orm) if orm else None

    async def list_chapters(
        self,
        project_id: uuid.UUID,
        volume_id: uuid.UUID | None = None,
        status: ChapterStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Chapter], int]:
        # #1162: 嵌套 FK 过滤值超 int64 → 不可能命中任何行 → 空结果
        # （128 位 int 绑定会抛 OverflowError → 500，须与 repo.get 同口径）
        # #1291：入参收窄为 uuid.UUID，归一统一经 require_uuid_pk。
        pid = require_uuid_pk(project_id)
        if pid is None:
            return [], 0
        vid = require_uuid_pk(volume_id)
        if volume_id is not None and vid is None:
            return [], 0
        base = select(ChapterORM).where(ChapterORM.project_id == pid)
        if vid is not None:
            base = base.where(ChapterORM.volume_id == vid)
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
                writing_requirements=chapter.writing_requirements,
                volume_id=(chapter.volume_id.int if chapter.volume_id else None),
                status_history=history,
                updated_at=_utcnow(),
            )
        )
        await self._session.commit()

        result = await self._session.execute(select(ChapterORM).where(ChapterORM.id == ch_id))
        return _chapter_orm_to_domain(result.scalar_one())

    async def delete_chapter(self, chapter_id: uuid.UUID) -> bool:
        """物理删除章节（先显式清理 6 处引用，foreign_keys=OFF 下不依赖 FK）.

        F43 P5（spec §2.10/§5.18）: 生产连接未开 foreign_keys=ON，显式
        引用清理与主删除同一事务——
        ① outlines.chapter_id / timeline_events.source_chapter_id → NULL
        ② audit_logs / chapter_summaries 级联删除
        ③ agent_runs / drafts chapter_id（String(36) uuid 字符串）→ NULL
        """
        cid = require_uuid_pk(chapter_id)
        if cid is None:
            return False
        result = await self._session.execute(select(ChapterORM).where(ChapterORM.id == cid))
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        ch_uuid_str = str(chapter_id)
        await self._session.execute(
            sa_update(OutlineORM).where(OutlineORM.chapter_id == cid).values(chapter_id=None)
        )
        await self._session.execute(
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.source_chapter_id == cid)
            .values(source_chapter_id=None)
        )
        await self._session.execute(sa_delete(AuditLogORM).where(AuditLogORM.chapter_id == cid))
        await self._session.execute(
            sa_delete(ChapterSummaryORM).where(ChapterSummaryORM.chapter_id == cid)
        )
        await self._session.execute(
            sa_update(AgentRunORM)
            .where(AgentRunORM.chapter_id == ch_uuid_str)
            .values(chapter_id=None)
        )
        await self._session.execute(
            sa_update(DraftORM).where(DraftORM.chapter_id == ch_uuid_str).values(chapter_id=None)
        )
        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def move_chapter(
        self, chapter_id: uuid.UUID, target_volume_id: uuid.UUID | None
    ) -> Chapter | None:
        cid = require_uuid_pk(chapter_id)
        if cid is None:
            return None
        tgt = require_uuid_pk(target_volume_id)
        if target_volume_id is not None and tgt is None:
            return None
        await self._session.execute(
            sa_update(ChapterORM)
            .where(ChapterORM.id == cid)
            .values(volume_id=tgt, updated_at=_utcnow())
        )
        await self._session.commit()
        result = await self._session.execute(select(ChapterORM).where(ChapterORM.id == cid))
        orm = result.scalar_one_or_none()
        return _chapter_orm_to_domain(orm) if orm else None

    async def get_next_chapter_order(
        self, project_id: uuid.UUID, volume_id: uuid.UUID | None = None
    ) -> float:
        pid = require_uuid_pk(project_id)
        if pid is None:
            return 1.0
        vid = require_uuid_pk(volume_id)
        if volume_id is not None and vid is None:
            return 1.0
        base = select(func.max(ChapterORM.order_index)).where(ChapterORM.project_id == pid)
        if volume_id is not None:
            base = base.where(ChapterORM.volume_id == vid)
        result = await self._session.execute(base)
        max_order = result.scalar_one()
        return (max_order or 0.0) + 1.0

    async def get_project_word_count(self, project_id: uuid.UUID) -> int:
        pid = require_uuid_pk(project_id)
        if pid is None:
            return 0
        stmt = select(func.sum(ChapterORM.word_count)).where(ChapterORM.project_id == pid)
        result = await self._session.execute(stmt)
        total = result.scalar_one()
        return total or 0

    async def get_volume_word_count(self, volume_id: uuid.UUID) -> int:
        vid = require_uuid_pk(volume_id)
        if vid is None:
            return 0
        stmt = select(func.sum(ChapterORM.word_count)).where(ChapterORM.volume_id == vid)
        result = await self._session.execute(stmt)
        total = result.scalar_one()
        return total or 0
