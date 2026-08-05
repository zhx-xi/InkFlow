"""F14 伏笔提取管线单元测试 — Mock LLM + Mock PromptManager + Mock Repo.

覆盖 spec §5.4「伏笔提取管线」全部场景:
合法 JSON 全量落库 / 同名活动伏笔非空覆盖且 status 不重置 / 软删同名新建 /
非法条目跳过 / 围栏输出 / 修复重试与异常 / 幂等性 / 模板与模型参数断言。

依据: specs/f14-extraction-service/spec.md §5.4 + §9 测试策略。
镜像 F9 test_character_extraction.py 测试模式。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingExtractionResult,
    ForeshadowingExtractRequest,
    ForeshadowingStatus,
)
from inkflow.domain.ports.foreshadowing_errors import ForeshadowingExtractionError
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._foreshadowing_extractor import (
    ForeshadowingExtractor,
    _extract_json_fragment,
    _first_error,
    _to_int_id,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _fs(
    title: str,
    *,
    description: str = "",
    location: str = "",
    status: ForeshadowingStatus = ForeshadowingStatus.OPEN,
    priority: int = 50,
    event_id: uuid.UUID | None = None,
    is_deleted: bool = False,
) -> Foreshadowing:
    """构造测试用伏笔实体（默认时间戳固定，便于断言）。"""
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        description=description,
        priority=priority,
        status=status,
        location=location,
        event_id=event_id,
        is_deleted=is_deleted,
        created_at=TS,
        updated_at=TS,
    )


def _payload(items: list[dict] | None = None) -> str:
    """构造合法提取 JSON 输出。"""
    return json.dumps({"foreshadowings": items or []}, ensure_ascii=False)


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
        name="foreshadowing_extract",
        description="Foreshadowing extraction template",
        system_prompt="你是小说伏笔提取器。输出严格 JSON。",
        human_prompt="章节文本：\n{text}",
        variables=["text"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说伏笔提取器。输出严格 JSON。"},
                {"role": "user", "content": "章节文本：\n测试文本"},
            ],
            token_estimate=50,
        )
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=ForeshadowingRepositoryProtocol)
    repo.get_by_title = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda f: f)
    repo.update = AsyncMock(side_effect=lambda f: f)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_prompt_manager, mock_repo) -> ForeshadowingExtractor:
    return ForeshadowingExtractor(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        foreshadowing_repo=mock_repo,
    )


class TestForeshadowingExtractor:
    """伏笔提取管线测试 — 解析 / 重试 / 合并 / 幂等（Mock LLM）。"""

    async def test_valid_json_creates_foreshadowings(self, extractor, mock_llm, mock_repo) -> None:
        """合法 JSON → 全部落库，created 计数正确、默认字段合规。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                [
                    {
                        "title": "铜镜的秘密",
                        "description": "古镜能映出亡者身影",
                        "location": "第 5 章·林晚沐浴场景",
                    },
                    {"title": "玉佩的裂痕", "description": "", "location": ""},
                ]
            )
        )
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="章节文本"),
            default_model=DEFAULT_MODEL,
        )
        assert isinstance(result, ForeshadowingExtractionResult)
        assert len(result.created) == 2
        assert result.updated == []
        assert result.warnings == []
        assert result.model == DEFAULT_MODEL
        assert mock_repo.add.await_count == 2
        assert {f.title for f in result.created} == {"铜镜的秘密", "玉佩的裂痕"}
        first = next(f for f in result.created if f.title == "铜镜的秘密")
        assert first.description == "古镜能映出亡者身影"
        assert first.location == "第 5 章·林晚沐浴场景"
        assert first.priority == 50
        assert first.status == ForeshadowingStatus.OPEN
        assert first.event_id is None
        assert first.is_deleted is False

    async def test_fenced_output_extracts_json_fragment(self, extractor, mock_llm) -> None:
        """输出带围栏/前后缀文字 → _extract_json_fragment 提取成功。"""
        payload = _payload([{"title": "铜镜的秘密"}])
        fenced = f"好的，以下是提取结果：\n```json\n{payload}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        assert result.created[0].title == "铜镜的秘密"

    async def test_invalid_json_retries_once_then_succeeds(self, extractor, mock_llm) -> None:
        """第一次非法 JSON → 修复重试 1 次（第二次合法）→ 成功。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="这不是 JSON", model=DEFAULT_MODEL),
            _ok_response(_payload([{"title": "铜镜的秘密"}])),
        ]
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert mock_llm.chat.await_count == 2
        assert len(result.created) == 1
        # 第 2 次调用携带修复 Prompt: assistant(原输出) + user(只输出 JSON)
        call2_msgs = mock_llm.chat.await_args_list[1].args[0]
        assert call2_msgs[-2].role == "assistant"
        assert call2_msgs[-2].content == "这不是 JSON"
        assert call2_msgs[-1].role == "user"
        assert "只输出 JSON" in call2_msgs[-1].content

    async def test_retries_exhausted_raises_with_truncated_raw_output(
        self, extractor, mock_llm
    ) -> None:
        """重试仍失败（共 3 次调用）→ ForeshadowingExtractionError，raw_output 截断 500。"""
        long_output = "x" * 600
        mock_llm.chat.side_effect = [
            ChatResponse(content="坏输出 1", model=DEFAULT_MODEL),
            ChatResponse(content="坏输出 2", model=DEFAULT_MODEL),
            ChatResponse(content=long_output, model=DEFAULT_MODEL),
        ]
        with pytest.raises(ForeshadowingExtractionError) as excinfo:
            await extractor.extract(
                ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )
        assert mock_llm.chat.await_count == 3
        assert len(excinfo.value.raw_output) == 500
        assert excinfo.value.raw_output == "x" * 500
        assert "无法解析" in str(excinfo.value)

    async def test_invalid_entries_skipped_with_warning(self, extractor, mock_llm) -> None:
        """非法条目（title 空/超长）→ 跳过 + warning，其余正常落库。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                [
                    {"title": ""},
                    {"title": "长" * 101},
                    {"title": "铜镜的秘密", "description": "古镜能映出亡者", "location": "第 5 章"},
                ]
            )
        )
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        assert result.created[0].title == "铜镜的秘密"
        assert len(result.warnings) == 2
        assert all("跳过非法伏笔条目" in w for w in result.warnings)

    async def test_same_title_active_overrides_non_empty_keeps_status(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """同名活动伏笔 → 非空字段覆盖（description/location 独立判断），status 不重置。"""
        event_id = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
        existing = _fs(
            "铜镜的秘密",
            description="旧描述",
            location="旧位置",
            status=ForeshadowingStatus.RESOLVED,
            priority=80,
            event_id=event_id,
        )
        mock_repo.get_by_title = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _payload([{"title": "铜镜的秘密", "description": "新描述", "location": ""}])
        )
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.created == []
        assert len(result.updated) == 1
        merged = result.updated[0]
        assert merged.id == existing.id
        assert merged.description == "新描述"  # 非空覆盖
        assert merged.location == "旧位置"  # 空串不覆盖
        assert merged.status == ForeshadowingStatus.RESOLVED  # status 不重置
        assert merged.priority == 80
        assert merged.event_id == event_id
        assert merged.created_at == TS
        assert mock_repo.update.await_count == 1
        assert mock_repo.add.await_count == 0

    async def test_same_title_location_only_update(self, extractor, mock_llm, mock_repo) -> None:
        """同名活动伏笔 → 仅 location 非空时只更新 location，description 保留。"""
        existing = _fs("铜镜的秘密", description="旧描述", location="旧位置")
        mock_repo.get_by_title = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _payload([{"title": "铜镜的秘密", "description": None, "location": "第 9 章·密室"}])
        )
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        merged = result.updated[0]
        assert merged.description == "旧描述"  # None 不覆盖
        assert merged.location == "第 9 章·密室"
        assert mock_repo.update.await_count == 1

    async def test_soft_deleted_same_title_creates_new_with_warning(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """软删同名 → 新建伏笔 + warning（不隐式恢复旧档案）。"""
        deleted = _fs("铜镜的秘密", description="旧档案", is_deleted=True)
        mock_repo.list = AsyncMock(return_value=([deleted], 1))
        mock_llm.chat.return_value = _ok_response(_payload([{"title": "铜镜的秘密"}]))
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        assert result.created[0].title == "铜镜的秘密"
        assert result.created[0].is_deleted is False
        assert mock_repo.add.await_count == 1
        assert any("已删除" in w for w in result.warnings)

    async def test_idempotent_second_extraction_produces_empty(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """幂等性: 同一文本二次提取 → 空 created/updated，零写入。"""
        payload = _payload(
            [
                {"title": "铜镜的秘密", "description": "古镜能映出亡者", "location": "第 5 章"},
                {"title": "玉佩的裂痕", "description": "裂痕在扩大", "location": ""},
            ]
        )
        mock_llm.chat.return_value = _ok_response(payload)
        req = ForeshadowingExtractRequest(project_id=PID, text="t")
        await extractor.extract(req, default_model=DEFAULT_MODEL)
        assert mock_repo.add.await_count == 2

        # 第二轮: 同名伏笔均已存在且字段一致
        by_title = {
            "铜镜的秘密": _fs("铜镜的秘密", description="古镜能映出亡者", location="第 5 章"),
            "玉佩的裂痕": _fs("玉佩的裂痕", description="裂痕在扩大"),
        }

        async def _get_by_title(pid: int, title: str) -> Foreshadowing | None:
            return by_title.get(title)

        mock_repo.get_by_title = AsyncMock(side_effect=_get_by_title)

        result2 = await extractor.extract(req, default_model=DEFAULT_MODEL)
        assert result2.created == []
        assert result2.updated == []
        assert mock_repo.add.await_count == 2  # 第二轮无新建
        assert mock_repo.update.await_count == 0

    async def test_empty_foreshadowings_warns(self, extractor, mock_llm) -> None:
        """空伏笔列表 → 空结果 + warning。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.created == []
        assert result.updated == []
        assert len(result.warnings) == 1
        assert "未从文本中提取" in result.warnings[0]

    async def test_uses_template_default_model_and_temperature(
        self, extractor, mock_llm, mock_prompt_manager
    ) -> None:
        """断言使用 foreshadowing_extract 模板 + 变量 text + 默认模型 + temperature 0.2。"""
        mock_llm.chat.return_value = _ok_response(_payload([{"title": "铜镜的秘密"}]))
        await extractor.extract(
            ForeshadowingExtractRequest(project_id=PID, text="第一章文本"),
            default_model=DEFAULT_MODEL,
        )
        mock_prompt_manager.load.assert_called_once_with("foreshadowing_extract")
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
            ForeshadowingExtractRequest(project_id=PID, text="t", model="deepseek/deepseek-chat"),
            default_model=DEFAULT_MODEL,
        )
        assert mock_llm.chat.await_args.kwargs["model"] == "deepseek/deepseek-chat"
        assert result.model == "deepseek/deepseek-chat"

    async def test_llm_error_propagates_without_retry(self, extractor, mock_llm) -> None:
        """Mock LLM 抛 LLMRequestError → 透传，不消耗解析重试。"""
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        with pytest.raises(LLMRequestError):
            await extractor.extract(
                ForeshadowingExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )
        assert mock_llm.chat.await_count == 1


class TestForeshadowingExtractorHelpers:
    """模块级纯函数测试（_to_int_id / _first_error）。"""

    def test_to_int_id_passthrough_for_int(self) -> None:
        """int 输入原样返回（非 UUID 分支）。"""
        assert _to_int_id(42) == 42

    def test_first_error_with_empty_errors_returns_str(self) -> None:
        """errors() 为空 → 回退 str(err)。"""
        err = ValidationError.from_exception_data("测试", line_errors=[])
        assert _first_error(err) == str(err)

    # ── _parse_output 结构级错误分支 ──────────────────────────────

    def test_malformed_json_syntax_returns_syntax_error(self, extractor) -> None:
        """括号平衡但语法非法 → JSON 语法错误（json.JSONDecodeError 分支）。"""
        outcome = extractor._parse_output('{"foreshadowings": }')
        assert not outcome.ok
        assert "JSON 语法错误" in outcome.error

    def test_foreshadowings_not_list_returns_structure_error(self, extractor) -> None:
        """foreshadowings 字段非列表 → 结构错误。"""
        outcome = extractor._parse_output('{"foreshadowings": "x"}')
        assert outcome.error == "缺少 foreshadowings 列表"


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
