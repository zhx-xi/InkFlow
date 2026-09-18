"""章节业务服务 — 编排 Volume/Chapter 业务逻辑."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from inkflow.domain.models.chapter import (
    Chapter,
    ChapterStatus,
    ChapterUpdate,
    Volume,
    VolumeUpdate,
    chapter_content_needs_normalize,
    normalize_chapter_content,
    normalize_chapter_title,
)
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.project import Project
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.services._data_change import publish_change
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

logger = logging.getLogger(__name__)


class VolumeNotEmptyError(Exception):
    """卷下存在章节且未指定级联/移动处理方式（#648 禁止静默解绑）。"""


class VolumeMoveError(Exception):
    """目标卷非法（不存在或等于当前卷）。"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_uuid(val: int | uuid.UUID) -> uuid.UUID:
    """将 int 或 UUID 统一转为 uuid.UUID（#1291：仅用于兼容外部 int 入参，非仓库层中转）."""
    if isinstance(val, int):
        return uuid.UUID(int=val)
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
        """创建卷（#1138: 落库前校验项目存在，防孤儿行）.

        Raises:
            ProjectNotFoundError: 项目不存在（router 转 404「项目不存在」）.
        """
        pid = _to_uuid(project_id)
        # #1138: 落库前先校验项目存在（对齐 foreshadowing_service._ensure_project）
        if await self._project_repo.get(pid) is None:
            raise ProjectNotFoundError()
        if order_index is None:
            order_index = await self._repo.get_next_volume_order(pid)
        vol = Volume(
            id=uuid.uuid4(),
            project_id=pid,
            title=title,
            order_index=order_index,
        )
        created: Volume = await self._repo.add_volume(vol)
        await publish_change("volume", "create", created.id, created.project_id)
        return created

    async def get_volume(self, volume_id: int | uuid.UUID) -> Volume | None:
        return await self._repo.get_volume(_to_uuid(volume_id))

    async def list_volumes(self, project_id: int | uuid.UUID) -> list[Volume]:
        """查询项目内全部卷（order_index ASC）.

        Raises:
            ProjectNotFoundError: 项目不存在（#1151：上层先判父资源存在，
                router 转 404「项目不存在」）.
        """
        pid = _to_uuid(project_id)
        # #1151: 先判父项目存在——缺失 → 404；顺带防 128 位 int 走到过滤 SQL 绑定
        # 抛 OverflowError → 500（project_repo.get 自带 int64 守卫，#1139 同族口径）
        if await self._project_repo.get(pid) is None:
            raise ProjectNotFoundError()
        return await self._repo.list_volumes(pid)

    async def update_volume(self, volume_id: int | uuid.UUID, dto: VolumeUpdate) -> Volume | None:
        vid = _to_uuid(volume_id)
        existing = await self._repo.get_volume(vid)
        if existing is None:
            return None
        updated = existing.model_copy(update=dto.model_dump(exclude_unset=True))
        saved: Volume | None = await self._repo.update_volume(updated)
        if saved is not None:
            await publish_change("volume", "update", saved.id, existing.project_id)
        return saved

    async def delete_volume(
        self,
        volume_id: int | uuid.UUID,
        *,
        delete_chapters: bool = False,
        move_to: int | uuid.UUID | None = None,
    ) -> bool:
        vid = _to_uuid(volume_id)
        existing: Volume | None = await self._repo.get_volume(vid)
        if existing is None:
            return False
        count = await self._repo.count_chapters_by_volume(vid)
        if count > 0:
            if delete_chapters:
                for cid in await self._repo.list_chapter_ids_by_volume(vid):
                    await self._repo.delete_chapter(cid)
            elif move_to is not None:
                target = _to_uuid(move_to)
                if target == vid:
                    raise VolumeMoveError("目标卷不能是当前卷")
                target_vol: Volume | None = await self._repo.get_volume(target)
                if target_vol is None:
                    raise VolumeMoveError("目标卷不存在")
                await self._repo.move_chapters_to_volume(vid, target)
            else:
                raise VolumeNotEmptyError("卷下存在章节，请选择级联删除或移动到其他卷")
        deleted: bool = await self._repo.delete_volume(vid)
        if deleted:
            await publish_change("volume", "delete", existing.id, existing.project_id)
        return deleted

    # ---- Chapter ----

    async def create_chapter(
        self,
        project_id: int | uuid.UUID,
        title: str,
        volume_id: int | uuid.UUID | None = None,
        content: str = "",
        order_index: float | None = None,
    ) -> Chapter:
        """创建章节.

        Raises:
            ProjectNotFoundError: 项目不存在（router 转 404「项目不存在」，#1149）.
        """
        pid = _to_uuid(project_id)
        vid = _to_uuid(volume_id) if volume_id is not None else None
        # #1149: 落库前先校验项目存在（对齐 create_volume；防 pid.int 超 int64 绑 SQLite
        # 抛 OverflowError → 500，并防孤儿行）
        if await self._project_repo.get(pid) is None:
            raise ProjectNotFoundError()
        if order_index is None:
            order_index = await self._repo.get_next_chapter_order(pid, vid)
        # #1095：落库前归一（重复标题 / markdown / 段首缩进）；干净正文原样落库。
        if chapter_content_needs_normalize(content, title):
            content = normalize_chapter_content(content, title)
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
        await publish_change("chapter", "create", created.id, created.project_id)
        return created

    async def get_chapter(self, chapter_id: int | uuid.UUID) -> Chapter | None:
        return await self._repo.get_chapter(_to_uuid(chapter_id))

    async def list_chapters(
        self,
        project_id: int | uuid.UUID,
        volume_id: int | uuid.UUID | None = None,
        status: ChapterStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Chapter], int]:
        """分页查询项目内章节列表（spec §6.3）.

        Raises:
            ProjectNotFoundError: 项目不存在（#1151，router 转 404）.
        """
        pid = _to_uuid(project_id)
        # #1151: 先判父项目存在——缺失 → 404；顺带防 128 位 int 走到过滤 SQL 绑定
        # 抛 OverflowError → 500（project_repo.get 自带 int64 守卫，#1139 同族口径）
        if await self._project_repo.get(pid) is None:
            raise ProjectNotFoundError()
        return await self._repo.list_chapters(
            pid,
            _to_uuid(volume_id) if volume_id is not None else None,
            status,
            offset,
            limit,
        )

    async def update_chapter(
        self, chapter_id: int | uuid.UUID, dto: ChapterUpdate
    ) -> Chapter | None:
        cid = _to_uuid(chapter_id)
        existing = await self._repo.get_chapter(cid)
        if existing is None:
            return None
        update_data = dto.model_dump(exclude_unset=True)
        # #1166: 改挂卷（volume_id 出现且非 None）必须先校验目标卷存在——
        # 缺失（含 128 位溢出）→ VolumeMoveError（router 422），绝不盲写孤儿 volume_id；
        # volume_id=None（出卷）保持放行（显式 NULL 合并语义不变）
        if update_data.get("volume_id") is not None:
            await self._ensure_target_volume(update_data["volume_id"])
        updated = existing.model_copy(update=update_data)
        # #1095：落库前按「合并后的最终 title」归一正文（单一真相面 = service 层，
        # Repository 层不得重复归一，避免双层归一双重缩进）。
        if chapter_content_needs_normalize(updated.content, updated.title):
            updated = updated.model_copy(
                update={"content": normalize_chapter_content(updated.content, updated.title)}
            )
        saved = await self._repo.update_chapter(updated)
        await self._auto_link_outline(saved, existing)
        await publish_change("chapter", "update", saved.id, saved.project_id)
        return saved

    async def _auto_link_outline(self, saved: Chapter, before: Chapter | None = None) -> None:
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
        deleted: bool = await self._repo.delete_chapter(_to_uuid(chapter_id))
        if deleted:
            logger.warning(
                "chapter 删除事件缺 project_id（delete_chapter 未加载实体，spec §15.3.2）: id=%s",
                chapter_id,
            )
            await publish_change("chapter", "delete", chapter_id, None)
        return deleted

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
        if fmt not in ("arabic", "chinese"):
            raise ValueError(f"不支持的章节标题格式: {fmt}")
        project: Project | None = await self._project_repo.get(pid)
        if project is None:
            return None

        chapters_replaced = 0
        offset = 0
        while True:
            chapter_page: tuple[list[Chapter], int] = await self._repo.list_chapters(
                pid, None, None, offset, 50
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
                pid, offset=offset, limit=50
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
            existing_outline = await self._outline_repo.get_by_name(pid, normalized)
            if existing_outline is not None and existing_outline.id != outline.id:
                # 归一后与既有活动大纲重名（uq_outlines_active_name）→ 跳过防 IntegrityError
                continue
            updated_outline = outline.model_copy(update={"name": normalized})
            await self._outline_repo.update(updated_outline)
            outlines_replaced += 1

        config = project.config.model_copy(update={"chapter_title_format": fmt})
        updated_project = project.model_copy(update={"config": config})
        await self._project_repo.update(updated_project)
        if chapters_replaced or outlines_replaced:
            await publish_change("chapter", "update", str(pid), pid)
            await publish_change("outline", "update", str(pid), pid)
        return {"chapters_replaced": chapters_replaced, "outlines_replaced": outlines_replaced}

    async def move_chapter(
        self,
        chapter_id: int | uuid.UUID,
        target_volume_id: int | uuid.UUID | None,
    ) -> Chapter | None:
        """移动章节到目标卷（对齐 delete_volume 的 move_to 先例，#1162/#1166）.

        Raises:
            VolumeMoveError: 目标卷不存在（溢出 int64 或查无此卷）→ router 转 422，
                且不落库（#1166 病症③：repo 层只能挡 500，盲写孤儿必须 service 挡）。
        """
        # #1166: 收敛到 _ensure_target_volume（与 update_chapter 改挂卷共用同一校验）
        if target_volume_id is not None:
            await self._ensure_target_volume(target_volume_id)
        moved: Chapter | None = await self._repo.move_chapter(
            _to_uuid(chapter_id),
            _to_uuid(target_volume_id) if target_volume_id is not None else None,
        )
        if moved is not None:
            await publish_change("chapter", "update", moved.id, moved.project_id)
        return moved

    async def _ensure_target_volume(self, volume_id: int | uuid.UUID) -> None:
        """改挂目标卷必须存在（#1166；同 delete_volume(move_to=) 口径）.

        Raises:
            VolumeMoveError: 目标卷不存在（router 转 422）.
        """
        target = _to_uuid(volume_id)
        target_vol: Volume | None = await self._repo.get_volume(target)
        if target_vol is None:
            raise VolumeMoveError("目标卷不存在")

    async def get_project_word_count(self, project_id: int | uuid.UUID) -> int:
        return await self._repo.get_project_word_count(_to_uuid(project_id))

    async def get_volume_word_count(self, volume_id: int | uuid.UUID) -> int:
        return await self._repo.get_volume_word_count(_to_uuid(volume_id))
