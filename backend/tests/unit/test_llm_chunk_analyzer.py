"""F14 LLM 分析切片器单元测试 — Mock LLMClient + Mock PromptManager（#278 M4）.

覆盖 spec §5.6.7（LLM 分析切片器）/§9 测试策略（LLM 模式: mock analyzer
边界生效 / 失败降级不中断）— 本文件测真实 LLM 边界提供器
``LLMChunkAnalyzer``（装配层注入的 async analyzer，复用 F5 LangChainLLMClient +
llm_chunk.yaml 模板）:

- 合法 JSON（boundaries 数组）→ 边界列表返回
- 代码块围栏容忍 / JSON 提取（镜像 F16 `_extract_json_fragment`）
- 非法边界（非升序 / 越界 / 非整数 / 缺键）→ 修复式重试 ≤2 → LLMChunkAnalyzerError
- LLM 调用失败（LLMRequestError）→ 透传（不消耗解析重试，reindex 层降级段落）
- 空文本 → []（不调用 LLM）
- 模板名 llm_chunk + 变量 text 断言
- model 透传（analyzer 构造默认 model / 调用覆盖）

设计假设（RED 阶段按 spec 口径记录，实现须满足）:
- ``LLMChunkAnalyzer(llm_client, prompt_manager, *, model=None)``:
  ``async analyze(text: str) -> list[int]``——语义边界起始偏移列表（升序）。
- 解析输出形态: ``{"boundaries": [5, 12]}``（整数起始偏移；首块边界 0 不返回）。
- 修复式重试镜像 F16/F14 骨架: 对话历史追加 assistant(原输出) + user(修复提示)。
- LLMChunkAnalyzerError 仅断言异常类型（构造参数语义同 F14 TimelineExtractionError）。
- 边界校验规则: 全部整数、0 < b < len(text)、严格升序——任一违规 → 重试/报错。
- 空文本 → 直接返回 []（不调用 LLM，spec §9「空文本 → []」）。

依据: specs/f14-extraction-service/spec.md §5.6.7/§9 + §13 M13。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._llm_chunk_analyzer import LLMChunkAnalyzer, LLMChunkAnalyzerError

DEFAULT_MODEL = "openai/gpt-4o"
TEMPLATE_NAME = "llm_chunk"

TEXT = "林晚推开窗，夜色如墨。她低声说：三年了，我终究还是回来了。窗外传来更鼓声。"


def _payload(boundaries: list[int]) -> str:
    """构造合法 LLM 边界 JSON 输出。"""
    return json.dumps({"boundaries": boundaries}, ensure_ascii=False)


def _ok_response(payload: str) -> ChatResponse:
    """构造 Mock LLM 成功响应。"""
    return ChatResponse(content=payload, model=DEFAULT_MODEL)


@pytest.fixture
def mock_llm() -> MagicMock:
    """Mock LLM 客户端（chat 为 AsyncMock）。"""
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    """Mock Prompt 管理器（load 返回 llm_chunk 模板，render 返回渲染消息）。

    镜像 F16 test_style_llm_analyzer.py fixture 形态：load/render 是同步方法
    （MagicMock 而非 AsyncMock），PromptTemplate 字段为
    name/description/system_prompt/human_prompt/variables。
    """
    pm = MagicMock(spec=PromptTemplateProtocol)
    template = PromptTemplate(
        name=TEMPLATE_NAME,
        description="LLM chunk template",
        system_prompt="你是小说语义切片助手。输出严格 JSON。",
        human_prompt="待分析文本：\n{text}",
        variables=["text"],
    )
    pm.load.return_value = template
    pm.render.return_value = RenderedPrompt(
        messages=[
            {"role": "system", "content": "你是小说语义切片助手。输出严格 JSON。"},
            {"role": "user", "content": f"待分析文本：\n{TEXT}"},
        ],
        token_estimate=50,
    )
    return pm


def _make_analyzer(
    mock_llm: MagicMock,
    mock_prompt_manager: MagicMock,
    **kwargs: object,
) -> LLMChunkAnalyzer:
    """构造被测分析器（Mock 依赖注入）。"""
    return LLMChunkAnalyzer(
        llm_client=mock_llm,  # type: ignore[arg-type]  # Mock 注入 Protocol
        prompt_manager=mock_prompt_manager,  # type: ignore[arg-type]  # Mock 注入 Protocol 端口（F16 同文件惯例）
        **kwargs,
    )


class TestLLMChunkAnalyzer:
    """LLM 语义边界分析器 — 合法解析 / 修复重试 / 失败透传."""

    async def test_analyze_returns_boundaries(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """合法 JSON（boundaries 数组）→ 边界列表返回."""
        mock_llm.chat.return_value = _ok_response(_payload([5, 12]))
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        result = await analyzer.analyze(TEXT)
        assert result == [5, 12]
        # 模板名 + 变量断言（load/render 同步方法——镜像 F16 fixture 形态）
        mock_prompt_manager.load.assert_called_once_with(TEMPLATE_NAME)
        template = mock_prompt_manager.load.return_value
        mock_prompt_manager.render.assert_called_once_with(template, {"text": TEXT})
        # LLM 调用断言（默认 model / temperature 低温）
        chat_kwargs = mock_llm.chat.await_args.kwargs
        assert chat_kwargs["model"] == DEFAULT_MODEL
        assert chat_kwargs["temperature"] == 0.2

    async def test_analyze_tolerates_code_fence(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """代码块围栏输出 → 提取 JSON 片段解析成功（镜像 F16）."""
        raw = f"```json\n{_payload([3])}\n```"
        mock_llm.chat.return_value = _ok_response(raw)
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        assert await analyzer.analyze(TEXT) == [3]

    async def test_analyze_empty_boundaries(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """boundaries 为空数组 → []（单块语义，chunk_text 层处理）."""
        mock_llm.chat.return_value = _ok_response(_payload([]))
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        assert await analyzer.analyze(TEXT) == []

    async def test_analyze_empty_text_skips_llm(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """空文本 → []（不调用 LLM）."""
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        assert await analyzer.analyze("") == []
        mock_llm.chat.assert_not_awaited()

    async def test_analyze_invalid_json_retries_then_error(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """非法 JSON → 修复式重试 ≤2 → 耗尽抛 LLMChunkAnalyzerError."""
        mock_llm.chat.side_effect = [
            _ok_response("不是 JSON"),
            _ok_response("仍然不是 JSON"),
            _ok_response("第三次仍失败"),
        ]
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        with pytest.raises(LLMChunkAnalyzerError):
            await analyzer.analyze(TEXT)
        assert mock_llm.chat.await_count == 3  # 1 原始 + 2 修复

    async def test_analyze_invalid_boundaries_retries_then_error(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """边界非法（越界 / 非升序）→ 修复式重试 ≤2 → LLMChunkAnalyzerError."""
        mock_llm.chat.side_effect = [
            _ok_response(_payload([9999])),  # 越界
            _ok_response(_payload([12, 5])),  # 非升序
            _ok_response(_payload([-1])),  # 非正
        ]
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        with pytest.raises(LLMChunkAnalyzerError):
            await analyzer.analyze(TEXT)
        assert mock_llm.chat.await_count == 3

    async def test_analyze_llm_failure_propagates(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """LLM 调用失败（LLMRequestError）→ 透传（不消耗解析重试；reindex 层降级段落）."""
        mock_llm.chat.side_effect = LLMRequestError("api down")
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager)
        with pytest.raises(LLMRequestError):
            await analyzer.analyze(TEXT)
        assert mock_llm.chat.await_count == 1  # 失败不重试

    async def test_analyze_model_override(
        self, mock_llm: MagicMock, mock_prompt_manager: MagicMock
    ) -> None:
        """model 透传: 构造默认 model 可被覆盖（同 F16 先例）."""
        mock_llm.chat.return_value = _ok_response(_payload([4]))
        analyzer = _make_analyzer(mock_llm, mock_prompt_manager, model="deepseek/deepseek-chat")
        await analyzer.analyze(TEXT)
        chat_kwargs = mock_llm.chat.await_args.kwargs
        assert chat_kwargs["model"] == "deepseek/deepseek-chat"
