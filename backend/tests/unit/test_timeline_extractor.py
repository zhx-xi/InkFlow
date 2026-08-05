"""F14 时间线提取管线单元测试 — Mock LLM + Mock PromptManager + Mock TimelineRepo.

覆盖 spec §5.5（时间线提取管线，Q2 拍板）+ §9 测试策略「提取（Mock LLM，
遵循 ADR-015）」全部场景:
合法 JSON 全量落库 / 同名同章更新与幂等性 / None 未知值不覆盖 / 空串明确
值覆盖 / 软删同名同章新建 + warning / 非法条目跳过 / 围栏输出 / 修复重试与
异常透传 / 空条目列表 / 模板与模型参数断言 / narrative_position=None 走
next_position 追加语义。

实现镜像 F10 test_world_extraction.py（同 F9 test_character_extraction.py
骨架），仅替换领域实体（TimelineEvent ↔ WorldSetting）、合并匹配键
（(project_id, title, source_chapter_id) ↔ (project_id, name)）与模板名
（timeline_extract ↔ world_extract）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.timeline import (
    ExtractedTimelineEvent,
    TimelineEvent,
    TimelineExtractRequest,
)
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.timeline_errors import TimelineExtractionError
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services._timeline_extractor import (
    TimelineExtractor,
    _extract_json_fragment,
    _first_error,
    _to_int_id,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
DEFAULT_MODEL = "openai/gpt-4o"


def _event(
    title: str,
    *,
    description: str = "",
    time_value: float | None = None,
    time_unit: str = "",
    narrative_position: int = 1,
    timeline_flag: str = "",
    is_deleted: bool = False,
    source_chapter_id: uuid.UUID | None = CID,
) -> TimelineEvent:
    """构造测试用时间线事件实体（默认时间戳固定，便于断言）。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        description=description,
        time_value=time_value,
        time_unit=time_unit,
        time_display="",
        narrative_position=narrative_position,
        timeline_flag=timeline_flag,
        source_chapter_id=source_chapter_id,
        is_deleted=is_deleted,
        created_at=TS,
        updated_at=TS,
    )


def _payload(events: list[dict] | None = None) -> str:
    """构造合法提取 JSON 输出（events 键）。"""
    return json.dumps({"events": events or []}, ensure_ascii=False)


def _ok_response(payload: str) -> ChatResponse:
    return ChatResponse(content=payload, model=DEFAULT_MODEL)


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    pm = MagicMock(spec=PromptTemplateProtocol)
    template = PromptTemplate(
        name="timeline_extract",
        description="Timeline extraction template",
        system_prompt="你是小说时间线事件提取器。输出严格 JSON。",
        human_prompt="章节文本：\n{text}",
        variables=["text"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说时间线事件提取器。输出严格 JSON。"},
                {"role": "user", "content": "章节文本：\n测试文本"},
            ],
            token_estimate=50,
        )
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.list_by_chapter = AsyncMock(return_value=[])
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda e: e)
    repo.update = AsyncMock(side_effect=lambda e: e)
    repo.next_position = AsyncMock(return_value=1)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_prompt_manager, mock_repo) -> TimelineExtractor:
    return TimelineExtractor(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        timeline_repo=mock_repo,
    )


