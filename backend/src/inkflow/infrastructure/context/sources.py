"""上下文数据源实现 — 收集各数据源产出的 ContextItem（issue #593 F6 数据源补齐）.

    - OutlineSource: 从 outlines 表读取大纲（overall→volume→chapter 三级，缺级降级；
      旧 ProjectConfigOutlineSource 读取 project.config.extra["outline"] 已移除）
    - CharacterSettingSource: 从 characters 表读取角色（名 + brief 轻量化，D5=A；
      brief 未填降级 personality）
    - WorldSettingSource: 从 world_settings 表读取世界观条目
    - ForeshadowingSource: 已由 F13（伏笔管理）实现 — 注入未回收伏笔提醒
      （ADR-019 编号口径：F13=伏笔管理，F14=统一提取）

依据: specs/f6-context-service/spec.md §3.2 / §4.3,
      specs/f13-foreshadowing-service/spec.md §5.3, ADR-010, ADR-019.
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.character import Character
from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol

_LEVEL_ORDER = {"overall": 0, "volume": 1, "chapter": 2}
_LEVEL_LABEL = {"overall": "总体", "volume": "卷", "chapter": "章"}


class OutlineSource:
    """大纲数据源 — 从 outlines 表读取大纲（overall→volume→chapter 三级，缺级降级）.

    Args:
        outline_repo: 大纲仓储（list 接受 int 主键，域内 UUID 以 project_id.int 转换）.
    """

    def __init__(self, outline_repo: OutlineRepositoryProtocol) -> None:
        self._outline_repo = outline_repo

    async def collect(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
    ) -> list[ContextItem]:
        """收集大纲条目；项目无大纲 → 空列表（跳过，不报错）.

        按 level（overall→volume→chapter）再 sort_order 排序，合并渲染为单个条目。
        """
        outlines, _total = await self._outline_repo.list(project_id.int)
        if not outlines:
            return []
        ordered = sorted(outlines, key=lambda o: (_LEVEL_ORDER[o.level], o.sort_order))
        content = "\n".join(
            f"{_LEVEL_LABEL[o.level]}：{o.name} —— {o.description}" for o in ordered
        )
        return [
            ContextItem(
                source=ContextSourceType.OUTLINE,
                title="大纲",
                content=content,
                metadata={"outline_ids": [str(o.id) for o in outlines]},
            )
        ]


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
