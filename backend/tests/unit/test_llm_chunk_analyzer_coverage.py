"""#627 coverage-gap closure: 补 _llm_chunk_analyzer 漏覆盖分支（独立文件，避免与
test_llm_chunk_analyzer.py 冲突/900 行护栏）。

覆盖：
- `_extract_json_fragment`：嵌套花括号回边（L87->71）、字符串转义（L74->75/L76->77）、
  未闭合 → None（L71->89 / line 89）。
- `_parse_output`：JSONDecodeError（L196->197）、boundaries 非数组（L203->204）、
  元素非整数（L208->209）。
- `analyze`：JSON 语法错误 → 修复式重试（走 L196->197 分支）。

物理不可达行（源码注释自证，不硬造 mock）：line 186（重试循环后不可达 raise）、
line 200（_extract_json_fragment 恒返回 `{...}` 片段 → json.loads 恒为 dict）。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._llm_chunk_analyzer import (
    LLMChunkAnalyzer,
    LLMChunkAnalyzerError,
    _extract_json_fragment,
)

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
TEMPLATE_NAME = "llm_chunk"
TEXT = "林晚推开窗，夜色如墨。她低声说：三年了。"


def _payload(boundaries: list[int]) -> str:
    return json.dumps({"boundaries": boundaries}, ensure_ascii=False)


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
    pm.load.return_value = PromptTemplate(
        name=TEMPLATE_NAME,
        description="LLM chunk template",
        system_prompt="你是小说语义切片助手。输出严格 JSON。",
        human_prompt="待分析文本：\n{text}",
        variables=["text"],
    )
    pm.render.return_value = RenderedPrompt(
        messages=[
            {"role": "system", "content": "你是小说语义切片助手。"},
            {"role": "user", "content": f"待分析文本：\n{TEXT}"},
        ],
        token_estimate=50,
    )
    return pm


def _make_analyzer(
    mock_llm: MagicMock, mock_prompt_manager: MagicMock, **kwargs
) -> LLMChunkAnalyzer:
    return LLMChunkAnalyzer(
        llm_client=mock_llm,  # type: ignore[arg-type]
        prompt_manager=mock_prompt_manager,  # type: ignore[arg-type]
        **kwargs,
    )


class TestExtractJsonFragment:
    """_extract_json_fragment 防御分支（#627 补测）。"""

    def test_nested_braces_back_edge(self):
        """嵌套花括号：深度未归零时继续扫描（L87->71 回边）。"""
        assert _extract_json_fragment("{{a}}") == "{{a}}"

    def test_escaped_string(self):
        """字符串字面量内转义字符（\\ 与 \"）→ 跳过（L74->75 / L76->77）。"""
        # JSON 字符串值含转义反斜杠：{"a": "x\\ny"} —— 经 json.dumps 构造，源码零转义
        raw = json.dumps({"a": "x\\ny"}, ensure_ascii=False)
        assert _extract_json_fragment(raw) == raw

    def test_unterminated_returns_none(self):
        """有 { 无配对 } → 返回 None（L71->89 / line 89）。"""
        assert _extract_json_fragment("{abc") is None


class TestParseOutputGaps:
    """_parse_output 校验分支（#627 补测）。"""

    def test_boundaries_not_list(self, mock_llm, mock_prompt_manager):
        """boundaries 非数组（字符串）→ 错误（L203->204）。"""
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        outcome = analyzer._parse_output('{"boundaries": "x"}', TEXT)
        assert outcome.ok is False
        assert "必须是数组" in outcome.error

    def test_non_int_element(self, mock_llm, mock_prompt_manager):
        """boundaries 元素非整数（字符串）→ 错误（L208->209）。"""
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        outcome = analyzer._parse_output('{"boundaries": [1, "a"]}', TEXT)
        assert outcome.ok is False
        assert "必须是整数" in outcome.error


class TestAnalyzerRetryGap:
    """analyze 的 JSON 语法错误 → 修复式重试（L196->197 分支）。"""

    async def test_json_syntax_error_retries(self, mock_llm, mock_prompt_manager):
        mock_llm.chat.side_effect = [
            _ok_response("{invalid}"),
            _ok_response("仍无法解析"),
            _ok_response("第三次失败"),
        ]
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        with pytest.raises(LLMChunkAnalyzerError):
            await analyzer.analyze(TEXT)
        assert mock_llm.chat.await_count == 3
