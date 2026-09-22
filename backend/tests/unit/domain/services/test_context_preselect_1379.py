"""#1379 RED 契约：上下文 Agent 预选（按本章大纲预挑相关条目）.

现象（v0.15.0-rc5 GUI 目视）：进入空章时上下文注入面板默认「全选」——
用户期望默认勾选 = 与本章相关的子集（按大纲 / 情节点 / 写作要求）。

本文件测 `ContextService.preselect_context` 的契约：
  1. 有候选 + 有大纲 → 一次预选调用（preselect_fn）→ 返回三类 id 子集
  2. 无大纲 → 回退全选（mode="fallback"），不调用预选
  3. 预选失败（异常）→ 回退全选（mode="fallback"）
  4. 脏 id（不在候选集内，LLM 幻觉）→ 被过滤；合法 id 保留
     （可证伪自证：去掉候选集过滤后，本用例的 `== [CHAR_A]` 断言必 FAIL）
  5. 未接线（preselect_fn=None）→ 回退全选
  6. 无候选（三类皆空）→ 空集 + mode="agent"（没得选，不算回退）
  7. writing_requirements 为空 → ValueError（与 build_context 同口径）

依据: issue #1379（方案 A）。
"""

from __future__ import annotations

import uuid

import pytest

from inkflow.domain.models.context import (
    ContextItem,
    ContextOverride,
    ContextPreselectRequest,
    ContextSourceType,
)
from inkflow.domain.services.context_service import ContextService

# ── 固定 id（断言可读） ────────────────────────────────────────────────

CHAR_A = uuid.UUID("10000000-0000-4000-8000-000000000001")
CHAR_B = uuid.UUID("10000000-0000-4000-8000-000000000002")
WORLD_A = uuid.UUID("20000000-0000-4000-8000-000000000001")
WORLD_B = uuid.UUID("20000000-0000-4000-8000-000000000002")
FORE_A = uuid.UUID("30000000-0000-4000-8000-000000000001")
FORE_B = uuid.UUID("30000000-0000-4000-8000-000000000002")
DIRTY = uuid.UUID("90000000-0000-4000-8000-0000000000ff")
"""候选集之外的 id（模拟 LLM 幻觉/串项目）。"""


# ── 辅助工厂 ──────────────────────────────────────────────────────────


def _item(
    source: ContextSourceType,
    title: str,
    content: str,
    metadata: dict[str, object] | None = None,
    priority: int = 0,
) -> ContextItem:
    return ContextItem(
        source=source,
        title=title,
        content=content,
        priority=priority,
        metadata=metadata or {},
    )


class MockSource:
    """返回固定 items 的 Mock 数据源（同 test_context_service.py 形态）。"""

    def __init__(self, items: list[ContextItem] | None = None) -> None:
        self._items = items or []

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        return list(self._items)


def _sources(with_outline: bool = True) -> dict[ContextSourceType, MockSource]:
    """三类候选（各 2 条）+ 可选大纲块。"""
    sources: dict[ContextSourceType, MockSource] = {
        ContextSourceType.CHARACTER_SETTING: MockSource(
            [
                _item(
                    ContextSourceType.CHARACTER_SETTING,
                    "角色：甲",
                    "甲：少年剑客",
                    {"character_id": str(CHAR_A)},
                ),
                _item(
                    ContextSourceType.CHARACTER_SETTING,
                    "角色：乙",
                    "乙：门派长老",
                    {"character_id": str(CHAR_B)},
                ),
            ]
        ),
        ContextSourceType.WORLD_SETTING: MockSource(
            [
                _item(
                    ContextSourceType.WORLD_SETTING,
                    "世界观：山门",
                    "山门：北方剑宗",
                    {"world_setting_id": str(WORLD_A), "category": "location"},
                ),
                _item(
                    ContextSourceType.WORLD_SETTING,
                    "世界观：禁地",
                    "禁地：后山封印",
                    {"world_setting_id": str(WORLD_B), "category": "location"},
                ),
            ]
        ),
        ContextSourceType.FORESHADOWING: MockSource(
            [
                _item(
                    ContextSourceType.FORESHADOWING,
                    "伏笔：玉佩来历",
                    "未回收伏笔：玉佩来历。",
                    {"foreshadowing_id": str(FORE_A), "status": "open"},
                ),
                _item(
                    ContextSourceType.FORESHADOWING,
                    "伏笔：长老旧伤",
                    "未回收伏笔：长老旧伤。",
                    {"foreshadowing_id": str(FORE_B), "status": "open"},
                ),
            ]
        ),
    }
    if with_outline:
        sources[ContextSourceType.OUTLINE] = MockSource(
            [
                _item(
                    ContextSourceType.OUTLINE,
                    "大纲",
                    "章：初入山门 —— 少年甲拜入乙门下",
                    {"level": "chapter", "outline_id": str(uuid.uuid4())},
                    priority=10,
                ),
            ]
        )
    return sources


def _preq(**overrides: object) -> ContextPreselectRequest:
    defaults: dict[str, object] = {
        "project_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "model": "openai/gpt-4o",
        "writing_requirements": "续写第 3 章",
    }
    defaults.update(overrides)
    return ContextPreselectRequest(**defaults)  # type: ignore[arg-type]  # 测试工厂动态 kwargs


