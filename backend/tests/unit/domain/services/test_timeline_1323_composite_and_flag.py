"""#1323 P1 后端修正 — 合成叙事序 + 标记包含式匹配 契约（RED）。

【现象（父侧已实证）】
G4：`_timeline_extractor.py:272-274` 把 LLM 返回的 `narrative_position` **原样落库**
    （仅 None 才走 `next_position`），而 `i18n/prompts/zh/timeline_extract.yaml:9` 要求
    「叙事位置 = 事件在**本章**叙事中出现的先后（从 1 开始）」→ **每章都从 1 重数，
    跨章必然碰撞**。DB 实测：215 条事件只有 34 个不同 position 值，1/6/7 各对应 10 条。

G6：`timeline_service._classify_pair` 的标记识别是**字面量**等值比较
    （`timeline_flag == "flashback"` / `"flashforward"`），而真实数据是**中文自由文本**
    （DB 实测：''=181, 倒叙=29, 插叙=3, 梦境=1, 回忆=1）→ **33 条已声明倒叙/插叙被当作
    「未标记」**，直接产 `order_conflict`（error 级 finding），串到审计报告。

【本批契约（#1323 拍板）】
- G4 修法 = **合成序**（章序 × 基数 + 章内序），**不是**「忽略 LLM 值」——
  章内序在章分组视图里是有用的排序键，直接丢会退化。
  → 同一章内 LLM 给出的章内序必须**决定该章内事件的相对先后**；
  → 不同章的合成序必须**互不碰撞**（跨章 collision 归零）。
- G6 修法 = **包含式匹配**（`倒叙`/`flashback` 等子串命中）——既有测试用英文值，
  包含式对既有测试**零破坏**（反向断言 D3 守护）。
- prompt 同步补枚举（`timeline_flag` 建议词表 + 「章内序仅作参考」）。

【RED 预期】
- C1/C2/C3 合成序：现实现原样落库 → 跨章碰撞，FAIL
- D1/D2 中文标记：现实现字面量匹配 → 中文值被当未标记，产 order_conflict，FAIL
- D3 反向断言（既有英文值仍合法）：现实现已通过 → **本测试在修复前本就是绿的，这是正确的**
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.timeline import (
    TimelineEvent,
    TimelineExtractRequest,
)
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services._timeline_extractor import TimelineExtractor
from inkflow.domain.services.timeline_service import TimelineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID_A = uuid.UUID("9b1c2d3e-0000-4000-8000-0000000000a1")
CID_B = uuid.UUID("9b1c2d3e-0000-4000-8000-0000000000b1")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
DEFAULT_MODEL = "openai/gpt-4o"


# ─────────────────────────── G4：合成叙事序 ───────────────────────────


def _ok_response(payload: str) -> ChatResponse:
    return ChatResponse(content=payload, model=DEFAULT_MODEL)


def _payload(events: list[dict]) -> str:
    return json.dumps({"events": events}, ensure_ascii=False)


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    pm = MagicMock(spec=PromptTemplateProtocol)
    pm.load = MagicMock(
        return_value=PromptTemplate(
            name="timeline_extract",
            description="t",
            system_prompt="s",
            human_prompt="{text}",
            variables=["text"],
        )
    )
    pm.render = MagicMock(
        return_value=RenderedPrompt(messages=[{"role": "user", "content": "x"}], token_estimate=1)
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.list_by_chapter = AsyncMock(return_value=[])
    repo.list = AsyncMock(return_value=([], 0))
    repo.update = AsyncMock(side_effect=lambda e: e)
    # 🔴 next_position 必须**模拟真实仓储语义**（项目内 max(narrative_position)+1），
    # 否则两章拿到同一个固定基址 → 假碰撞。真实现见 timeline_repo.py:238-250。
    _added: list[int] = []

    async def _add(e):
        _added.append(e.narrative_position)
        return e

    repo.add = AsyncMock(side_effect=_add)
    repo.next_position = AsyncMock(side_effect=lambda _pid: max(_added, default=0) + 1)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_prompt_manager, mock_repo) -> TimelineExtractor:
    return TimelineExtractor(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        timeline_repo=mock_repo,
    )


class TestCompositeNarrativePosition:
    """G4：提取落库的叙事序 = 合成序（章序×基数 + 章内序），跨章不碰撞。"""

    async def test_chapter_internal_order_preserved(self, extractor, mock_llm) -> None:
        """同一章内：LLM 给的章内序（3,1,2）必须决定该章内事件的相对先后。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                [
                    {"title": "丙", "narrative_position": 3, "timeline_flag": ""},
                    {"title": "甲", "narrative_position": 1, "timeline_flag": ""},
                    {"title": "乙", "narrative_position": 2, "timeline_flag": ""},
                ]
            )
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID_A, text="t"),
            default_model=DEFAULT_MODEL,
        )
        by_title = {e.title: e.narrative_position for e in result.created}
        # 章内相对序必须成立：甲(1) < 乙(2) < 丙(3)
        assert by_title["甲"] < by_title["乙"] < by_title["丙"]
        # 且三条互不相同（章内不碰撞）
        assert len(set(by_title.values())) == 3

    async def test_cross_chapter_no_collision(self, extractor, mock_llm, mock_repo) -> None:
        """跨章不碰撞：两章各自从 1 编号，落库后合成序必须互不相同。"""
        mock_llm.chat.return_value = _ok_response(
            _payload([{"title": "章A事件", "narrative_position": 1, "timeline_flag": ""}])
        )
        await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID_A, text="t"),
            default_model=DEFAULT_MODEL,
        )
        first = mock_repo.add.await_args_list[0].args[0]

        mock_llm.chat.return_value = _ok_response(
            _payload([{"title": "章B事件", "narrative_position": 1, "timeline_flag": ""}])
        )
        await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID_B, text="t"),
            default_model=DEFAULT_MODEL,
        )
        second = mock_repo.add.await_args_list[1].args[0]

        # 两章的首个事件都是章内序 1 → 合成序必须不同（现实现落库都是 1 → COLLISION）
        assert first.narrative_position != second.narrative_position

    async def test_position_not_none_when_llm_gave_value(self, extractor, mock_llm) -> None:
        """合成序永不落 None（None 会让排序退化）。"""
        mock_llm.chat.return_value = _ok_response(
            _payload([{"title": "甲", "narrative_position": 2, "timeline_flag": ""}])
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID_A, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert result.created[0].narrative_position is not None
        assert result.created[0].narrative_position > 0


# ─────────────────────────── G6：标记包含式匹配 ───────────────────────────

SEQ_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
SEQ_TS = datetime(2026, 8, 1, 10, 0, 0)


class _FakeRepo:
    """内存版 repo（一致性检查用；镜像 test_timeline_check.py）。"""

    def __init__(self, events: list[TimelineEvent]) -> None:
        self._events = list(events)

    async def list_all(self, project_id: uuid.UUID) -> list[TimelineEvent]:
        return sorted(self._events, key=lambda e: (e.narrative_position, e.created_at))

    async def next_position(self, project_id: uuid.UUID) -> int:
        return max((e.narrative_position for e in self._events), default=0) + 1


class _FakeProjectRepo:
    def __init__(self, exists: bool = True) -> None:
        self._exists = exists

    async def get(self, project_id: uuid.UUID):
        if not self._exists:
            return None
        return object()


def _seq_event(title: str, time_value: float, position: int, flag: str) -> TimelineEvent:
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=SEQ_PID,
        title=title,
        time_value=time_value,
        time_display="",
        narrative_position=position,
        timeline_flag=flag,
        created_at=SEQ_TS,
        updated_at=SEQ_TS,
    )


