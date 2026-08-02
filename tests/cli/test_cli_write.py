"""Write CLI 命令测试."""

import json
import types
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.write import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.writing import WritingMode, WritingResult
from inkflow.domain.ports.llm_client import TokenUsage
from inkflow.domain.ports.llm_errors import LLMRequestError

_EXISTING_CONTENT = (
    "这是已有的章节内容，用于测试续写与修订功能。这一段文本足够长，"
    "以通过续写请求对已有内容的最少字符数校验要求，同时也满足修订请求"
    "对内容长度的基本校验。"
)


@pytest.fixture
def cli_runner(monkeypatch):
    # CI 彩色环境（GITHUB_ACTIONS/FORCE_COLOR）下，Typer 0.27 在 import 时把
    # rich_utils.FORCE_TERMINAL 固定为 True，help 渲染强制带样式，选项名
    # "--count" 被高亮器拆成 ANSI span（"-count"），导致文本断言脆弱。
    # 禁用强制终端渲染 + NO_COLOR，恢复无样式输出。
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", False)
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def mock_writing_service():
    """Mock WritingService + 相关依赖."""
    with patch(
        "inkflow.cli.commands.write.WritingService", autospec=True
    ) as mock_svc_cls:
        mock_svc = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        with patch("inkflow.cli.commands.write.LangChainLLMClient", autospec=True):
            with patch(
                "inkflow.cli.commands.write.LangChainPromptManager", autospec=True
            ):
                with patch(
                    "inkflow.cli.commands.write.NullContextProvider", autospec=True
                ):
                    with patch(
                        "inkflow.cli.commands.write.SQLiteChapterRepository",
                        autospec=True,
                    ) as mock_repo_cls:
                        mock_repo = AsyncMock()
                        mock_repo_cls.return_value = mock_repo
                        mock_repo.get_chapter.return_value = types.SimpleNamespace(
                            content=_EXISTING_CONTENT
                        )
                        yield mock_svc


