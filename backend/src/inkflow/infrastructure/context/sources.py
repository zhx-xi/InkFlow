"""上下文数据源实现 — 收集各数据源产出的 ContextItem（issue #593 F6 数据源补齐）.

    - OutlineSource: 从 outlines 表读取大纲，按 level 分块注入（overall 恒注入 /
      volume / chapter 按当前章节匹配）+ 每块摘要化（≤60 字），#1234 起不再全文拼接
      （旧 ProjectConfigOutlineSource 读取 project.config.extra["outline"] 已移除）
    - CharacterSettingSource: 从 characters 表读取角色（名 + brief 轻量化，D5=A；
      brief 未填降级 personality）
    - WorldSettingSource: 从 world_settings 表读取世界观条目
    - ForeshadowingSource: 已由 F13（伏笔管理）实现 — 注入未回收伏笔提醒
      （ADR-019 编号口径：F13=伏笔管理，F14=统一提取）

依据: specs/f6-context/spec.md §3.2 / §4.3,
      specs/f13-foreshadowing/spec.md §5.3, ADR-010, ADR-019.
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.chapter import Chapter, normalize_chapter_title
from inkflow.domain.models.character import Character
from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol

_LEVEL_LABEL = {"overall": "总体", "volume": "卷", "chapter": "章"}
_LEVEL_PRIORITY = {"overall": 30, "volume": 20, "chapter": 10}
_SQLITE_INT_MAX = 2**63 - 1


def _summarize(description: str, limit: int = 60) -> str:
    """大纲描述摘要化 — 超 limit 字截断加省略号，否则原样返回（#1234）."""
    return description[:limit] + "…" if len(description) > limit else description


def _is_sqlite_int_id(value: uuid.UUID) -> bool:
    """UUID 主键是否落在 SQLite INTEGER 范围（溢出族 #1151 防护）."""
    return value.int <= _SQLITE_INT_MAX


class OutlineSource:
    """大纲数据源 — 从 outlines 表读取大纲，按 level 分块注入（#1234）.

    overall 块始终注入（每条一个块）；volume / chapter 块只注入与当前章节匹配的
    条目（chapter_id 精确关联 → 章标题三形态兜底；卷按 chapter.volume_id 关联或
    章纲 parent_id 上溯），其余卷/章不注入；每块描述摘要化（≤60 字）。

    Args:
        outline_repo: 大纲仓储（list 接受 int 主键，域内 UUID 以 project_id.int 转换）.
        chapter_repo: 章节仓储（可选；缺省 None = 未接线 —— 章标题兜底与
            chapter.volume_id 卷匹配不可用，chapter_id 精确匹配与 parent_id 上溯仍生效）.
    """

    def __init__(
        self,
        outline_repo: OutlineRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol | None = None,
    ) -> None:
        self._outline_repo = outline_repo
        self._chapter_repo = chapter_repo

    async def collect(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
    ) -> list[ContextItem]:
        """收集大纲条目 — 固定顺序 overall(s) → volume → chapter 分块返回.

        项目无大纲 → 空列表（跳过，不报错）；chapter_id=None 或越界
        （> 2^63-1，SQLite INTEGER 溢出族 #1151）→ 只注入 overall。
        """
        outlines, _total = await self._outline_repo.list(project_id.int)
        if not outlines:
            return []
        blocks = await self._resolve_blocks(outlines, chapter_id)
        outline_ids = [str(o.id) for o in blocks]
        return [
            ContextItem(
                source=ContextSourceType.OUTLINE,
                title="大纲",
                content=f"{_LEVEL_LABEL[o.level]}：{o.name} —— {_summarize(o.description)}",
                priority=_LEVEL_PRIORITY[o.level],
                metadata={"level": o.level, "outline_id": str(o.id), "outline_ids": outline_ids},
            )
            for o in blocks
        ]

    async def _resolve_blocks(
        self, outlines: list[Outline], chapter_id: uuid.UUID | None
    ) -> list[Outline]:
        """产出注入块序列：全部 overall（sort_order 升序）→ 命中卷纲 → 命中章纲."""
        blocks = sorted(
            (o for o in outlines if o.level == "overall"),
            key=lambda o: o.sort_order,
        )
        chapter_outline, chapter = await self._match_chapter(outlines, chapter_id)
        volume_outline = await self._match_volume(outlines, chapter, chapter_outline, chapter_id)
        if volume_outline is not None:
            blocks.append(volume_outline)
        if chapter_outline is not None:
            blocks.append(chapter_outline)
        return blocks

    async def _fetch_chapter(self, chapter_id: uuid.UUID | None) -> Chapter | None:
        """按需取章节实体；未接线 / 缺 id / id 越界 → None 且不查仓储（#1151）."""
        if self._chapter_repo is None or chapter_id is None or not _is_sqlite_int_id(chapter_id):
            return None
        chapter: Chapter | None = await self._chapter_repo.get_chapter(chapter_id.int)
        return chapter

    async def _match_chapter(
        self, outlines: list[Outline], chapter_id: uuid.UUID | None
    ) -> tuple[Outline | None, Chapter | None]:
        """定位当前章章纲：chapter_id 精确关联优先，缺关联时标题三形态兜底.

        Returns:
            (命中的章纲, 已取到的章节实体)；未匹配处为 None。精确命中路径不取
            章节实体（留待卷匹配按需懒取），标题兜底路径已取到实体。
        """
        if chapter_id is not None:
            exact = [o for o in outlines if o.level == "chapter" and o.chapter_id == chapter_id]
            if exact:
                return min(exact, key=lambda o: o.sort_order), None
        chapter = await self._fetch_chapter(chapter_id)
        if chapter is None:
            return None, None
        # 候选形态沿用 OutlineService.auto_link_chapter_by_title（#1001）先例
        candidates = {
            chapter.title,
            normalize_chapter_title(chapter.title, "arabic"),
            normalize_chapter_title(chapter.title, "chinese"),
        }
        hits = [o for o in outlines if o.level == "chapter" and o.name in candidates]
        if not hits:
            return None, chapter
        return min(hits, key=lambda o: o.sort_order), chapter

    async def _match_volume(
        self,
        outlines: list[Outline],
        chapter: Chapter | None,
        chapter_outline: Outline | None,
        chapter_id: uuid.UUID | None,
    ) -> Outline | None:
        """定位当前章所属卷纲：chapter.volume_id 关联优先，章纲 parent_id 上溯兜底.

        章纲未命中 → 无卷块；两途径皆未命中 → 无卷块（不报错）。
        """
        if chapter_outline is None:
            return None
        if chapter is None:
            chapter = await self._fetch_chapter(chapter_id)
        volumes = [o for o in outlines if o.level == "volume"]
        if chapter is not None and chapter.volume_id is not None:
            matched = [o for o in volumes if o.volume_id == chapter.volume_id]
            if matched:
                return min(matched, key=lambda o: o.sort_order)
        if chapter_outline.parent_id is not None:
            parents = [o for o in volumes if o.id == chapter_outline.parent_id]
            if parents:
                return min(parents, key=lambda o: o.sort_order)
        return None


