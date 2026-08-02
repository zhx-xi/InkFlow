"""F16 LLM 深度分析管线单元测试 — Mock LLMClient + Mock PromptManager（Q1=C）.

覆盖 spec §5.6（LLM 深度分析管线步骤 ①-⑥）/§9（LLM 分析器测试场景）:
合法 JSON → StyleLLMAssessment / 代码块围栏提取 / 非法 JSON 修复式重试 ≤2 次
（共 3 次尝试，耗尽 → StyleLLMAnalysisError）/ verdict 非法值重试 / reasoning
为空重试 / reasoning 超长截断 ≤2000 / 空文本不调用 LLM / LLMRequestError 透传
（不消耗解析重试）/ model 透传（请求覆盖 → 项目默认）/ 模板名 style_llm_analysis
+ temperature 0.2 断言。

设计假设（RED 阶段按 spec 口径记录，实现须满足）:
- StyleLLMAnalyzer.analyze(project, text, *, model=None) -> StyleLLMAssessment | None:
  model 可选覆盖（spec §2.7「model or project.config.model」+ §5.6 步骤 ②）
- 空文本 → 直接返回 None、不调用 LLM（spec §7「空文本项目 → llm_assessment=None」+
  §9「空文本 → 不调用 LLM」）——以 None 表达「未产生 LLM 判定」而非抛错（200 语义）
- 修复式重试镜像 F14 _timeline_extractor 骨架: 对话历史追加 assistant(原输出) +
  user(修复提示，附错误信息)
- StyleLLMAnalysisError 仅断言异常类型（构造参数语义同 F14 TimelineExtractionError，
  本测试不约束）

依据: specs/f16-style-service/spec.md §5.6/§7/§9。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.style import StyleLLMAssessment
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.style_errors import StyleLLMAnalysisError
from inkflow.domain.services._style_llm_analyzer import StyleLLMAnalyzer

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
DEFAULT_MODEL = "openai/gpt-4o"
TEMPLATE_NAME = "style_llm_analysis"

TEXT = "林晚推开窗，夜色如墨。她低声说：三年了，我终究还是回来了。窗外传来更鼓声，一下，两下……"


def _payload(verdict: str = "likely_ai", reasoning: str = "句式整齐，词汇复用偏高。") -> str:
    """构造合法 LLM 判定 JSON 输出。"""
    return json.dumps({"verdict": verdict, "reasoning": reasoning}, ensure_ascii=False)


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
    """Mock Prompt 管理器（load 返回 style_llm_analysis 模板，render 返回渲染消息）。"""
    pm = MagicMock(spec=PromptTemplateProtocol)
    template = PromptTemplate(
        name=TEMPLATE_NAME,
        description="Style LLM analysis template",
        system_prompt="你是小说风格判定器。输出严格 JSON。",
        human_prompt="文本：\n{text}",
        variables=["text"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说风格判定器。输出严格 JSON。"},
                {"role": "user", "content": f"文本：\n{TEXT}"},
            ],
            token_estimate=50,
        )
    )
    return pm


@pytest.fixture
def project() -> Project:
    """构造测试项目（config.model 为项目默认模型）。"""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(model=DEFAULT_MODEL),
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def analyzer(mock_llm: MagicMock, mock_prompt_manager: MagicMock) -> StyleLLMAnalyzer:
    """装配 StyleLLMAnalyzer（Mock LLM + Mock PromptManager 注入，ADR-015）。"""
    return StyleLLMAnalyzer(llm_client=mock_llm, prompt_manager=mock_prompt_manager)


class TestStyleLLMAnalyzer:
    """LLM 深度分析管线测试 — 解析 / 修复重试 / 校验 / 截断（Mock LLM）。"""

    async def test_valid_json_returns_assessment(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """合法 JSON → StyleLLMAssessment（verdict/reasoning/model/generated_at 正确）。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(verdict="likely_human", reasoning="句式长短错落，对话自然。")
        )
        result = await analyzer.analyze(project, TEXT)
        assert isinstance(result, StyleLLMAssessment)
        assert result.llm_verdict == "likely_human"
        assert result.reasoning == "句式长短错落，对话自然。"
        assert result.model == DEFAULT_MODEL  # 缺省 → 项目默认模型
        assert result.generated_at.tzinfo is not None  # UTC 时区感知
        assert mock_llm.chat.await_count == 1

    async def test_fenced_json_extracted(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """代码块围栏/前后缀文字包裹的 JSON → 提取成功（_extract_json_fragment 逻辑）。"""
        payload = _payload()
        fenced = f"好的，以下是判定结果：\n```json\n{payload}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        result = await analyzer.analyze(project, TEXT)
        assert result.llm_verdict == "likely_ai"
        assert result.reasoning == "句式整齐，词汇复用偏高。"

    async def test_invalid_json_retries_twice_then_raises(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """输出完全非法 → 修复重试 2 次（共 3 次调用）→ StyleLLMAnalysisError。"""
        mock_llm.chat.side_effect = [
            _ok_response("这不是 JSON"),
            _ok_response("还是不对"),
            _ok_response("依然失败"),
        ]
        with pytest.raises(StyleLLMAnalysisError):
            await analyzer.analyze(project, TEXT)
        assert mock_llm.chat.await_count == 3  # 首次 + 2 次修复重试
        # 第 2 次调用携带修复 Prompt: assistant(原输出) + user(修复提示)
        call2_msgs = mock_llm.chat.await_args_list[1].args[0]
        assert call2_msgs[-2].role == "assistant"
        assert call2_msgs[-2].content == "这不是 JSON"
        assert call2_msgs[-1].role == "user"
        assert "JSON" in call2_msgs[-1].content

    async def test_invalid_json_recovers_on_retry(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """非法输出后修复重试成功 → 返回评估（共 2 次调用）。"""
        mock_llm.chat.side_effect = [
            _ok_response("这不是 JSON"),
            _ok_response(_payload(verdict="uncertain", reasoning="特征不明显。")),
        ]
        result = await analyzer.analyze(project, TEXT)
        assert result.llm_verdict == "uncertain"
        assert result.reasoning == "特征不明显。"
        assert mock_llm.chat.await_count == 2

    async def test_invalid_verdict_retries(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """verdict 非三值之一（likely_human/uncertain/likely_ai 之外）→ 重试后成功。"""
        mock_llm.chat.side_effect = [
            _ok_response(_payload(verdict="maybe", reasoning="理由")),
            _ok_response(_payload(verdict="likely_ai", reasoning="句式整齐。")),
        ]
        result = await analyzer.analyze(project, TEXT)
        assert result.llm_verdict == "likely_ai"
        assert mock_llm.chat.await_count == 2

    async def test_empty_reasoning_retries(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """reasoning 为空字符串 → 重试后成功（spec §9: reasoning 为空 → 重试）。"""
        mock_llm.chat.side_effect = [
            _ok_response(_payload(reasoning="")),
            _ok_response(_payload(verdict="likely_human", reasoning="人类写作特征。")),
        ]
        result = await analyzer.analyze(project, TEXT)
        assert result.llm_verdict == "likely_human"
        assert result.reasoning == "人类写作特征。"
        assert mock_llm.chat.await_count == 2

    async def test_reasoning_truncated_to_2000(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """reasoning 超长（>2000 字符）→ 截断 ≤ 2000 字符（§2.7/§5.6 步骤 ⑤）。"""
        long_reasoning = "长" * 3000
        mock_llm.chat.return_value = _ok_response(_payload(reasoning=long_reasoning))
        result = await analyzer.analyze(project, TEXT)
        assert len(result.reasoning) == 2000
        assert result.reasoning == "长" * 2000

    async def test_empty_text_returns_none_without_llm_call(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        (
            """空文本 → 不调用 LLM（Mock 断言 chat 未被调用），直接返回"""
            """ None（llm_assessment=None 语义）。"""
        )
        result = await analyzer.analyze(project, "")
        assert result is None
        mock_llm.chat.assert_not_awaited()

    async def test_llm_error_propagates_without_retry(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """Mock LLM 抛 LLMRequestError → 透传，不消耗解析重试（spec §5.6 注）。"""
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        with pytest.raises(LLMRequestError):
            await analyzer.analyze(project, TEXT)
        assert mock_llm.chat.await_count == 1

    async def test_llm_error_after_bad_output_propagates(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """坏输出后 LLM 报错 → 立即透传，不进入第 3 次尝试。"""
        mock_llm.chat.side_effect = [
            _ok_response("坏输出"),
            LLMRequestError("timeout"),
        ]
        with pytest.raises(LLMRequestError):
            await analyzer.analyze(project, TEXT)
        assert mock_llm.chat.await_count == 2

    async def test_request_model_overrides_project_default(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """请求指定 model → LLMClient.chat 收到该 model，评估 model 同步。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await analyzer.analyze(project, TEXT, model="deepseek/deepseek-chat")
        assert mock_llm.chat.await_args.kwargs["model"] == "deepseek/deepseek-chat"
        assert result.model == "deepseek/deepseek-chat"

    async def test_default_model_from_project_config(
        self, analyzer: StyleLLMAnalyzer, mock_llm: MagicMock, project: Project
    ) -> None:
        """缺省 model → 使用项目默认 model（project.config.model）。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await analyzer.analyze(project, TEXT)
        assert mock_llm.chat.await_args.kwargs["model"] == DEFAULT_MODEL
        assert result.model == DEFAULT_MODEL

    async def test_uses_style_llm_analysis_template_and_temperature(
        self,
        analyzer: StyleLLMAnalyzer,
        mock_llm: MagicMock,
        mock_prompt_manager: MagicMock,
        project: Project,
    ) -> None:
        """断言使用 style_llm_analysis 模板 + 变量 {text} + temperature 0.2（构造注入生效）。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        await analyzer.analyze(project, TEXT)
        mock_prompt_manager.load.assert_called_once_with(TEMPLATE_NAME)
        template = mock_prompt_manager.load.return_value
        mock_prompt_manager.render.assert_called_once_with(template, {"text": TEXT})
        kwargs = mock_llm.chat.await_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["temperature"] == 0.2
        msgs = mock_llm.chat.await_args.args[0]
        assert msgs[0].role == "system"
        assert msgs[-1].role == "user"
