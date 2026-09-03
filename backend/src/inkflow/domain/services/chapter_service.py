"""章节业务服务 — 编排 Volume/Chapter 业务逻辑."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from inkflow.domain.models.chapter import (
    Chapter,
    ChapterStatus,
    ChapterUpdate,
    Volume,
    VolumeUpdate,
)
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.logging import log_structured


class VolumeNotEmptyError(Exception):
    """卷下存在章节且未指定级联/移动处理方式（#648 禁止静默解绑）。"""


class VolumeMoveError(Exception):
    """目标卷非法（不存在或等于当前卷）。"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_uuid(val: int | uuid.UUID) -> uuid.UUID:
    """将 int 或 UUID 统一转为 uuid.UUID."""
    if isinstance(val, int):
        return uuid.UUID(int=val)
    return val


def _to_int(val: int | uuid.UUID) -> int:
    """将 int 或 UUID 统一转为 int."""
    if isinstance(val, uuid.UUID):
        return val.int
    return val


class ChapterService:
    """章节业务服务."""

    def __init__(self, db_session) -> None:
        self._repo = SQLiteChapterRepository(db_session)

    # ---- Volume ----

    async def create_volume(
        self,
        project_id: int | uuid.UUID,
        title: str,
        order_index: float | None = None,
    ) -> Volume:
        pid = _to_uuid(project_id)
        if order_index is None:
            order_index = await self._repo.get_next_volume_order(pid.int)
        vol = Volume(
            id=uuid.uuid4(),
            project_id=pid,
            title=title,
            order_index=order_index,
        )
        return await self._repo.add_volume(vol)

    async def get_volume(self, volume_id: int | uuid.UUID) -> Volume | None:
        return await self._repo.get_volume(_to_int(volume_id))

    async def list_volumes(self, project_id: int | uuid.UUID) -> list[Volume]:
        return await self._repo.list_volumes(_to_int(project_id))

    async def update_volume(self, volume_id: int | uuid.UUID, dto: VolumeUpdate) -> Volume | None:
        vid = _to_int(volume_id)
        existing = await self._repo.get_volume(vid)
        if existing is None:
            return None
        updated = existing.model_copy(update=dto.model_dump(exclude_unset=True))
        return await self._repo.update_volume(updated)

    async def delete_volume(
        self,
        volume_id: int | uuid.UUID,
        *,
        delete_chapters: bool = False,
        move_to: int | uuid.UUID | None = None,
    ) -> bool:
        vid = _to_int(volume_id)
        if vid > 2**63 - 1:
            return False
        existing: Volume | None = await self._repo.get_volume(vid)
        if existing is None:
            return False
        count = await self._repo.count_chapters_by_volume(vid)
        if count > 0:
            if delete_chapters:
                for cid in await self._repo.list_chapter_ids_by_volume(vid):
                    await self._repo.delete_chapter(cid)
            elif move_to is not None:
                target = _to_int(move_to)
                if target == vid:
                    raise VolumeMoveError("目标卷不能是当前卷")
                if target > 2**63 - 1:
                    raise VolumeMoveError("目标卷不存在")
                target_vol: Volume | None = await self._repo.get_volume(target)
                if target_vol is None:
                    raise VolumeMoveError("目标卷不存在")
                await self._repo.move_chapters_to_volume(vid, target)
            else:
                raise VolumeNotEmptyError("卷下存在章节，请选择级联删除或移动到其他卷")
        return await self._repo.delete_volume(vid)

    # ---- Chapter ----

    async def create_chapter(
        self,
        project_id: int | uuid.UUID,
        title: str,
        volume_id: int | uuid.UUID | None = None,
        content: str = "",
        order_index: float | None = None,
    ) -> Chapter:
        pid = _to_uuid(project_id)
        vid = _to_uuid(volume_id) if volume_id is not None else None
        if order_index is None:
            order_index = await self._repo.get_next_chapter_order(pid.int, vid.int if vid else None)
        ch = Chapter(
            id=uuid.uuid4(),
            project_id=pid,
            volume_id=vid,
            title=title,
            content=content,
            status=ChapterStatus.DRAFT,
            order_index=order_index,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        created = await self._repo.add_chapter(ch)
        log_structured(
            level="INFO",
            caller_type="api",
            caller_name="chapter_service.create_chapter",
            event="create_chapter",
            message_key="log.event.create_chapter",
            message=f"创建章节：{title}",
            params={"title": title},
        )
        return created

    async def get_chapter(self, chapter_id: int | uuid.UUID) -> Chapter | None:
        return await self._repo.get_chapter(_to_int(chapter_id))

    async def list_chapters(
        self,
        project_id: int | uuid.UUID,
        volume_id: int | uuid.UUID | None = None,
        status: ChapterStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Chapter], int]:
        return await self._repo.list_chapters(
            _to_int(project_id),
            _to_int(volume_id) if volume_id is not None else None,
            status,
            offset,
            limit,
        )

    async def update_chapter(
        self, chapter_id: int | uuid.UUID, dto: ChapterUpdate
    ) -> Chapter | None:
        cid = _to_int(chapter_id)
        existing = await self._repo.get_chapter(cid)
        if existing is None:
            return None
        update_data = dto.model_dump(exclude_unset=True)
        updated = existing.model_copy(update=update_data)
        return await self._repo.update_chapter(updated)

    async def delete_chapter(self, chapter_id: int | uuid.UUID) -> bool:
        return await self._repo.delete_chapter(_to_int(chapter_id))

    async def move_chapter(
        self,
        chapter_id: int | uuid.UUID,
        target_volume_id: int | uuid.UUID | None,
    ) -> Chapter | None:
        return await self._repo.move_chapter(
            _to_int(chapter_id),
            _to_int(target_volume_id) if target_volume_id is not None else None,
        )

    async def get_project_word_count(self, project_id: int) -> int:
        return await self._repo.get_project_word_count(project_id)

    async def get_volume_word_count(self, volume_id: int) -> int:
        return await self._repo.get_volume_word_count(volume_id)