def _service(events: list[TimelineEvent]) -> TimelineService:
    return TimelineService(repository=_FakeRepo(events), project_repo=_FakeProjectRepo())


class TestInclusiveFlagMatching:
    """G6：timeline_flag 是自由文本，真实数据为中文（倒叙/插叙）→ 必须包含式匹配。"""

    async def test_chinese_flashback_is_legal(self) -> None:
        """逆序对后叙事件标记「倒叙」→ 应判 flashback 合法（现实现当未标记 → order_conflict）。"""
        events = [
            _seq_event("前", 10.0, 1, ""),
            _seq_event("后", 5.0, 2, "倒叙"),
        ]
        report = await _service(events).check_consistency(SEQ_PID)
        # 已声明倒叙 → 合法，不进 conflicts
        assert [c.conflict_type for c in report.conflicts] == []
        assert len(report.flashbacks) == 1
        assert report.flashbacks[0].conflict_type == "flashback"
        assert report.consistent is True

    async def test_chinese_flashforward_is_legal(self) -> None:
        """逆序对前叙事件标记「插叙」→ 应判 flashforward 合法。"""
        events = [
            _seq_event("前", 10.0, 1, "插叙"),
            _seq_event("后", 5.0, 2, ""),
        ]
        report = await _service(events).check_consistency(SEQ_PID)
        assert [c.conflict_type for c in report.conflicts] == []
        assert len(report.flashbacks) == 1
        assert report.flashbacks[0].conflict_type == "flashforward"

    async def test_chinese_flag_with_qualifier_still_matches(self) -> None:
        """自由文本含修饰（如「倒叙（回忆片段）」）仍应命中包含式匹配。"""
        events = [
            _seq_event("前", 10.0, 1, ""),
            _seq_event("后", 5.0, 2, "倒叙（回忆片段）"),
        ]
        report = await _service(events).check_consistency(SEQ_PID)
        assert [c.conflict_type for c in report.conflicts] == []
        assert len(report.flashbacks) == 1

    async def test_english_flag_still_legal(self) -> None:
        """反向断言（守护「既有英文值测试零破坏」）：flashback/flashforward 仍合法。

        ⚠️ 本用例在修复前**本就是绿的** —— 这是正确的，别去改它。
        """
        back = await _service(
            [_seq_event("前", 10.0, 1, ""), _seq_event("后", 5.0, 2, "flashback")]
        ).check_consistency(SEQ_PID)
        assert [c.conflict_type for c in back.conflicts] == []
        assert len(back.flashbacks) == 1

        fwd = await _service(
            [_seq_event("前", 10.0, 1, "flashforward"), _seq_event("后", 5.0, 2, "")]
        ).check_consistency(SEQ_PID)
        assert [c.conflict_type for c in fwd.conflicts] == []
        assert len(fwd.flashbacks) == 1

    async def test_unrelated_flag_still_conflicts(self) -> None:
        """反向断言：与倒叙/插叙**无关**的自由文本（如「梦境」）不得被误判为已声明。"""
        events = [
            _seq_event("前", 10.0, 1, ""),
            _seq_event("后", 5.0, 2, "梦境"),
        ]
        report = await _service(events).check_consistency(SEQ_PID)
        assert [c.conflict_type for c in report.conflicts] == ["order_conflict"]
        assert report.flashbacks == []