class CharacterSettingSource:
    """角色设定数据源 — 从 characters 表读角色（D5=A：名 + brief 轻量化注入）.

    Args:
        character_repo: 角色仓储（list 接受 int 主键，域内 UUID 以 project_id.int 转换）.
    """

    def __init__(self, character_repo: CharacterRepositoryProtocol) -> None:
        self._character_repo = character_repo

    async def collect(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
    ) -> list[ContextItem]:
        """收集项目全部角色的设定条目；项目无角色 → 空列表（跳过，不报错）."""
        chars, _total = await self._character_repo.list(project_id.int)
        return [
            ContextItem(
                source=ContextSourceType.CHARACTER_SETTING,
                title=f"角色：{c.name}",
                content=_render_character(c),
                metadata={"character_id": str(c.id)},
            )
            for c in chars
        ]


def _render_character(c: Character) -> str:
    """角色注入文本确定性模板 — 名 + brief 轻量化（D5=A）.

    brief 非空 → 「名：brief」；brief 为空降级 personality；
    两者皆空 → 仅角色名（避免空内容条目）。
    """
    summary = c.brief if c.brief else (c.personality or c.name)
    if summary == c.name:
        return c.name
    return f"{c.name}：{summary}"


class WorldSettingSource:
    """世界设定数据源 — 从 world_settings 表读条目.

    Args:
        world_repo: 世界观仓储（list 接受 int 主键，域内 UUID 以 project_id.int 转换）.
    """

    def __init__(self, world_repo: WorldRepositoryProtocol) -> None:
        self._world_repo = world_repo

    async def collect(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
    ) -> list[ContextItem]:
        """收集项目全部世界观条目；项目无条目 → 空列表（跳过，不报错）."""
        settings, _total = await self._world_repo.list(project_id.int)
        return [
            ContextItem(
                source=ContextSourceType.WORLD_SETTING,
                title=f"世界观：{w.name}",
                content=_render_world(w),
                metadata={"world_setting_id": str(w.id), "category": w.category},
            )
            for w in settings
        ]


def _render_world(w: WorldSetting) -> str:
    """世界观条目注入文本确定性模板 — 「名：内容」（content 可为空，仍保留冒号）."""
    return f"{w.name}：{w.content}"


class ForeshadowingSource:
    """伏笔数据源 — 收集未回收（open）伏笔提醒（F13 真实实现）.

    Args:
        foreshadowing_repo: 伏笔仓储（list_open 查询 open 状态活动伏笔）.
    """

    def __init__(self, foreshadowing_repo: ForeshadowingRepositoryProtocol) -> None:
        self._repo = foreshadowing_repo

    async def collect(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
    ) -> list[ContextItem]:
        """收集全部未回收伏笔的提醒条目.

        - 项目不存在/无 open 伏笔 → 空列表（跳过，不报错，同 F6 数据源惯例）
        - 项目存在但所有伏笔已回收/已软删除 → 空列表（正常路径）
        - chapter_id 参数 MVP 不使用（全量注入 open 伏笔，按章节过滤归 Phase 2+）
        """
        items = await self._repo.list_open(project_id.int)  # (priority DESC, updated_at DESC)
        return [
            ContextItem(
                source=ContextSourceType.FORESHADOWING,
                title=f"伏笔：{f.title}",
                content=_render_reminder(f),  # 确定性模板，无 LLM
                priority=f.priority,  # 透传伏笔优先级（F6 dynamic 层排序键）
                metadata={
                    "foreshadowing_id": str(f.id),
                    "status": f.status.value,
                    "location": f.location,
                    "event_id": str(f.event_id) if f.event_id else None,
                },
            )
            for f in items
        ]


def _render_reminder(f: Foreshadowing) -> str:
    """提醒文本确定性模板 — 纯函数，无 LLM（spec §5.3）.

    首段固定「未回收伏笔：{title}。」；description 非空时追加描述段；
    location 非空时追加埋设位置段。全部来自伏笔档案字段。

    Args:
        f: 伏笔领域实体.

    Returns:
        提醒文本（分段以换行连接）.
    """
    parts = [f"未回收伏笔：{f.title}。"]
    if f.description:
        parts.append(f.description)
    if f.location:
        parts.append(f"（埋设位置：{f.location}）")
    return "\n".join(parts)
