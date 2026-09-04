"""F10 世界观提取管线单元测试 — Mock LLM + Mock PromptManager + Mock Repo.

覆盖 spec §9「提取（Mock LLM，遵循 ADR-015）」全部场景:
合法 JSON 全量落库 / 同名更新与幂等性 / 软删同名新建 / 非法条目跳过 /
围栏输出 / 修复重试与异常透传 / 空条目列表 / 模板与模型参数断言。

依据: specs/f10-world-settings/spec.md §5（AI 提取模式，同 F9 §5）+
§9 测试策略。实现镜像 F9 test_character_extraction.py，仅替换领域实体
（WorldSetting ↔ Character）与模板名（world_extract ↔ character_extract）。

"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.world import (
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
)
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.world_errors import WorldExtractionError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._world_extractor import (
    WorldExtractor,
    _extract_json_fragment,
    _first_error,
    _to_int_id,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _setting(
    name: str,
    *,
    category: str = "",
    content: str = "",
) -> WorldSetting:
    """构造测试用世界观条目实体（默认时间戳固定，便于断言）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        category=category,
        content=content,
        created_at=TS,
        updated_at=TS,
    )


def _payload(settings: list[dict] | None = None) -> str:
    """构造合法提取 JSON 输出（world_settings 键）。"""
    return json.dumps({"world_settings": settings or []}, ensure_ascii=False)


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
        name="world_extract",
        description="World extraction template",
        system_prompt="你是小说世界观信息提取器。输出严格 JSON。",
        human_prompt="章节文本：\n{text}",
        variables=["text"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说世界观信息提取器。输出严格 JSON。"},
                {"role": "user", "content": "章节文本：\n测试文本"},
            ],
            token_estimate=50,
        )
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.update = AsyncMock(side_effect=lambda s: s)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_prompt_manager, mock_repo) -> WorldExtractor:
    return WorldExtractor(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        repository=mock_repo,
    )


