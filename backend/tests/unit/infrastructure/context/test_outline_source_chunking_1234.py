"""RED 契约（#1234）— OutlineSource 按 level 分块 + 摘要化 + 卷/章匹配.

用户诉求（2026-09-17 拍板，issue #1234 读法 B）:
    1. 大纲注入只取「几十字摘要」，不注入全文（现 2392 字全文拼接）；
    2. 默认只注入与当前章节匹配的卷纲 + 章纲，其余卷/章不注入；
    3. 总纲（level=overall）始终注入。

契约（GREEN 后 OutlineSource.collect 必须满足）:
    - 产出多个 ContextItem（overall / volume / chapter 各一块），不再单条拼接；
    - 每块 content = f"{level_label}：{name} —— {summary}"，
      summary = description 截断 ≤60 字 + "…"（description ≤60 字时原样，无省略号）；
    - priority: overall=30 / volume=20 / chapter=10（同层排序，protected 层全量注入）；
    - metadata: {"level": <level>, "outline_id": str(o.id), "outline_ids": [全部注入 id]}；
    - 章匹配: outline.chapter_id == chapter_id 精确命中；
      未回填时标题兜底 — outline.name ∈ {章标题 原样/arabic/chinese 三归一形态}
      （沿用 OutlineService.auto_link_chapter_by_title #1001 先例）；
    - 卷匹配: chapter.volume_id → volume outline 的 volume_id 相等；
      或 chapter outline.parent_id == volume outline.id 上溯命中；
      chapter 命中但无卷关联 → 只注入 overall + chapter（不报错）；
    - chapter_id=None → 只注入 overall（总纲始终）；
    - chapter 不存在 / 未命中任何章纲 → 只注入 overall；
    - 无大纲 → []（既有契约不变）。

构造签名契约（GREEN 时不得偏离）:
    OutlineSource(outline_repo, chapter_repo=None)
    chapter_repo: ChapterRepositoryProtocol | None（get_chapter(int) -> Chapter | None）；
    None = 未接线（章标题兜底不可用，volume_id 上溯不可用 — 仅精确 chapter_id 匹配生效）。
    既有单参构造 OutlineSource(repo) 必须仍可运行（向后兼容）。

守卫: chapter_id.int > 2**63-1 时禁止调 get_chapter（SQLite INTEGER 溢出族，#1151）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.outline import Outline
from inkflow.infrastructure.context.sources import OutlineSource

PROJECT_ID = uuid.UUID(int=1)
CHAPTER_ID = uuid.UUID(int=100)
OTHER_CHAPTER_ID = uuid.UUID(int=200)
VOLUME_ID = uuid.UUID(int=300)


def _uuid(n: int) -> uuid.UUID:
    """构造确定性 UUID（UUID.int = n）."""
    return uuid.UUID(int=n)


def _make_outline(
    oid: int,
    name: str,
    level: str,
    description: str = "",
    sort_order: int = 0,
    parent_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    volume_id: uuid.UUID | None = None,
) -> Outline:
    """构造测试用 Outline（带三级关联字段）."""
    return Outline(
        id=_uuid(oid),
        project_id=PROJECT_ID,
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


def _make_chapter(title: str, volume_id: uuid.UUID | None = None) -> Chapter:
    """构造测试用 Chapter（title + volume_id 关联）."""
    return Chapter(
        id=CHAPTER_ID,
        project_id=PROJECT_ID,
        volume_id=volume_id,
        title=title,
        content="",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_source(
    outlines: list[Outline], chapter: Chapter | None = None
) -> tuple[OutlineSource, AsyncMock]:
    """装配 OutlineSource（outline_repo mock + chapter_repo mock）."""
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (outlines, len(outlines))
    chapter_repo = AsyncMock()
    chapter_repo.get_chapter.return_value = chapter
    return OutlineSource(outline_repo, chapter_repo=chapter_repo), chapter_repo


def _levels(items: list[ContextItem]) -> list[str]:
    return [str(item.metadata.get("level", "")) for item in items]


def _find(items: list[ContextItem], level: str) -> ContextItem:
    for item in items:
        if item.metadata.get("level") == level:
            return item
    raise AssertionError(f"缺少 level={level} 的注入块: got {_levels(items)}")


LONG_DESC = "蜀" * 200


class TestOutlineChunking:
    """契约 1 — 按 level 分块（不再单条拼接）."""

    async def test_three_levels_produce_three_blocks(self) -> None:
        """三级齐全 + 匹配命中 → 3 个独立块（overall/volume/chapter），非 1 条拼接."""
        outlines = [
            _make_outline(10, "总纲", "overall", "全书主线", sort_order=0),
            _make_outline(11, "第一卷", "volume", "卷级概要", sort_order=0, volume_id=VOLUME_ID),
            _make_outline(
                12, "第1章 开篇", "chapter", "章级概要", sort_order=0, chapter_id=CHAPTER_ID
            ),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章 开篇", VOLUME_ID))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 3, f"应产出 3 块（overall/volume/chapter），实得 {_levels(items)}"
        assert _levels(items) == ["overall", "volume", "chapter"]
        for item in items:
            assert item.source == ContextSourceType.OUTLINE
            assert isinstance(item, ContextItem)

    async def test_priority_order_overall_volume_chapter(self) -> None:
        """priority 契约: overall=30 > volume=20 > chapter=10（protected 层内排序）."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(11, "第一卷", "volume", volume_id=VOLUME_ID),
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章", VOLUME_ID))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        by_level = {str(i.metadata["level"]): i for i in items}
        assert by_level["overall"].priority == 30
        assert by_level["volume"].priority == 20
        assert by_level["chapter"].priority == 10

    async def test_metadata_carries_level_and_ids(self) -> None:
        """metadata 契约: 每块带 level + outline_id；全部块共享 outline_ids（注入集）."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章"))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        for item in items:
            assert item.metadata["outline_id"] in {str(_uuid(10)), str(_uuid(12))}
            assert set(item.metadata["outline_ids"]) == {str(_uuid(10)), str(_uuid(12))}


class TestOutlineSummary:
    """契约 2 — 摘要化（content ≤ 阈值）."""

    async def test_long_description_truncated_to_60(self) -> None:
        """description 200 字 → 截断 60 字 + "…"（issue 验收判据 2）."""
        outlines = [_make_outline(10, "总纲", "overall", LONG_DESC)]
        source, _ = _make_source(outlines, None)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        overall = _find(items, "overall")
        assert overall.content.endswith("…")
        assert LONG_DESC[:60] in overall.content
        assert LONG_DESC[60:] not in overall.content
        # 整块长度 = label + name + 分隔 + 60 字摘要 + 省略号 ≪ 原 2392 字全文
        assert len(overall.content) <= 100

    async def test_short_description_kept_verbatim_no_ellipsis(self) -> None:
        """description ≤ 60 字 → 原样，不加省略号."""
        outlines = [_make_outline(10, "总纲", "overall", "全书主线概述")]
        source, _ = _make_source(outlines, None)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        overall = _find(items, "overall")
        assert "全书主线概述" in overall.content
        assert not overall.content.endswith("…")

    async def test_content_format_label_name_summary(self) -> None:
        """content 形态 = "{level_label}：{name} —— {summary}"（既有渲染惯例延续）."""
        outlines = [_make_outline(10, "总纲", "overall", "全书主线")]
        source, _ = _make_source(outlines, None)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _find(items, "overall").content == "总体：总纲 —— 全书主线"


class TestOutlineMatching:
    """契约 3 — 卷/章按当前章节匹配（反向断言是关键）."""

    async def test_only_matching_chapter_injected(self) -> None:
        """精确 chapter_id 命中 → 只注入该章纲；其它章纲不注入（反向断言）."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID),
            _make_outline(13, "第2章", "chapter", chapter_id=OTHER_CHAPTER_ID),
            _make_outline(14, "第3章", "chapter", chapter_id=_uuid(300)),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章"))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        chapter = _find(items, "chapter")
        assert chapter.metadata["outline_id"] == str(_uuid(12))
        assert "第2章" not in "".join(i.content for i in items)
        assert "第3章" not in "".join(i.content for i in items)

    async def test_title_fallback_when_chapter_id_not_linked(self) -> None:
        """章纲未回填 chapter_id → 标题兜底命中（原样/arabic/chinese 三形态之一）."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(12, "第1章 风雨", "chapter"),  # 无 chapter_id
            _make_outline(13, "第2章 雷鸣", "chapter"),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章 风雨"))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _find(items, "chapter").metadata["outline_id"] == str(_uuid(12))

    async def test_title_fallback_chinese_number_variant(self) -> None:
        """标题兜底的归一形态：章标题「第一章 风雨」匹配大纲名「第1章 风雨」."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(12, "第1章 风雨", "chapter"),
        ]
        source, _ = _make_source(outlines, _make_chapter("第一章 风雨"))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _find(items, "chapter").metadata["outline_id"] == str(_uuid(12))

    async def test_only_matching_volume_injected(self) -> None:
        """当前章属卷 A → 只注入卷 A 纲；其它卷纲不注入（反向断言）."""
        vol_b = _uuid(301)
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(11, "第一卷", "volume", volume_id=VOLUME_ID),
            _make_outline(15, "第二卷", "volume", volume_id=vol_b),
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章", VOLUME_ID))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        volume = _find(items, "volume")
        assert volume.metadata["outline_id"] == str(_uuid(11))
        assert "第二卷" not in "".join(i.content for i in items)

    async def test_volume_matched_via_parent_chain(self) -> None:
        """章纲 parent_id → 卷纲 id 上溯命中（章未挂 volume_id 的形态）."""
        vol_outline = _make_outline(11, "第一卷", "volume")
        outlines = [
            _make_outline(10, "总纲", "overall"),
            vol_outline,
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID, parent_id=vol_outline.id),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章"))  # chapter.volume_id=None

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _find(items, "volume").metadata["outline_id"] == str(_uuid(11))

    async def test_chapter_without_volume_still_injects_overall_and_chapter(self) -> None:
        """章命中但无卷关联 → overall + chapter 两块，不报错（issue 验收判据 4）."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章", volume_id=None))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _levels(items) == ["overall", "chapter"]


class TestOutlineOverallAlways:
    """契约 4 — 总纲始终注入."""

    async def test_overall_injected_without_chapter_context(self) -> None:
        """chapter_id=None → 仅 overall（卷/章无匹配依据，不注入）."""
        outlines = [
            _make_outline(10, "总纲", "overall", "全书主线"),
            _make_outline(11, "第一卷", "volume", volume_id=VOLUME_ID),
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID),
        ]
        source, chapter_repo = _make_source(outlines, _make_chapter("第1章", VOLUME_ID))

        items = await source.collect(PROJECT_ID, None)

        assert _levels(items) == ["overall"]
        assert _find(items, "overall").content == "总体：总纲 —— 全书主线"
        chapter_repo.get_chapter.assert_not_awaited()

    async def test_overall_injected_when_chapter_missing(self) -> None:
        """chapter_repo 查无此章（get_chapter → None）→ 标题兜底不可用，仅 overall.

        章纲无 chapter_id 精确关联（否则精确匹配不依赖 chapter 实体，仍会注入）。
        """
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(12, "第1章", "chapter"),  # 无 chapter_id 关联
        ]
        source, _ = _make_source(outlines, None)  # get_chapter → None

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _levels(items) == ["overall"]

    async def test_overall_injected_when_no_chapter_outline_matches(self) -> None:
        """当前章无对应章纲 → 仅 overall（不误注入其它章纲，反向断言）."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(13, "第2章", "chapter", chapter_id=OTHER_CHAPTER_ID),
        ]
        source, _ = _make_source(outlines, _make_chapter("第1章"))

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _levels(items) == ["overall"]
        assert "第2章" not in items[0].content

    async def test_multiple_overall_outlines_all_injected(self) -> None:
        """多条 overall（总纲+分卷总述形态）→ 全部注入（overall 不过滤）."""
        outlines = [
            _make_outline(10, "总纲", "overall", "主线", sort_order=0),
            _make_outline(11, "副纲", "overall", "暗线", sort_order=1),
        ]
        source, _ = _make_source(outlines, None)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert _levels(items) == ["overall", "overall"]
        joined = "".join(i.content for i in items)
        assert "主线" in joined
        assert "暗线" in joined


