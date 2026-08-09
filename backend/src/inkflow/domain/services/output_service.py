"""F21 导出服务 — 只读聚合编排（spec §5.1 ①-④）.

ExportService 是 F21 的编排核心: 构造注入 F1/F2/F9/F10/F11/F12/F13 各仓储
Protocol（零跨模块 MODIFY，全部走既有只读方法，§8.2），export 按
spec §5.1 步骤 ①-④ 执行:

① 项目校验（ProjectRepositoryProtocol.get → None → ProjectNotFoundError 404）
② 正文聚合 + ③ 设定聚合（并行拉取，§5.1 要点 2）:
   正文: list_volumes 拉卷骨架 + list_chapters 循环分页拉全（limit=50 绝不
   静默丢章，M1 兜底）→ 软删章防御性过滤（getattr）→ 内存按 volume_id
   分组（None 归「未分组」卷，排所有命名卷之后）→ 卷 order_index ASC、
   章（卷内）order_index ASC, created_at ASC
   设定（include_settings=True）: 5 类 repo 经 asyncio.gather 并行拉取，
   组装顺序固定 character → world → outline → timeline → foreshadowing
   （§5.1 ③/§6.3 摘要拼接）; False（默认）→ settings=[] 且五个设定 repo
   方法均不调用（条件依赖性能契约）
④ 组装 BookDocument（统一中间表示，§2.2）

只依赖 domain/ports/ 与 domain/models/（Protocol 与领域模型），不依赖任何
infrastructure 实现——domain/ 零框架 import 门禁天然满足（ADR-002/015）。

依据: specs/f21-export-service/spec.md §2.2/§5.1/§5.2/§6.1/§6.3/§7 E1-E2/§8.2。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from inkflow.domain.models.chapter import Chapter, Volume
from inkflow.domain.models.character import Character
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.output import (
    BookChapter,
    BookDocument,
    BookMeta,
    BookSetting,
    BookVolume,
)
from inkflow.domain.models.project import Genre, Project
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol

_UNGROUPED_TITLE = "未分组"
"""未分组卷标题常量（spec §6.1: volume_id IS NULL 的章归「未分组」卷）。"""

_PAGE_SIZE = 50
"""循环分页页大小（各 list 方法默认 limit=50，聚合必须拉全，§5.2）。"""


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1/F15 `_to_int_id` 模式）.

    Args:
        value: 领域 UUID 或已有 int 主键.

    Returns:
        仓储层 int 主键（UUID 取其 int 表示）.
    """
    if isinstance(value, uuid.UUID):
        return value.int
    return value