class TestTimelineExtractor:
    """提取管线测试 — 解析 / 重试 / 合并 / 幂等（Mock LLM）。"""

    async def test_valid_json_creates_events(self, extractor, mock_llm, mock_repo) -> None:
        """合法 JSON → 全部落库，created 计数正确、source_chapter_id=当前章。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                events=[
                    {
                        "title": "林晚入宫",
                        "description": "入宫为妃",
                        "time_value": 3.5,
                        "time_unit": "年",
                        "narrative_position": 1,
                        "timeline_flag": "",
                    },
                    {
                        "title": "宫变",
                        "time_value": 4.0,
                        "narrative_position": 2,
                        "timeline_flag": "flashback",
                    },
                ]
            )
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.created) == 2
        assert result.created[0].title == "林晚入宫"
        assert result.created[0].description == "入宫为妃"
        assert result.created[0].time_value == 3.5
        assert result.created[0].source_chapter_id == CID
        assert result.created[1].timeline_flag == "flashback"
        assert result.updated == []
        assert mock_repo.add.await_count == 2
        # 每个提取事件各拉取一次同章候选集（按 title 比对在服务层完成）
        mock_repo.list_by_chapter.assert_awaited_with(PID.int, CID.int)
        # narrative_position 均有 LLM 输出 → 不调 next_position
        mock_repo.next_position.assert_not_awaited()

    async def test_existing_same_title_same_chapter_updated(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """list_by_chapter 命中同 title 活动事件 → 非空字段覆盖，计入 updated。"""
        mock_repo.list_by_chapter.return_value = [
            _event("林晚入宫", description="旧描述", time_value=1.0, narrative_position=2)
        ]
        mock_llm.chat.return_value = _ok_response(
            _payload(
                events=[
                    {
                        "title": "林晚入宫",
                        "description": "新描述",
                        "time_value": 3.5,
                        "time_unit": "年",
                        "narrative_position": 3,
                        "timeline_flag": "flashback",
                    }
                ]
            )
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert result.created == []
        assert len(result.updated) == 1
        merged = result.updated[0]
        assert merged.title == "林晚入宫"
        assert merged.description == "新描述"
        assert merged.time_value == 3.5
        assert merged.time_unit == "年"
        assert merged.narrative_position == 3
        assert merged.timeline_flag == "flashback"
        assert merged.source_chapter_id == CID
        assert mock_repo.add.await_count == 0
        mock_repo.update.assert_awaited_once()

    async def test_none_fields_do_not_overwrite(self, extractor, mock_llm, mock_repo) -> None:
        """提取字段 None = 未知/不覆盖 → 保留库中原值（独立判断）。"""
        mock_repo.list_by_chapter.return_value = [
            _event(
                "宫变",
                description="保留描述",
                time_value=4.0,
                time_unit="年",
                narrative_position=2,
                timeline_flag="flashback",
            )
        ]
        mock_llm.chat.return_value = _ok_response(
            _payload(events=[{"title": "宫变", "time_value": 5.0}])
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.updated) == 1
        merged = result.updated[0]
        assert merged.description == "保留描述"  # None 不覆盖
        assert merged.time_unit == "年"  # None 不覆盖
        assert merged.narrative_position == 2  # None 不覆盖
        assert merged.timeline_flag == "flashback"  # None 不覆盖
        assert merged.time_value == 5.0  # 非 None 覆盖

    async def test_empty_string_is_explicit_value_overwrites(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """空字符串 = 明确值（如 timeline_flag="" = 明确无标记）→ 照常覆盖。"""
        mock_repo.list_by_chapter.return_value = [
            _event("宫变", description="旧描述", time_unit="年", timeline_flag="flashback")
        ]
        mock_llm.chat.return_value = _ok_response(
            _payload(
                events=[{"title": "宫变", "description": "", "time_unit": "", "timeline_flag": ""}]
            )
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.updated) == 1
        merged = result.updated[0]
        assert merged.description == ""
        assert merged.time_unit == ""
        assert merged.timeline_flag == ""

    async def test_missing_creates_with_next_position(self, extractor, mock_llm, mock_repo) -> None:
        """narrative_position=None → 调 repo.next_position（F12 追加语义）。"""
        mock_repo.next_position.return_value = 7
        mock_llm.chat.return_value = _ok_response(
            _payload(events=[{"title": "新事件", "narrative_position": None}])
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.created) == 1
        assert result.created[0].narrative_position == 7
        mock_repo.next_position.assert_awaited_once_with(PID.int)

    async def test_soft_deleted_same_title_creates_with_warning(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """软删同名同章 → 视为不存在 → 新建 + warning。"""
        mock_repo.list.return_value = (
            [_event("旧事件", is_deleted=True)],
            1,
        )
        mock_llm.chat.return_value = _ok_response(
            _payload(events=[{"title": "旧事件", "time_value": 2.0}])
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.created) == 1
        assert result.created[0].source_chapter_id == CID
        assert any("已删除" in w for w in result.warnings)

    async def test_idempotent_second_extract(self, extractor, mock_llm, mock_repo) -> None:
        """同文本二次提取 → 全部命中已有事件且非空覆盖无变化 → 空 created/updated。"""
        existing = _event(
            "林晚入宫",
            description="入宫为妃",
            time_value=3.5,
            time_unit="年",
            narrative_position=1,
            timeline_flag="",
        )
        mock_repo.list_by_chapter.return_value = [existing]
        payload = _payload(
            events=[
                {
                    "title": "林晚入宫",
                    "description": "入宫为妃",
                    "time_value": 3.5,
                    "time_unit": "年",
                    "narrative_position": 1,
                    "timeline_flag": "",
                }
            ]
        )
        mock_llm.chat.return_value = _ok_response(payload)
        request = TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t")
        first = await extractor.extract(request, default_model=DEFAULT_MODEL)
        assert first.created == []
        assert first.updated == []  # 与库中事件完全一致 → 幂等跳过
        # 模拟第二次提取（库中事件不变）
        mock_llm.chat.reset_mock()
        mock_llm.chat.return_value = _ok_response(payload)
        mock_repo.update.reset_mock()
        second = await extractor.extract(request, default_model=DEFAULT_MODEL)
        assert second.created == []
        assert second.updated == []
        mock_repo.update.assert_not_awaited()

    async def test_invalid_entries_skipped_with_warning(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """非法条目（title 空/超长、time_value 越界、time_unit 超长、
        narrative_position 负数、timeline_flag 超长）→ 跳过 + warning，其余正常落库。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                events=[
                    {"title": ""},
                    {"title": "长" * 101},
                    {"title": "时间越界", "time_value": 1e12 + 1},
                    {"title": "单位超长", "time_unit": "年" * 21},
                    {"title": "位置负数", "narrative_position": -1},
                    {"title": "标记超长", "timeline_flag": "x" * 21},
                    {"title": "合法事件", "time_value": 3.5, "narrative_position": 1},
                ]
            )
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.created) == 1
        assert result.created[0].title == "合法事件"
        assert len(result.warnings) == 6  # 6 非法条目
        assert all("跳过" in w for w in result.warnings)

    async def test_fenced_output_extracts_json_fragment(self, extractor, mock_llm) -> None:
        """输出带围栏/前后缀文字 → _extract_json_fragment 提取成功。"""
        payload = _payload(events=[{"title": "林晚入宫"}])
        fenced = f"好的，以下是提取结果：\n```json\n{payload}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.created) == 1
        assert result.created[0].title == "林晚入宫"

    async def test_invalid_output_retries_twice_then_raises(self, extractor, mock_llm) -> None:
        """输出完全非法 → 修复重试 2 次（共 3 次调用）→ TimelineExtractionError。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="这不是 JSON", model=DEFAULT_MODEL),
            ChatResponse(content="还是不对", model=DEFAULT_MODEL),
            ChatResponse(content="依然失败", model=DEFAULT_MODEL),
        ]
        with pytest.raises(TimelineExtractionError) as excinfo:
            await extractor.extract(
                TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
                default_model=DEFAULT_MODEL,
            )
        assert mock_llm.chat.await_count == 3
        assert excinfo.value.raw_output == "依然失败"
        # 第 2 次调用携带修复 Prompt: assistant(原输出) + user(只输出 JSON)
        call2_msgs = mock_llm.chat.await_args_list[1].args[0]
        assert call2_msgs[-2].role == "assistant"
        assert call2_msgs[-2].content == "这不是 JSON"
        assert call2_msgs[-1].role == "user"
        assert "只输出 JSON" in call2_msgs[-1].content
        # 第 3 次调用保留完整对话历史
        call3_msgs = mock_llm.chat.await_args_list[2].args[0]
        assert call3_msgs[-2].content == "还是不对"

    async def test_llm_error_propagates_without_retry(self, extractor, mock_llm) -> None:
        """Mock LLM 抛 LLMRequestError → 透传，不消耗解析重试。"""
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        with pytest.raises(LLMRequestError):
            await extractor.extract(
                TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
                default_model=DEFAULT_MODEL,
            )
        assert mock_llm.chat.await_count == 1

    async def test_llm_error_after_bad_output_propagates(self, extractor, mock_llm) -> None:
        """坏输出后 LLM 报错 → 立即透传，不进入第 3 次尝试。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="bad", model=DEFAULT_MODEL),
            LLMRequestError("timeout"),
        ]
        with pytest.raises(LLMRequestError):
            await extractor.extract(
                TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
                default_model=DEFAULT_MODEL,
            )
        assert mock_llm.chat.await_count == 2

    async def test_empty_events_warns(self, extractor, mock_llm) -> None:
        """空条目列表 → 空结果 + warning。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert result.created == []
        assert result.updated == []
        assert len(result.warnings) == 1
        assert "未从文本中提取" in result.warnings[0]

    async def test_uses_template_default_model_and_temperature(
        self, extractor, mock_llm, mock_prompt_manager
    ) -> None:
        """断言使用 timeline_extract 模板 + 变量 text + 默认模型 + temperature 0.2。"""
        mock_llm.chat.return_value = _ok_response(_payload(events=[{"title": "林晚入宫"}]))
        await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="第一章文本"),
            default_model=DEFAULT_MODEL,
        )
        mock_prompt_manager.load.assert_called_once_with("timeline_extract")
        template = mock_prompt_manager.load.return_value
        mock_prompt_manager.render.assert_called_once_with(template, {"text": "第一章文本"})
        kwargs = mock_llm.chat.await_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["temperature"] == 0.2
        msgs = mock_llm.chat.await_args.args[0]
        assert msgs[0].role == "system"
        assert msgs[-1].role == "user"

    async def test_request_model_overrides_default(self, extractor, mock_llm) -> None:
        """request.model 覆盖项目默认模型。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await extractor.extract(
            TimelineExtractRequest(
                project_id=PID, chapter_id=CID, text="t", model="deepseek/deepseek-chat"
            ),
            default_model=DEFAULT_MODEL,
        )
        assert mock_llm.chat.await_args.kwargs["model"] == "deepseek/deepseek-chat"
        assert result.model == "deepseek/deepseek-chat"

    # ── _parse_output 结构级错误分支 ──────────────────────────────

    def test_malformed_json_syntax_returns_syntax_error(self, extractor) -> None:
        """括号平衡但语法非法 → JSON 语法错误（json.JSONDecodeError 分支）。"""
        outcome = extractor._parse_output('{"events": }')
        assert not outcome.ok
        assert "JSON 语法错误" in outcome.error

    def test_events_not_list_returns_structure_error(self, extractor) -> None:
        """events 字段非列表 → 结构错误。"""
        outcome = extractor._parse_output('{"events": 3}')
        assert outcome.error == "缺少 events 列表"

    async def test_no_title_match_in_chapter_creates_new(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """同章候选集非空但 title 均不匹配 → 遍历结束仍判不存在 → 新建（匹配 False 分支）。"""
        mock_repo.list_by_chapter.return_value = [_event("另一事件", description="旧描述")]
        mock_llm.chat.return_value = _ok_response(
            _payload(events=[{"title": "林晚入宫", "time_value": 2.0}])
        )
        result = await extractor.extract(
            TimelineExtractRequest(project_id=PID, chapter_id=CID, text="t"),
            default_model=DEFAULT_MODEL,
        )
        assert len(result.created) == 1
        assert result.created[0].title == "林晚入宫"
        assert result.updated == []
        mock_repo.add.assert_awaited_once()


class TestTimelineExtractorHelpers:
    """模块级纯函数测试（_to_int_id / _first_error）。"""

    def test_to_int_id_passthrough_for_int(self) -> None:
        """int 输入原样返回（非 UUID 分支）。"""
        assert _to_int_id(42) == 42

    def test_first_error_with_empty_errors_returns_str(self) -> None:
        """errors() 为空 → 回退 str(err)。"""
        err = ValidationError.from_exception_data("测试", line_errors=[])
        assert _first_error(err) == str(err)


class TestExtractedTimelineEventSchema:
    """ExtractedTimelineEvent schema 校验（§5.5 字段级规则）。"""

    def test_title_required_and_stripped(self) -> None:
        """title 必填且去空白。"""
        with pytest.raises(ValidationError):
            ExtractedTimelineEvent.model_validate({"time_value": 1.0})
        ev = ExtractedTimelineEvent.model_validate({"title": "  林晚入宫  "})
        assert ev.title == "林晚入宫"

    def test_title_too_long_invalid(self) -> None:
        """title 超 100 字符 → 非法。"""
        with pytest.raises(ValidationError):
            ExtractedTimelineEvent.model_validate({"title": "长" * 101})

    def test_time_value_out_of_range_invalid(self) -> None:
        """time_value |v| > 1e12 → 非法；None 合法。"""
        with pytest.raises(ValidationError):
            ExtractedTimelineEvent.model_validate({"title": "t", "time_value": 1e12 + 1})
        ev = ExtractedTimelineEvent.model_validate({"title": "t", "time_value": None})
        assert ev.time_value is None

    def test_optional_fields_default_none(self) -> None:
        """description/time_unit/narrative_position/timeline_flag 默认 None。"""
        ev = ExtractedTimelineEvent.model_validate({"title": "t"})
        assert ev.description is None
        assert ev.time_value is None
        assert ev.time_unit is None
        assert ev.narrative_position is None
        assert ev.timeline_flag is None


class TestExtractJsonFragment:
    """_extract_json_fragment 纯函数测试。"""

    def test_balanced_nested_with_braces_in_string(self) -> None:
        """嵌套括号与字符串内花括号均正确处理。"""
        text = '前缀 {"a": {"b": [1, 2]}, "c": "}"} 后缀'
        assert _extract_json_fragment(text) == '{"a": {"b": [1, 2]}, "c": "}"}'

    def test_unbalanced_or_absent_returns_none(self) -> None:
        """无花括号或括号不平衡 → None。"""
        assert _extract_json_fragment("纯文本输出") is None
        assert _extract_json_fragment('{"a": 1') is None

    def test_escaped_quotes_inside_string(self) -> None:
        """字符串字面量内的转义引号不提前闭合字符串（escaped 状态机分支）。"""
        text = '{"msg": "他说 \\"你好\\""}'
        assert _extract_json_fragment(text) == text