class TestOutlineBackwardCompat:
    """既有契约兼容 — 单参构造 + 空大纲 + 溢出守卫."""

    async def test_single_arg_construction_still_works(self) -> None:
        """OutlineSource(repo) 单参构造（既有测试形态）→ 仍可 collect，overall 注入."""
        outlines = [_make_outline(10, "总纲", "overall", "全书主线")]
        repo = AsyncMock()
        repo.list.return_value = (outlines, 1)
        source = OutlineSource(repo)

        items = await source.collect(PROJECT_ID, None)

        assert _levels(items) == ["overall"]
        repo.list.assert_awaited_once_with(PROJECT_ID)

    async def test_no_outlines_returns_empty(self) -> None:
        """项目无大纲 → []（既有契约不变）."""
        source, _ = _make_source([], None)

        assert await source.collect(PROJECT_ID, CHAPTER_ID) == []

    async def test_overflow_chapter_id_skips_repo_lookup(self) -> None:
        """chapter_id.int > 2^63-1 → 不调 get_chapter（SQLite INTEGER 溢出守卫，#1151 族）."""
        outlines = [
            _make_outline(10, "总纲", "overall"),
            _make_outline(12, "第1章", "chapter", chapter_id=CHAPTER_ID),
        ]
        source, chapter_repo = _make_source(outlines, _make_chapter("第1章"))
        big_chapter_id = uuid.uuid4()  # 128-bit 随机 UUID，必溢出

        items = await source.collect(PROJECT_ID, big_chapter_id)

        assert _levels(items) == ["overall"]
        chapter_repo.get_chapter.assert_not_awaited()
