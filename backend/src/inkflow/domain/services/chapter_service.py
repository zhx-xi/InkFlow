"""章节业务服务 — 编排 Volume/Chapter 业务逻辑."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from inkflow.domain.models.chapter import (
    Chapter,
    ChapterStatus,
    ChapterUpdate,
    Volume,
    VolumeUpdate,
    normalize_chapter_title,
)
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.project import Project
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.outline_repo import (
    SQLiteOutlineRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
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


# #1001 正文落盘自动关联器：(project_id, chapter_id, chapter_title) -> None
OutlineAutolinker = Callable[[uuid.UUID, uuid.UUID, str], Awaitable[object]]


class ChapterService:
    """章节业务服务."""

    def __init__(
        self,
        db_session,
        outline_repo=None,
        project_repo=None,
        outline_autolinker: OutlineAutolinker | None = None,
    ) -> None:
        self._repo = SQLiteChapterRepository(db_session)
        self._outline_repo = outline_repo or SQLiteOutlineRepository(db_session)
        self._project_repo = project_repo or SQLiteProjectRepository(db_session)
        self._outline_autolinker = outline_autolinker

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
        await self._auto_link_outline(created)
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
        if cid > 2**63 - 1:
            return None  # 随机 uuid4 溢出 SQLite INTEGER：必然不存在 → 404 语义
        existing = await self._repo.get_chapter(cid)
        if existing is None:
            return None
        update_data = dto.model_dump(exclude_unset=True)
        updated = existing.model_copy(update=update_data)
        saved = await self._repo.update_chapter(updated)
        await self._auto_link_outline(saved, existing)
        return saved

    async def _auto_link_outline(
        self, saved: Chapter, before: Chapter | None = None
    ) -> None:
        """#1001：正文首次非空白落盘 → 触发章级大纲自动关联（弱依赖）.

        触发条件：落库后正文非空白，且落库前无正文（``before=None`` 视为创建）。
        未注入关联器 → 空操作；关联异常一律吞掉（不得影响正文落盘，镜像
        ``make_outline_bindder`` / ``_volume_lookup`` 的永不抛错语义）。
        """
        if self._outline_autolinker is None:
            return
        if not (saved.content or "").strip():
            return
        if before is not None and (before.content or "").strip():
            return  # 非首次落盘（已有正文）→ 不重触发
        try:
            await self._outline_autolinker(saved.project_id, saved.id, saved.title)
        except Exception:  # 弱依赖：自动关联失败不得影响正文落盘
            return

    async def delete_chapter(self, chapter_id: int | uuid.UUID) -> bool:
        return await self._repo.delete_chapter(_to_int(chapter_id))

    async def normalize_all_titles(
        self, project_id: int | uuid.UUID, fmt: str
    ) -> dict[str, int] | None:
        """全书章节/章级大纲标题批量归一（#999 契约 §4）.

        流程：项目校验（不存在 → None，router 转 404）→ 章实体分页取快照
        归一（变化才 update 计数）→ chapter 级大纲同步归一（归一后撞
        uq_outlines_active_name 活动大纲重名 → 跳过不计数）→ 最后把
        project.config.chapter_title_format 持久化为 fmt。

        Args:
            project_id: 项目主键（int 或 UUID）.
            fmt: 目标序号格式（arabic / chinese）.

        Returns:
            项目不存在返回 None；否则 {"chapters_replaced": int,
            "outlines_replaced": int}（幂等：第二次同 fmt 调用两计数全 0）.
        """
        pid = _to_uuid(project_id)
        pid_int = pid.int
        if fmt not in ("arabic", "chinese"):
            raise ValueError(f"不支持的章节标题格式: {fmt}")
        project: Project | None = await self._project_repo.get(pid_int)
        if project is None:
            return None

        chapters_replaced = 0
        offset = 0
        while True:
            chapter_page: tuple[list[Chapter], int] = await self._repo.list_chapters(
                pid_int, None, None, offset, 50
            )
            chapters, chapter_total = chapter_page
            for ch in chapters:
                normalized = normalize_chapter_title(ch.title, fmt)
                if normalized == ch.title:
                    continue
                updated_chapter = ch.model_copy(update={"title": normalized})
                await self._repo.update_chapter(updated_chapter)
                chapters_replaced += 1
            offset += len(chapters)
            if offset >= chapter_total or not chapters:
                break

        outlines_replaced = 0
        outline_snapshot: list[Outline] = []
        offset = 0
        while True:
            outline_page: tuple[list[Outline], int] = await self._outline_repo.list(
                pid_int, offset=offset, limit=50
            )
            outline_items, outline_total = outline_page
            outline_snapshot.extend(outline_items)
            offset += len(outline_items)
            if offset >= outline_total or not outline_items:
                break
        for outline in outline_snapshot:
            if outline.level != "chapter":
                continue
            name: str = outline.name
            normalized = normalize_chapter_title(name, fmt)
            if normalized == name:
                continue
            existing_outline = await self._outline_repo.get_by_name(pid_int, normalized)
            if existing_outline is not None and existing_outline.id != outline.id:
                # 归一后与既有活动大纲重名（uq_outlines_active_name）→ 跳过防 IntegrityError
                continue
            updated_outline = outline.model_copy(update={"name": normalized})
            await self._outline_repo.update(updated_outline)
            outlines_replaced += 1

        config = project.config.model_copy(update={"chapter_title_format": fmt})
        updated_project = project.model_copy(update={"config": config})
        await self._project_repo.update(updated_project)
        return {"chapters_replaced": chapters_replaced, "outlines_replaced": outlines_replaced}

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