# ── 1 · 子集返回 ──────────────────────────────────────────────────────


class TestPreselectSubset:
    """预选成功路径：一次调用 → 三类 id 子集。"""

    async def test_returns_llm_subset_and_feeds_outline(self) -> None:
        calls: list[tuple[list[ContextItem], str, str, str]] = []

        async def preselect_fn(
            candidates: list[ContextItem],
            outline_text: str,
            requirements: str,
            model: str,
        ) -> ContextOverride:
            calls.append((candidates, outline_text, requirements, model))
            return ContextOverride(
                character_ids=[CHAR_A],
                world_ids=[WORLD_B],
                foreshadowing_ids=[],
            )

        svc = ContextService(sources=_sources(), preselect_fn=preselect_fn)
        result = await svc.preselect_context(_preq())

        assert result.mode == "agent"
        assert result.character_ids == [CHAR_A]
        assert result.world_ids == [WORLD_B]
        assert result.foreshadowing_ids == []

        # 输入面契约：候选 / 大纲文本 / 写作要求 / 模型 全部进预选调用
        assert len(calls) == 1
        candidates, outline_text, requirements, model = calls[0]
        assert {
            str(c.metadata.get("character_id"))
            for c in candidates
            if c.source == ContextSourceType.CHARACTER_SETTING
        } == {
            str(CHAR_A),
            str(CHAR_B),
        }
        assert "初入山门" in outline_text
        assert requirements == "续写第 3 章"
        assert model == "openai/gpt-4o"


# ── 2-3 · 回退全选 ────────────────────────────────────────────────────


class TestPreselectFallback:
    """回退路径：无大纲 / 预选异常 / 未接线 → 全选。"""

    async def test_falls_back_without_outline_without_llm_call(self) -> None:
        called = False

        async def preselect_fn(*args: object) -> ContextOverride:
            nonlocal called
            called = True
            return ContextOverride()

        svc = ContextService(sources=_sources(with_outline=False), preselect_fn=preselect_fn)
        result = await svc.preselect_context(_preq())

        assert result.mode == "fallback"
        assert result.character_ids == [CHAR_A, CHAR_B]
        assert result.world_ids == [WORLD_A, WORLD_B]
        assert result.foreshadowing_ids == [FORE_A, FORE_B]
        assert called is False, "无大纲时必须直接回退，不得浪费一次 LLM 调用"

    async def test_falls_back_on_preselect_error(self) -> None:
        async def preselect_fn(*args: object) -> ContextOverride:
            raise RuntimeError("llm down")

        svc = ContextService(sources=_sources(), preselect_fn=preselect_fn)
        result = await svc.preselect_context(_preq())

        assert result.mode == "fallback"
        assert result.character_ids == [CHAR_A, CHAR_B]
        assert result.world_ids == [WORLD_A, WORLD_B]
        assert result.foreshadowing_ids == [FORE_A, FORE_B]

    async def test_falls_back_when_not_wired(self) -> None:
        svc = ContextService(sources=_sources())
        result = await svc.preselect_context(_preq())

        assert result.mode == "fallback"
        assert result.character_ids == [CHAR_A, CHAR_B]


# ── 4 · 候选集过滤（可证伪自证） ────────────────────────────────────────


class TestPreselectDirtyIds:
    """脏 id 过滤：LLM 幻觉 id 不得进入结果。

    可证伪自证：若实现去掉「∩ 候选集」过滤，`== [CHAR_A]` 与
    `DIRTY not in` 两条断言必 FAIL（脏 id 会原样透传）。
    """

    async def test_dirty_ids_filtered_legal_kept(self) -> None:
        async def preselect_fn(*args: object) -> ContextOverride:
            return ContextOverride(
                character_ids=[CHAR_A, DIRTY],
                world_ids=[DIRTY],
                foreshadowing_ids=[FORE_A],
            )

        svc = ContextService(sources=_sources(), preselect_fn=preselect_fn)
        result = await svc.preselect_context(_preq())

        assert result.mode == "agent"
        assert result.character_ids == [CHAR_A]
        assert DIRTY not in result.character_ids
        assert result.world_ids == []
        assert DIRTY not in result.world_ids
        assert result.foreshadowing_ids == [FORE_A]


# ── 5-7 · 边界 ────────────────────────────────────────────────────────


class TestPreselectEdges:
    """无候选 / 空写作要求边界。"""

    async def test_empty_candidates_returns_empty_agent_without_llm_call(self) -> None:
        called = False

        async def preselect_fn(*args: object) -> ContextOverride:
            nonlocal called
            called = True
            return ContextOverride()

        # 只有大纲，三类候选全空
        svc = ContextService(
            sources={ContextSourceType.OUTLINE: _sources()[ContextSourceType.OUTLINE]},
            preselect_fn=preselect_fn,
        )
        result = await svc.preselect_context(_preq())

        assert result.mode == "agent"
        assert result.character_ids == []
        assert result.world_ids == []
        assert result.foreshadowing_ids == []
        assert called is False

    async def test_empty_writing_requirements_raises_value_error(self) -> None:
        svc = ContextService(sources=_sources())

        with pytest.raises(ValueError):
            await svc.preselect_context(_preq(writing_requirements="   "))