class ExportService:
    """导出聚合服务（spec §5）— 只读聚合 7 模块档案为 BookDocument.

    依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:

    Args:
        project_repo: F1 项目仓储——get 项目校验 + meta（§5.1 步骤 ①）.
        chapter_repo: F2 章节仓储——卷骨架 + 章节全量（步骤 ②）.
        character_repo: F9 角色仓储——角色附录（include_settings=True 时）.
        world_repo: F10 世界观仓储——世界观附录.
        outline_repo: F11 大纲仓储——大纲/情节点附录.
        timeline_repo: F12 时间线仓储——事件附录.
        foreshadowing_repo: F13 伏笔仓储——伏笔附录.
    """

    def __init__(
        self,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        outline_repo: OutlineRepositoryProtocol,
        timeline_repo: TimelineRepositoryProtocol,
        foreshadowing_repo: ForeshadowingRepositoryProtocol,
    ) -> None:
        self._project_repo = project_repo
        self._chapter_repo = chapter_repo
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._outline_repo = outline_repo
        self._timeline_repo = timeline_repo
        self._foreshadowing_repo = foreshadowing_repo

    # ── 服务编排（spec §5.1 步骤 ①-④）────────────────────────────

    async def export(
        self, project_id: int | uuid.UUID, include_settings: bool = False
    ) -> BookDocument:
        """导出聚合编排 — 项目 → BookDocument（统一中间表示）.

        流程: 项目校验 → 正文 + 设定并行聚合（asyncio.gather，§5.1 要点 2；
        分页拉全 + 软删过滤 + 内存分组；include_settings=False 不调用设定
        repo）→ 组装 BookDocument。
        只读幂等：同一项目同一参数两次导出 BookDocument 逐字段相等
        （§5.4 确定性；updated_at 仅入 meta 展示）。

        Args:
            project_id: 项目领域 UUID 或 int 主键.
            include_settings: 是否含设定档案附录（Q3=C 拍板默认不含）.

        Returns:
            BookDocument 统一中间表示（volumes/settings 均可能为空列表）.

        Raises:
            ProjectNotFoundError: 项目不存在（404 语义，§3.3）.
            各仓储读取异常: 透传（router 转 500，§7 E9 原子快照）.
        """
        # ① 项目校验（服务层统一校验一次，404）
        pid_int = _to_int_id(project_id)
        project = await self._project_repo.get(pid_int)
        if project is None:
            raise ProjectNotFoundError()

        # ② 正文聚合 + ③ 设定聚合（并行，§5.1 要点 2: 各数据源相互独立）
        volumes_coro = self._chapter_repo.list_volumes(pid_int)
        chapters_coro = self._load_all(self._chapter_repo.list_chapters, pid_int)
        settings: list[BookSetting] = []
        if include_settings:
            volumes, chapters, settings = await asyncio.gather(
                volumes_coro,
                chapters_coro,
                self._aggregate_settings(pid_int),
            )
        else:
            # 条件依赖: False → 设定 repo 零调用（不创建 _aggregate_settings 协程）
            volumes, chapters = await asyncio.gather(volumes_coro, chapters_coro)

        # 软删章防御性过滤 + 内存分组（§5.2/§6.1）
        chapters = [ch for ch in chapters if not getattr(ch, "is_deleted", False)]
        book_volumes = self._assemble_volumes(volumes, chapters)

        # ④ 组装 BookDocument（§2.2）
        return BookDocument(
            meta=self._assemble_meta(project),
            volumes=book_volumes,
            settings=settings,
        )

    # ── 全量读取（spec §5.2: 循环分页拉全，M1 兜底）──────────────

    async def _load_all(
        self,
        repo_list: Callable[..., Awaitable[tuple[list[Any], int]]],
        pid_int: int,
    ) -> list[Any]:
        """分页循环拉取全量档案（list(limit=50) 循环直到累计 ≥ total）.

        Args:
            repo_list: 各模块仓储的分页 list 方法（首参 project_id int，
                支持 offset/limit 关键字）.
            pid_int: 项目 int 主键.

        Returns:
            全量档案列表（分页合并，读取顺序即各仓储返回顺序）.
        """
        items: list[Any] = []
        offset = 0
        while True:
            page, total = await repo_list(pid_int, offset=offset, limit=_PAGE_SIZE)
            items.extend(page)
            offset += _PAGE_SIZE
            if len(items) >= total:
                break
        return items

    # ── 正文聚合（spec §5.1 ②/§6.1）──────────────────────────────

    def _assemble_volumes(self, volumes: list[Volume], chapters: list[Chapter]) -> list[BookVolume]:
        """卷/章组装 BookVolume 树 — 内存按 volume_id 分组 + 显式排序.

        Args:
            volumes: 卷骨架（list_volumes）.
            chapters: 全量活动章节（已软删过滤）.

        Returns:
            命名卷（order_index ASC）+ 末尾「未分组」卷（volume_id 不在
            任何命名卷的章，仅当存在此类章时追加；§6.1 M5）.
        """
        chapters_by_volume: dict[uuid.UUID | None, list[Chapter]] = {}
        for chapter in chapters:
            chapters_by_volume.setdefault(chapter.volume_id, []).append(chapter)

        book_volumes: list[BookVolume] = []
        for volume in sorted(volumes, key=lambda v: v.order_index):
            volume_chapters = chapters_by_volume.pop(volume.id, [])
            book_volumes.append(
                BookVolume(
                    title=volume.title,
                    order_index=volume.order_index,
                    chapters=self._assemble_chapters(volume_chapters),
                )
            )
        leftover: list[Chapter] = []
        for remaining in chapters_by_volume.values():
            leftover.extend(remaining)
        if leftover:
            book_volumes.append(
                BookVolume(
                    title=_UNGROUPED_TITLE,
                    order_index=0.0,
                    chapters=self._assemble_chapters(leftover),
                )
            )
        return book_volumes

    def _assemble_chapters(self, chapters: list[Chapter]) -> list[BookChapter]:
        """卷内章排序 + BookChapter 字段映射（order_index ASC, created_at ASC）."""
        return [
            BookChapter(
                title=chapter.title,
                content=chapter.content,
                order_index=chapter.order_index,
                word_count=chapter.word_count,
            )
            for chapter in sorted(chapters, key=lambda c: (c.order_index, c.created_at))
        ]

    def _assemble_meta(self, project: Project) -> BookMeta:
        """Project → BookMeta 字段映射（genre 枚举 → 中文字面量）."""
        genre = project.genre.value if isinstance(project.genre, Genre) else str(project.genre)
        return BookMeta(
            title=project.name,
            genre=genre,
            language=project.language,
            target_words=project.target_words,
            updated_at=project.updated_at,
        )

    # ── 附录聚合（spec §5.1 ③/§6.3，include_settings=True 时）────

    async def _aggregate_settings(self, pid_int: int) -> list[BookSetting]:
        """5 类设定档案聚合 — asyncio.gather 并行拉取（§5.1 要点 2），组装顺序固定.

        Args:
            pid_int: 项目 int 主键.

        Returns:
            按 §6.1 排序键与 §6.3 摘要拼接规则组装的 BookSetting 列表.
        """
        characters, worlds, outlines, events, foreshadowings = await asyncio.gather(
            self._load_all(self._character_repo.list, pid_int),
            self._load_all(self._world_repo.list, pid_int),
            self._load_all(self._outline_repo.list, pid_int),
            self._timeline_repo.list_all(pid_int),
            self._load_all(self._foreshadowing_repo.list, pid_int),
        )

        # 组装顺序固定（§5.1 ③）: character → world → outline → timeline → foreshadowing
        settings: list[BookSetting] = []
        settings.extend(self._character_settings(characters))
        settings.extend(self._world_settings(worlds))
        settings.extend(await self._outline_settings(outlines))
        settings.extend(self._timeline_settings(events))
        settings.extend(self._foreshadowing_settings(foreshadowings))
        return settings

    def _character_settings(self, characters: list[Character]) -> list[BookSetting]:
        """角色附录 — created_at ASC；摘要 性格/背景/目标 行拼接（空字段跳过）."""
        result: list[BookSetting] = []
        for char in sorted(characters, key=lambda c: c.created_at):
            parts: list[str] = []
            if char.personality:
                parts.append(f"性格：{char.personality}")
            if char.background:
                parts.append(f"背景：{char.background}")
            if char.goals:
                parts.append(f"目标：{char.goals}")
            result.append(BookSetting(type="character", name=char.name, content="\n".join(parts)))
        return result

    def _world_settings(self, worlds: list[WorldSetting]) -> list[BookSetting]:
        """世界观附录 — created_at ASC；摘要 {category}：{content}（category 空省略）."""
        return [
            BookSetting(
                type="world",
                name=world.name,
                content=(f"{world.category}：{world.content}" if world.category else world.content),
            )
            for world in sorted(worlds, key=lambda w: w.created_at)
        ]

    async def _outline_settings(self, outlines: list[Outline]) -> list[BookSetting]:
        """大纲附录 — sort_order ASC, created_at ASC；情节点 position ASC 逐行拼接."""
        result: list[BookSetting] = []
        for outline in sorted(outlines, key=lambda o: (o.sort_order, o.created_at)):
            points = await self._outline_repo.list_points(_to_int_id(outline.id))
            lines = [outline.description]
            for point in sorted(points, key=lambda p: (p.position, p.created_at)):
                lines.append(f"- {point.name}（{point.type}）: {point.description}")
            result.append(BookSetting(type="outline", name=outline.name, content="\n".join(lines)))
        return result

    def _timeline_settings(self, events: list[TimelineEvent]) -> list[BookSetting]:
        """时间线附录 — narrative_position ASC, created_at ASC.

        摘要: {time_display}｜{description}（time_display 空 → 用 title）.
        """
        return [
            BookSetting(
                type="timeline",
                name=event.title,
                content=(
                    f"{event.time_display}｜{event.description}"
                    if event.time_display
                    else f"{event.title}｜{event.description}"
                ),
            )
            for event in sorted(events, key=lambda e: (e.narrative_position, e.created_at))
        ]

    def _foreshadowing_settings(self, foreshadowings: list[Foreshadowing]) -> list[BookSetting]:
        """伏笔附录 — created_at ASC.

        摘要: 状态：{status.value}｜{description}（location 非空追加埋设）.
        """
        result: list[BookSetting] = []
        for foreshadowing in sorted(foreshadowings, key=lambda f: f.created_at):
            content = f"状态：{foreshadowing.status.value}｜{foreshadowing.description}"
            if foreshadowing.location:
                content += f"｜埋设：{foreshadowing.location}"
            result.append(
                BookSetting(
                    type="foreshadowing",
                    name=foreshadowing.title,
                    content=content,
                )
            )
        return result
