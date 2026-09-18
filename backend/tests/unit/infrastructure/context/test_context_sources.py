"""上下文数据源测试 — 角色/世界观/大纲接真表（issue #593 F6 数据源补齐）.

测试范围 (spec f6-context v1.1):
    - CharacterSettingSource: 从 characters 表读角色，产出 source=character_setting 的 ContextItem
      （内容 = 角色名 + brief；brief 未填降级截 personality）
    - WorldSettingSource: 从 world_settings 表读条目，产出 source=world_setting 的 ContextItem
    - OutlineSource: 从 outlines 表读大纲（#1234：按 level 分块 + 摘要化 + 卷/章匹配）
    - 伏笔数据源: 已由 F13 实现（ForeshadowingSource），测试见 test_foreshadowing_source.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.character import Character
from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.world import WorldSetting
from inkflow.infrastructure.context.sources import (
    CharacterSettingSource,
    OutlineSource,
    WorldSettingSource,
)


def _uuid(n: int) -> uuid.UUID:
    """构造确定性 UUID（UUID.int = n）."""
    return uuid.UUID(int=n)


def _make_character(
    pid: int,
    cid: int,
    name: str,
    brief: str = "",
    personality: str = "",
    background: str = "",
    goals: str = "",
) -> Character:
    """构造测试用 Character."""
    return Character(
        id=_uuid(cid),
        project_id=_uuid(pid),
        name=name,
        brief=brief,
        personality=personality,
        background=background,
        goals=goals,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_world(
    pid: int,
    wid: int,
    name: str,
    category: str = "",
    content: str = "",
) -> WorldSetting:
    """构造测试用 WorldSetting."""
    return WorldSetting(
        id=_uuid(wid),
        project_id=_uuid(pid),
        name=name,
        category=category,
        content=content,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_outline(
    pid: int,
    oid: int,
    name: str,
    level: str,
    description: str = "",
    sort_order: int = 0,
    parent_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    volume_id: uuid.UUID | None = None,
) -> Outline:
    """构造测试用 Outline（#1234：补三级关联字段）."""
    return Outline(
        id=_uuid(oid),
        project_id=_uuid(pid),
        name=name,
        level=level,
        description=description,
        sort_order=sort_order,
        parent_id=parent_id,
        chapter_id=chapter_id,
        volume_id=volume_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_chapter_entity(
    cid: uuid.UUID,
    title: str,
    volume_id: uuid.UUID | None = None,
) -> Chapter:
    """构造测试用 Chapter（#1234：章标题 + 卷关联，供 OutlineSource 匹配）."""
    return Chapter(
        id=cid,
        project_id=_uuid(1),
        volume_id=volume_id,
        title=title,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestCharacterSettingSource:
    """角色设定数据源 — 从 characters 表读角色（D5=A：名 + brief 轻量化注入）."""

    async def test_returns_character_item_with_name_and_brief(self) -> None:
        """brief 非空 → content = 角色名 + brief，source=character_setting."""
        char = _make_character(pid=1, cid=10, name="林晚", brief="冷傲大小姐", personality="高冷")
        repo = AsyncMock()
        repo.list.return_value = ([char], 1)
        source = CharacterSettingSource(repo)

        items = await source.collect(_uuid(1), _uuid(2))

        assert len(items) == 1
        item = items[0]
        assert isinstance(item, ContextItem)
        assert item.source == ContextSourceType.CHARACTER_SETTING
        assert item.title == "角色：林晚"
        assert item.content == "林晚：冷傲大小姐"
        assert item.metadata["character_id"] == str(char.id)
        # 按真实仓储契约调用 list(project_id)（#1291：领域 UUID 直传）
        repo.list.assert_awaited_once_with(_uuid(1))

    async def test_falls_back_to_personality_when_brief_empty(self) -> None:
        """brief 未填 → 降级截 personality（D5-a1 降级逻辑）."""
        char = _make_character(pid=1, cid=11, name="萧炎", brief="", personality="坚韧隐忍")
        repo = AsyncMock()
        repo.list.return_value = ([char], 1)
        source = CharacterSettingSource(repo)

        items = await source.collect(_uuid(1), _uuid(2))

        assert items[0].content == "萧炎：坚韧隐忍"

    async def test_returns_multiple_characters(self) -> None:
        """多角色 → 每角色一条 ContextItem."""
        chars = [
            _make_character(pid=1, cid=12, name="林尘", brief="废柴觉醒者"),
            _make_character(pid=1, cid=13, name="青云真人", brief="元婴老祖"),
        ]
        repo = AsyncMock()
        repo.list.return_value = (chars, 2)
        source = CharacterSettingSource(repo)

        items = await source.collect(_uuid(1), _uuid(2))

        assert len(items) == 2
        assert {i.metadata["character_id"] for i in items} == {str(c.id) for c in chars}

    async def test_returns_empty_when_no_characters(self) -> None:
        """项目无角色 → 空列表（跳过，不报错）."""
        repo = AsyncMock()
        repo.list.return_value = ([], 0)
        source = CharacterSettingSource(repo)

        assert await source.collect(_uuid(1), _uuid(2)) == []


class TestWorldSettingSource:
    """世界设定数据源 — 从 world_settings 表读条目."""

    async def test_returns_world_item(self) -> None:
        """世界设定非空 → source=world_setting 的 ContextItem."""
        world = _make_world(
            pid=1, wid=20, name="灵气复苏", category="设定", content="公元2048年灵气浓度回升"
        )
        repo = AsyncMock()
        repo.list.return_value = ([world], 1)
        source = WorldSettingSource(repo)

        items = await source.collect(_uuid(1), _uuid(2))

        assert len(items) == 1
        item = items[0]
        assert isinstance(item, ContextItem)
        assert item.source == ContextSourceType.WORLD_SETTING
        assert item.title == "世界观：灵气复苏"
        assert "灵气复苏" in item.content
        assert item.metadata["world_setting_id"] == str(world.id)
        repo.list.assert_awaited_once_with(_uuid(1))

    async def test_returns_empty_when_no_world_settings(self) -> None:
        """项目无世界设定 → 空列表（跳过，不报错）."""
        repo = AsyncMock()
        repo.list.return_value = ([], 0)
        source = WorldSettingSource(repo)

        assert await source.collect(_uuid(1), _uuid(2)) == []


class TestOutlineSource:
    """大纲数据源 — #1234 起按 level 分块 + 摘要化 + 卷/章匹配（不再单条拼接）.

    完整契约（分块/摘要阈值/匹配/反向断言/总纲始终/溢出守卫）见
    test_outline_source_chunking_1234.py；本类只保留基础渲染与降级的冒烟锚点。
    """

    async def test_renders_matched_levels_as_blocks(self) -> None:
        """三级齐全 + 匹配命中 → overall/volume/chapter 各一块（非单条拼接）."""
        pid, cid, vid = _uuid(1), _uuid(2), _uuid(9)
        outlines = [
            _make_outline(1, 30, "主线", "overall", "全书主线", sort_order=0),
            _make_outline(1, 31, "第一卷", "volume", "青云宗", sort_order=0, volume_id=vid),
            _make_outline(1, 32, "第一章", "chapter", "开局", sort_order=0, chapter_id=cid),
        ]
        repo = AsyncMock()
        repo.list.return_value = (outlines, 3)
        chapter_repo = AsyncMock()
        chapter_repo.get_chapter.return_value = _make_chapter_entity(cid, "第一章", vid)
        source = OutlineSource(repo, chapter_repo=chapter_repo)

        items = await source.collect(pid, cid)

        assert len(items) == 3
        assert [str(i.metadata["level"]) for i in items] == ["overall", "volume", "chapter"]
        for item in items:
            assert isinstance(item, ContextItem)
            assert item.source == ContextSourceType.OUTLINE
        assert items[0].content == "总体：主线 —— 全书主线"
        repo.list.assert_awaited_once_with(pid)

    async def test_returns_empty_when_only_unmatched_chapter(self) -> None:
        """孤立章 + 无 overall + chapter_id 不匹配 → 空列表（降级不报错）."""
        outlines = [_make_outline(1, 33, "孤儿章", "chapter", "无父级")]
        repo = AsyncMock()
        repo.list.return_value = (outlines, 1)
        source = OutlineSource(repo)

        # chapter_id=_uuid(2) 与孤立章无关联、标题也不匹配 → 不注入
        assert await source.collect(_uuid(1), _uuid(2)) == []

    async def test_returns_empty_when_no_outlines(self) -> None:
        """项目无大纲 → 空列表（跳过，不报错）."""
        repo = AsyncMock()
        repo.list.return_value = ([], 0)
        source = OutlineSource(repo)

        assert await source.collect(_uuid(1), _uuid(2)) == []
