"""#1581 时间线提取「写前分流」——未定事件不入正式表（RED）。

被测（GREEN 才实现，spec 见 f12 §2.9 Z1-Z3 / f14 §5.5）：

- 提取事件 `time_value is None` 且 `time_display` **解析不出**值 → **不调用** `repo.add`
  （正式表零变更），并在 `TimelineExtractionResult.pending` 中连 **reason** 返回；
- `time_display` **可解析**（纪年式 / 序数 / 数量 / 月日）→ 后置归一填 `time_value`/`time_unit`
  后**正常落库**；`time_display` 原文原样保留；
- LLM 直接给出的 `time_value` **不被解析器覆盖**；
- `dry_run=True`（含 `stage=True`）**行为不变**（全部 would-be 新建进 `created`、`pending` 空）。

RED 预期：`TimelineExtractionResult` 无 `pending` 字段 → 断言 AttributeError（FAIL）。

依据: specs/f12-timeline/spec.md §2.9；specs/f14-extraction/spec.md §5.5 / §5.9。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.timeline import TimelineExtractRequest
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services._timeline_extractor import TimelineExtractor

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
DEFAULT_MODEL = "openai/gpt-4o"


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
        return_value=RenderedPrompt(messages=[{"role": "user", "content": "t"}], token_estimate=1)
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.list_by_chapter = AsyncMock(return_value=[])
    repo.add = AsyncMock(side_effect=lambda e: e)
    repo.update = AsyncMock(side_effect=lambda e: e)
    repo.next_position = AsyncMock(return_value=1)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_prompt_manager, mock_repo) -> TimelineExtractor:
    return TimelineExtractor(
        llm_client=mock_llm, prompt_manager=mock_prompt_manager, timeline_repo=mock_repo
    )


def _req() -> TimelineExtractRequest:
    return TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t")


async def test_undetermined_event_is_not_written_and_lands_in_pending(
    extractor, mock_llm, mock_repo
) -> None:
    """解析不出时间的条目：正式表零变更 + 进 pending（连 reason，原文保留）。"""
    mock_llm.chat.return_value = ChatResponse(
        content=_payload(
            [
                {
                    "title": "未定事件",
                    "description": "d",
                    "time_display": "那年冬天",
                    "time_value": None,
                    "narrative_position": 1,
                    "timeline_flag": "",
                }
            ]
        ),
        model=DEFAULT_MODEL,
    )

    result = await extractor.extract(_req(), default_model=DEFAULT_MODEL)

    assert result.created == []
    assert mock_repo.add.await_count == 0
    assert len(result.pending) == 1
    pending = result.pending[0]
    assert pending.event.title == "未定事件"
    assert pending.event.time_display == "那年冬天"  # 原文永不留失
    assert pending.event.time_unit == ""  # 不变式：无 value 不得有 unit
    assert pending.reason.strip() != ""  # 禁止静默丢弃


async def test_parseable_time_display_is_normalized_then_written(
    extractor, mock_llm, mock_repo
) -> None:
    """可解析的 time_display → 后置归一填值后正常落库（原文保留）。"""
    mock_llm.chat.return_value = ChatResponse(
        content=_payload(
            [
                {
                    "title": "可解析事件",
                    "time_display": "三年",
                    "time_value": None,
                    "narrative_position": 1,
                    "timeline_flag": "",
                }
            ]
        ),
        model=DEFAULT_MODEL,
    )

    result = await extractor.extract(_req(), default_model=DEFAULT_MODEL)

    assert result.pending == []
    assert len(result.created) == 1
    created = result.created[0]
    assert created.time_value == 3.0
    assert created.time_unit == "年"
    assert created.time_display == "三年"
    assert mock_repo.add.await_count == 1


async def test_llm_time_value_wins_over_parser(extractor, mock_llm, mock_repo) -> None:
    """LLM 已给 time_value → 解析器不覆盖（只在缺失时补）。"""
    mock_llm.chat.return_value = ChatResponse(
        content=_payload(
            [
                {
                    "title": "已给值",
                    "time_display": "第七天",
                    "time_value": 7.0,
                    "time_unit": "日",
                    "narrative_position": 1,
                    "timeline_flag": "",
                }
            ]
        ),
        model=DEFAULT_MODEL,
    )

    result = await extractor.extract(_req(), default_model=DEFAULT_MODEL)

    assert len(result.created) == 1
    assert (result.created[0].time_value, result.created[0].time_unit) == (7.0, "日")
    assert result.pending == []


async def test_dry_run_keeps_all_in_created_and_pending_empty(
    extractor, mock_llm, mock_repo
) -> None:
    """dry_run（stage 预览）行为不变：全部 would-be 新建进 created、pending 空。"""
    mock_llm.chat.return_value = ChatResponse(
        content=_payload(
            [
                {
                    "title": "未定事件",
                    "time_display": "那年冬天",
                    "time_value": None,
                    "narrative_position": 1,
                    "timeline_flag": "",
                }
            ]
        ),
        model=DEFAULT_MODEL,
    )

    result = await extractor.extract(_req(), default_model=DEFAULT_MODEL, dry_run=True)

    assert len(result.created) == 1
    assert result.pending == []
    assert mock_repo.add.await_count == 0