class TestWriteNext:
    def test_next_json(self, cli_runner, mock_writing_service):
        """write next --json 成功."""
        mock_writing_service.generate_chapter.return_value = WritingResult(
            content="test content",
            word_count=100,
            mode=WritingMode.GENERATE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "test content"
        mock_writing_service.generate_chapter.assert_awaited_once()

    def test_next_count_param(self, cli_runner, mock_writing_service):
        """write next --count / --show-context 参数出现在 help."""
        result = cli_runner.invoke(
            app, ["next", "--help"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "--count" in result.output
        assert "--show-context" in result.output

    def test_next_show_context_placeholder(self, cli_runner, mock_writing_service):
        """--show-context 占位打印."""
        mock_writing_service.generate_chapter.return_value = WritingResult(
            content="test content",
            word_count=100,
            mode=WritingMode.GENERATE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
                "--show-context",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "(--show-context 功能将在 F6 联调时启用)" in result.output

    def test_next_llm_error(self, cli_runner, mock_writing_service):
        """LLM 错误映射为 LLM_ERROR 信封."""
        mock_writing_service.generate_chapter.side_effect = LLMRequestError(
            "provider down"
        )
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "LLM_ERROR"

    def test_generate_renamed_to_next(self, cli_runner):
        """generate 命令已移除（重命名为 next）."""
        result = cli_runner.invoke(
            app, ["generate", "--help"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 2
        assert "No such command" in result.stderr


class TestWriteContinue:
    def test_continue_json(self, cli_runner, mock_writing_service):
        """write continue --json 成功."""
        mock_writing_service.continue_writing.return_value = WritingResult(
            content="continued",
            word_count=50,
            mode=WritingMode.CONTINUE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "continue",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "continued"


class TestWriteRevise:
    def test_revise_json(self, cli_runner, mock_writing_service):
        """write revise --instruction --json 成功."""
        mock_writing_service.revise_content.return_value = WritingResult(
            content="revised",
            word_count=80,
            mode=WritingMode.REVISE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "revise",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--instruction",
                "改短一点",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "revised"

    def test_revise_feedback_removed(self, cli_runner):
        """--feedback 已改名为 --instruction."""
        result = cli_runner.invoke(
            app, ["revise", "--feedback", "x"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 2
        assert "No such option" in result.stderr


# =====================================================================
# F23 SSE 流式输出 — CLI 层 RED 测试（spec §4 / §9 M6/M7，Q3: 默认流式）
# =====================================================================


@pytest.fixture
def mock_streaming_service(mock_writing_service):
    """F23 流式方法 mock — 预置 2 delta + done 事件序列.

    设计假设（docstring 即契约，F16 模式）:
    - 接口签名: WritingService.stream_generate(request) -> AsyncGenerator[
      WritingStreamEvent, None]；stream_continue / stream_revise 同形（spec §5.1）——
      CLI 三子命令默认消费 service 流式方法（spec §4，Q3 拍板，不提供 --no-stream）
    - 事件模型: WritingStreamEvent dataclass（spec §2.1）——RED 阶段未实现，
      本 fixture 延迟 import，未实现时每个用例在 fixture setup 报 ImportError（预期 RED 形态）
    - 事件序列: delta("清晨") + delta("薄雾") + done(format_valid=True, word_count=4,
      model="test-model", token_usage=TokenUsage(prompt_tokens=10, completion_tokens=20,
      total_tokens=30))；全部 delta 拼接 == "清晨薄雾"（4 字）
    - 摘要行常量（spec §4.1，镜像 F3 非流式文案；流式不重试 → retry_count 恒 0）:
      next:     "✅ 章节生成成功: {word_count} 字 (重试 0 次, {model})"
      continue: "✅ 续写完成: {word_count} 字 ({model})"
      revise:   "✅ 修订完成: {word_count} 字 ({model})"
    - 错误类归属: LLMRequestError（domain/ports/llm_errors.py）——项目/章节不存在 →
      NOT_FOUND（spec §7 E1）；流中异常 → LLM_ERROR（spec §7 E3）；
      KeyboardInterrupt → 退出码 130（spec §4.1/§7 E4，Typer 默认）
    - patch 目标: inkflow.cli.commands.write.WritingService（既有 mock_writing_service
      fixture 已 patch，autospec=True；此处仅追加流式方法属性赋值，既有 fixture 零改动）
    """
    from inkflow.domain.models.writing import WritingStreamEvent

    async def _stream_events(*args, **kwargs):
        yield WritingStreamEvent(delta="清晨")
        yield WritingStreamEvent(delta="薄雾")
        yield WritingStreamEvent(
            done=True,
            format_valid=True,
            word_count=4,
            model="test-model",
            token_usage=TokenUsage(
                prompt_tokens=10, completion_tokens=20, total_tokens=30
            ),
        )

    mock_writing_service.stream_generate = _stream_events
    mock_writing_service.stream_continue = _stream_events
    mock_writing_service.stream_revise = _stream_events
    return mock_writing_service


class TestWriteNextStreaming:
    """write next 默认流式输出（人类模式，spec §4.1/§9 M6）.

    设计假设:
    - 默认（json_output=False）下 CLI 消费 service.stream_generate（非 generate_chapter），
      逐 delta 用 typer.echo(ev.delta, nl=False) 打印——chunk 间无换行分隔，拼接 == 全文
    - 摘要行: "✅ 章节生成成功: {word_count} 字 (重试 0 次, {model})"；format_valid=False
      时前缀 ⚠️ 且 warnings 逐条 echo（spec §7 E6）
    - --count > 1（仅 next）: 逐章流式循环，每章一个摘要行（spec §4.1）
    - 成功退出码 0
    """

    def test_next_streams_deltas_then_summary(self, cli_runner, mock_streaming_service):
        """默认流式: stdout 逐 delta 连续拼接 == 全文 + ✅ 摘要行."""
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        # 逐 delta 连续打印（nl=False，无换行分隔）——"清晨"+"薄雾" 直接拼接
        assert "清晨薄雾" in result.stdout
        assert "✅ 章节生成成功: 4 字 (重试 0 次, test-model)" in result.stdout

    def test_next_stream_warning_summary(self, cli_runner, mock_streaming_service):
        """format_valid=False → ⚠️ 摘要 + warnings 逐条 echo（spec §7 E6）."""
        from inkflow.domain.models.writing import WritingStreamEvent

        async def _stream_warning(*args, **kwargs):
            yield WritingStreamEvent(delta="清晨")
            yield WritingStreamEvent(delta="薄雾")
            yield WritingStreamEvent(
                done=True,
                format_valid=False,
                warnings=["字数不足，格式校验未通过"],
                word_count=4,
                model="test-model",
            )

        mock_streaming_service.stream_generate = _stream_warning
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "⚠️ 章节生成成功: 4 字 (重试 0 次, test-model)" in result.stdout
        assert "字数不足，格式校验未通过" in result.stdout

    def test_next_count_two_streams_twice(self, cli_runner, mock_streaming_service):
        """--count 2: 两次流式生成 + 两个摘要行（spec §4.1）."""
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--count",
                "2",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert result.stdout.count("清晨薄雾") == 2
        assert result.stdout.count("✅ 章节生成成功: 4 字 (重试 0 次, test-model)") == 2


class TestWriteContinueStreaming:
    """write continue 默认流式输出（spec §4.1/§9 M6）.

    设计假设:
    - 默认（json_output=False）下 CLI 消费 service.stream_continue（非 continue_writing）
    - 摘要行: "✅ 续写完成: {word_count} 字 ({model})"
    - 成功退出码 0
    """

    def test_continue_streams_deltas_then_summary(
        self, cli_runner, mock_streaming_service
    ):
        """continue 流式输出 + 「✅ 续写完成」摘要."""
        result = cli_runner.invoke(
            app,
            [
                "continue",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "清晨薄雾" in result.stdout
        assert "✅ 续写完成: 4 字 (test-model)" in result.stdout


class TestWriteReviseStreaming:
    """write revise 默认流式输出（spec §4.1/§9 M6）.

    设计假设:
    - 默认（json_output=False）下 CLI 消费 service.stream_revise（非 revise_content）
    - 摘要行: "✅ 修订完成: {word_count} 字 ({model})"
    - 成功退出码 0
    """

    def test_revise_streams_deltas_then_summary(
        self, cli_runner, mock_streaming_service
    ):
        """revise 流式输出 + 「✅ 修订完成」摘要."""
        result = cli_runner.invoke(
            app,
            [
                "revise",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--instruction",
                "改短一点",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "清晨薄雾" in result.stdout
        assert "✅ 修订完成: 4 字 (test-model)" in result.stdout


class TestWriteStreamJson:
    """--json 模式: 静默收集 delta，流结束后输出信封（spec §4.2/§9 M7）.

    设计假设:
    - json_output=True 时 CLI 不逐 delta 打印（静默收集），stdout 为单一 JSON 信封——
      json.loads 可解析整段 stdout（若逐 token 打印则解析失败）
    - 信封: {"ok": true, "data": WritingResult.model_dump(mode="json")}——
      data.content == 全文拼接（"清晨薄雾"）、format_valid/word_count/model/
      token_usage/retry_count(恒 0)/mode(StrEnum 值 "generate") 完整透传（spec §4.2）
    - --count > 1 + --json: data 为数组信封（镜像 F3 next 逻辑 write.py L78-84）
    - 成功退出码 0
    """

    def test_next_json_silent_collect_envelope(
        self, cli_runner, mock_streaming_service
    ):
        """next --json: 静默收集，信封 content == 全文拼接 + 结果字段完整."""
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        # 整段 stdout 可解析为单个 JSON → 无逐 delta 打印（静默收集）
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "清晨薄雾"
        assert payload["data"]["format_valid"] is True
        assert payload["data"]["word_count"] == 4
        assert payload["data"]["model"] == "test-model"
        assert payload["data"]["mode"] == "generate"
        assert payload["data"]["retry_count"] == 0
        assert payload["data"]["token_usage"]["total_tokens"] == 30
        # 静默收集佐证: delta 文本仅作为 content 字段值出现一次
        assert result.stdout.count("清晨") == 1

    def test_next_count_two_json_array(self, cli_runner, mock_streaming_service):
        """next --count 2 --json: data 为数组信封（两个元素）."""
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--count",
                "2",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert isinstance(payload["data"], list)
        assert len(payload["data"]) == 2
        assert payload["data"][0]["content"] == "清晨薄雾"
        assert payload["data"][1]["content"] == "清晨薄雾"


class TestWriteStreamErrors:
    """流式错误路径（spec §7 E1/E3/E4/§9 M6）.

    设计假设:
    - 错误类归属: LLMRequestError（domain/ports/llm_errors.py）
    - NOT_FOUND（E1）: service.stream_generate 在流开始前 raise
      LLMRequestError("项目不存在") → print_error(cli_ctx, "NOT_FOUND", ...) →
      退出码 1，JSON 错误信封 code == "NOT_FOUND"
    - LLM_ERROR（E3）: async generator 流中 raise LLMRequestError →
      print_error(cli_ctx, "LLM_ERROR", ...) → 退出码 1，JSON 错误信封 code == "LLM_ERROR"
    - KeyboardInterrupt（E4/Ctrl+C）: mock 抛 KeyboardInterrupt → 退出码 130（Typer 默认）
    - 错误信封: {"ok": false, "error": {"code": ..., "message": ...}}（output.py print_error）
    """

    def test_next_not_found_error(self, cli_runner, mock_streaming_service):
        """项目不存在 → 退出码 1 + NOT_FOUND 错误信封（spec §7 E1）."""

        async def _stream_not_found(*args, **kwargs):
            raise LLMRequestError("项目不存在")
            yield  # pragma: no cover — 使函数为 async generator，首个 next() 即抛异常

        mock_streaming_service.stream_generate = _stream_not_found
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"
        assert "项目不存在" in payload["error"]["message"]

    def test_next_llm_error_in_stream(self, cli_runner, mock_streaming_service):
        """流中 LLM 异常 → 退出码 1 + LLM_ERROR 错误信封（spec §7 E3）."""
        from inkflow.domain.models.writing import WritingStreamEvent

        async def _stream_then_raise(*args, **kwargs):
            yield WritingStreamEvent(delta="清晨")
            raise LLMRequestError("provider down")

        mock_streaming_service.stream_generate = _stream_then_raise
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "LLM_ERROR"

    def test_next_keyboard_interrupt_exit_130(self, cli_runner, mock_streaming_service):
        """Ctrl+C（KeyboardInterrupt）→ 退出码 130（spec §4.1/§7 E4）."""

        async def _stream_interrupt(*args, **kwargs):
            raise KeyboardInterrupt
            yield  # pragma: no cover — 使函数为 async generator

        mock_streaming_service.stream_generate = _stream_interrupt
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 130