class TestWorldExtractor:
    """提取管线测试 — 解析 / 重试 / 合并 / 幂等（Mock LLM）。"""

    async def test_valid_json_creates_world_settings(self, extractor, mock_llm, mock_repo) -> None:
        """合法 JSON → 全部落库，created 计数正确。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                settings=[
                    {
                        "name": "灵气复苏",
                        "category": "设定",
                        "content": "天地灵气重新活跃，凡人可修行",
                    },
                    {
                        "name": "宗门等级",
                        "category": "规则",
                        "content": "宗门分下品、中品、上品三等",
                    },
                ]
            )
        )
        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="章节文本"), default_model=DEFAULT_MODEL
        )
        assert isinstance(result, WorldExtractionResult)
        assert len(result.created) == 2
        assert result.updated == []
        assert result.warnings == []
        assert result.model == DEFAULT_MODEL
        assert mock_repo.add.await_count == 2
        assert {s.name for s in result.created} == {"灵气复苏", "宗门等级"}
        by_name = {s.name: s for s in result.created}
        assert by_name["灵气复苏"].category == "设定"
        assert by_name["宗门等级"].content == "宗门分下品、中品、上品三等"

    async def test_updates_existing_same_name_non_empty_override(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """同名已存在 → 更新（非空字段覆盖，空值不覆盖），计入 updated。"""
        existing = _setting(name="灵气复苏", category="旧类别", content="旧内容")
        mock_repo.get_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _payload(settings=[{"name": "灵气复苏", "category": "设定", "content": ""}])
        )
        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.created == []
        assert len(result.updated) == 1
        merged = result.updated[0]
        assert merged.category == "设定"  # 非空覆盖
        assert merged.content == "旧内容"  # 空串不覆盖
        assert mock_repo.update.await_count == 1
        assert mock_repo.add.await_count == 0

    async def test_update_preserves_unrelated_fields(self, extractor, mock_llm, mock_repo) -> None:
        """更新时保留 extra / created_at 等无关字段。"""
        existing = WorldSetting(
            id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            project_id=PID,
            name="灵气复苏",
            category="旧类别",
            extra={"tags": ["核心"]},
            created_at=TS,
            updated_at=TS,
        )
        mock_repo.get_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _payload(settings=[{"name": "灵气复苏", "category": "设定"}])
        )
        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        merged = result.updated[0]
        assert merged.id == existing.id
        assert merged.name == "灵气复苏"
        assert merged.category == "设定"
        assert merged.extra == {"tags": ["核心"]}
        assert merged.created_at == TS

    async def test_idempotent_second_extraction_produces_empty(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """幂等性: 同一文本二次提取 → created/updated 全空，零写入。"""
        payload = _payload(
            settings=[
                {"name": "灵气复苏", "category": "设定", "content": "天地灵气重新活跃"},
                {"name": "宗门等级", "category": "", "content": ""},
            ]
        )
        mock_llm.chat.return_value = _ok_response(payload)
        req = WorldExtractRequest(project_id=PID, text="t")
        await extractor.extract(req, default_model=DEFAULT_MODEL)
        assert mock_repo.add.await_count == 2

        # 第二轮: 同名条目均已存在且字段一致
        s1 = _setting(name="灵气复苏", category="设定", content="天地灵气重新活跃")
        s2 = _setting(name="宗门等级")
        by_name = {"灵气复苏": s1, "宗门等级": s2}

        async def _get_by_name(pid: int, name: str) -> WorldSetting | None:
            return by_name.get(name)

        mock_repo.get_by_name = AsyncMock(side_effect=_get_by_name)

        result2 = await extractor.extract(req, default_model=DEFAULT_MODEL)
        assert result2.created == []
        assert result2.updated == []
        assert mock_repo.add.await_count == 2  # 第二轮无新建
        assert mock_repo.update.await_count == 0

    async def test_invalid_entries_skipped_with_warning(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """非法条目（空名/超长名）→ 跳过 + warning，其余正常落库。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                settings=[
                    {"name": ""},
                    {"name": "长" * 60},
                    {"name": "灵气复苏", "category": "设定", "content": "天地灵气重新活跃"},
                    {"name": "宗门等级"},
                ]
            )
        )
        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 2
        assert len(result.warnings) == 2  # 2 非法条目
        assert all("跳过" in w for w in result.warnings)

    async def test_fenced_output_extracts_json_fragment(self, extractor, mock_llm) -> None:
        """输出带围栏/前后缀文字 → _extract_json_fragment 提取成功。"""
        payload = _payload(settings=[{"name": "灵气复苏"}])
        fenced = f"好的，以下是提取结果：\n```json\n{payload}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        assert result.created[0].name == "灵气复苏"

    async def test_invalid_output_retries_twice_then_raises(self, extractor, mock_llm) -> None:
        """输出完全非法 → 修复重试 2 次（共 3 次调用）→ WorldExtractionError。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="这不是 JSON", model=DEFAULT_MODEL),
            ChatResponse(content="还是不对", model=DEFAULT_MODEL),
            ChatResponse(content="依然失败", model=DEFAULT_MODEL),
        ]
        with pytest.raises(WorldExtractionError) as excinfo:
            await extractor.extract(
                WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
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
                WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
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
                WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )
        assert mock_llm.chat.await_count == 2

    async def test_empty_world_settings_warns(self, extractor, mock_llm) -> None:
        """空条目列表 → 空结果 + warning。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.created == []
        assert result.updated == []
        assert len(result.warnings) == 1
        assert "未从文本中提取" in result.warnings[0]

    async def test_uses_template_default_model_and_temperature(
        self, extractor, mock_llm, mock_prompt_manager
    ) -> None:
        """断言使用 world_extract 模板 + 变量 text + 默认模型 + temperature 0.2。"""
        mock_llm.chat.return_value = _ok_response(_payload(settings=[{"name": "灵气复苏"}]))
        await extractor.extract(
            WorldExtractRequest(project_id=PID, text="第一章文本"), default_model=DEFAULT_MODEL
        )
        mock_prompt_manager.load.assert_called_once_with("world_extract")
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
            WorldExtractRequest(project_id=PID, text="t", model="deepseek/deepseek-chat"),
            default_model=DEFAULT_MODEL,
        )
        assert mock_llm.chat.await_args.kwargs["model"] == "deepseek/deepseek-chat"
        assert result.model == "deepseek/deepseek-chat"


class TestWorldExtractorHelpers:
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
        outcome = extractor._parse_output('{"world_settings": }')
        assert not outcome.ok
        assert "JSON 语法错误" in outcome.error

    def test_world_settings_not_list_returns_structure_error(self, extractor) -> None:
        """world_settings 字段非列表 → 结构错误。"""
        outcome = extractor._parse_output('{"world_settings": "x"}')
        assert outcome.error == "缺少 world_settings 列表"


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
