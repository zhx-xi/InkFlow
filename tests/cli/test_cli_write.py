"""Write CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（F38 HTTP mock 轨，SSE 流式）.

F38 改造（#169）：mock 目标从 domain Service/LLM 客户端迁移到 ensure_kernel +
InkFlowHTTPClient（HTTP JSON 响应 + SSE 流式 mock）；create_tables/session/LLM
patch 已移除。命令改造后不再 import 服务层/仓储/LLM 客户端——GREEN 目标为
write.py 内 `from inkflow.infrastructure.kernel import ensure_kernel` 与
`from inkflow.infrastructure.http import InkFlowHTTPClient`；RED 阶段两符号
不存在 → fake_http_client fixture 的 patch setup 抛 AttributeError（同根因，
预期 RED 形态）。

══════════════════════════════════════════════════════════════════════════
HTTP 契约（实现者以本文件为准，F38 §3.1/§5.4）:
- 三子命令默认流式：POST /writing/stream（SSE），body 带 mode 判别
  （generate/continue/revise，F23 判别联合）+ 请求字段 JSON；base_url =
  http://127.0.0.1:{port}/api/v1
- continue/revise 需章节原文：先 GET /chapters/{chapter_id}（响应含 content），
  再组装 existing_content/content 字段进流式 body；404 → NOT_FOUND
- SSE 帧（F23 §6.2，dict 原样透传）:
  * delta 帧 {"done": false, "delta": "..."}（0-N 个）——全部 delta 拼接 == content
  * done 帧 {"done": true, "format_valid", "warnings", "word_count", "model",
    "token_usage"}（恰好 1 个）——帧字段 → WritingResult
  * error 帧 {"done": true, "error": "..."} → LLM_ERROR（spec §7 E12）
- 流前错误 = HttpApiError(status_code, detail[, code])：404 → NOT_FOUND；
  500 + code="LLM_ERROR" → LLM_ERROR（§5.3 映射表）；HttpApiError 惰性 import
- 非流式兜底（generate/continue/revise 端点）：POST /writing/generate|continue|revise
  → WritingResult JSON dict（当前用例不触发；如需兜底路径 mock post.return_value）
- next --count N：循环调用 stream_sse N 次（同一 client 实例，§5.2）
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.write import app
from inkflow.cli.context import CliContext

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


async def _stream_events(*args, **kwargs):
    """F23 SSE 帧序列（dict 形态，spec §6.2）：2 delta + 1 done.

    全部 delta 拼接 == "清晨薄雾"（4 字）；done 帧携带 format_valid/word_count/
    model/token_usage/warnings（与 F3 非流式 _preset 字段镜像）。
    """
    yield {"done": False, "delta": "清晨"}
    yield {"done": False, "delta": "薄雾"}
    yield {
        "done": True,
        "format_valid": True,
        "word_count": 4,
        "model": "test-model",
        "token_usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
        "warnings": [],
    }


@pytest.fixture
def fake_http_client():
    """patch ensure_kernel + InkFlowHTTPClient（命令模块命名空间）→ fake client 实例.

    - stream_sse = MagicMock(side_effect=_stream_events)：调用返回 async generator
      （与真实 client.stream_sse 形态一致——async generator 函数，调用即得生成器），
      同时保留调用记录供 assert_called_once_with 断言 path/body。
    - get 预置 GET /chapters/{id} 响应（continue/revise 需章节原文拼 existing_content）。
    - __aenter__ 返回自身：`async with InkFlowHTTPClient(handle) as client` 的
      client 即本 mock，后续调用记录在 mock_instance 上。
    """
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.write.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.write.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get.return_value = {"content": _EXISTING_CONTENT}
        mock_instance.stream_sse = MagicMock(side_effect=_stream_events)
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_err(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError（infrastructure.http RED 阶段不存在，禁顶部 import）."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _assert_stream_body(body: dict, mode: str, **expected) -> None:
    """流式请求体契约断言：mode 判别 + 关键字段（不做全字段锁定，可选字段
    由内核侧 DTO 默认值兜底）."""
    assert body["mode"] == mode
    for key, value in expected.items():
        assert body[key] == value


class TestWriteNext:
    def test_next_json(self, cli_runner, fake_http_client):
        """write next --json 成功（F23: 流式静默收集 → JSON 信封）."""
        pid = uuid.uuid4()
        cid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(pid),
                "--chapter-id",
                str(cid),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        # 流式契约（spec §4.2）: 信封 content == 全部 delta 拼接 == 全文
        assert payload["data"]["content"] == "清晨薄雾"
        assert payload["data"]["format_valid"] is True
        assert payload["data"]["word_count"] == 4
        assert payload["data"]["model"] == "test-model"
        assert payload["data"]["mode"] == "generate"
        assert payload["data"]["retry_count"] == 0
        assert payload["data"]["token_usage"]["total_tokens"] == 30

        # HTTP 契约: POST /writing/stream + mode 判别 + 参数映射（F38 §5.4）
        call = fake_http_client.stream_sse.call_args
        assert call.args[0] == "/writing/stream"
        _assert_stream_body(
            call.kwargs["json"],
            "generate",
            project_id=str(pid),
            chapter_id=str(cid),
            outline="test outline",
        )

    def test_next_count_param(self, cli_runner):
        """write next --count / --show-context 参数出现在 help."""
        result = cli_runner.invoke(
            app, ["next", "--help"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "--count" in result.output
        assert "--show-context" in result.output

    def test_next_show_context_placeholder(self, cli_runner, fake_http_client):
        """--show-context 占位打印（F23 流式: 仍在摘要行后 echo，spec §4.1）."""
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
        # 流式摘要行先输出，占位提示在其后
        assert result.output.index("✅ 章节生成成功: 4 字 (重试 0 次, test-model)") < (
            result.output.index("(--show-context 功能将在 F6 联调时启用)")
        )

    def test_next_llm_error_before_stream(self, cli_runner, fake_http_client):
        """流前 LLM 错误（HTTP 500 + LLM_ERROR 头）→ LLM_ERROR 信封（F38 §5.3）."""
        fake_http_client.stream_sse.side_effect = _http_err(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
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
    def test_continue_json(self, cli_runner, fake_http_client):
        """write continue --json 成功（F23: 流式静默收集 → JSON 信封）."""
        pid = uuid.uuid4()
        cid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            [
                "continue",
                "--project-id",
                str(pid),
                "--chapter-id",
                str(cid),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        # 流式契约（spec §4.2）: 信封 content == 全部 delta 拼接 == 全文
        assert payload["data"]["content"] == "清晨薄雾"
        assert payload["data"]["format_valid"] is True
        assert payload["data"]["word_count"] == 4
        assert payload["data"]["model"] == "test-model"
        assert payload["data"]["mode"] == "continue"
        assert payload["data"]["retry_count"] == 0
        assert payload["data"]["token_usage"]["total_tokens"] == 30

        # HTTP 契约: 先 GET /chapters/{id} 取章节原文，再流式 mode=continue
        call = fake_http_client.stream_sse.call_args
        assert call.args[0] == "/writing/stream"
        _assert_stream_body(
            call.kwargs["json"],
            "continue",
            project_id=str(pid),
            chapter_id=str(cid),
            existing_content=_EXISTING_CONTENT,
        )


class TestWriteRevise:
    def test_revise_json(self, cli_runner, fake_http_client):
        """write revise --instruction --json 成功（F23: 流式静默收集 → JSON 信封）."""
        pid = uuid.uuid4()
        cid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            [
                "revise",
                "--project-id",
                str(pid),
                "--chapter-id",
                str(cid),
                "--instruction",
                "改短一点",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        # 流式契约（spec §4.2）: 信封 content == 全部 delta 拼接 == 全文
        assert payload["data"]["content"] == "清晨薄雾"
        assert payload["data"]["format_valid"] is True
        assert payload["data"]["word_count"] == 4
        assert payload["data"]["model"] == "test-model"
        assert payload["data"]["mode"] == "revise"
        assert payload["data"]["retry_count"] == 0
        assert payload["data"]["token_usage"]["total_tokens"] == 30

        # HTTP 契约: 先 GET /chapters/{id} 取章节原文，再流式 mode=revise
        call = fake_http_client.stream_sse.call_args
        assert call.args[0] == "/writing/stream"
        _assert_stream_body(
            call.kwargs["json"],
            "revise",
            project_id=str(pid),
            chapter_id=str(cid),
            content=_EXISTING_CONTENT,
            feedback="改短一点",
        )

    def test_revise_feedback_removed(self, cli_runner):
        """--feedback 已改名为 --instruction."""
        result = cli_runner.invoke(
            app, ["revise", "--feedback", "x"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 2
        assert "No such option" in result.stderr


# =====================================================================
# F38 SSE 流式 — CLI 层（spec §4 / §9 M6/M7，Q3: 默认流式）
# =====================================================================


class TestWriteNextStreaming:
    """write next 默认流式输出（人类模式，spec §4.1/§9 M6）.

    设计假设:
    - 默认（json_output=False）下 CLI 消费 client.stream_sse("/writing/stream")，
      逐 delta 用 typer.echo(ev["delta"], nl=False) 打印——chunk 间无换行分隔，
      拼接 == 全文
    - 摘要行: "✅ 章节生成成功: {word_count} 字 (重试 0 次, {model})"；
      format_valid=False 时前缀 ⚠️ 且 warnings 逐条 echo（spec §7 E6）
    - --count > 1（仅 next）: 逐章流式循环，每章一个摘要行（spec §4.1）
    - 成功退出码 0
    """

    def test_next_streams_deltas_then_summary(self, cli_runner, fake_http_client):
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

    def test_next_stream_warning_summary(self, cli_runner, fake_http_client):
        """format_valid=False → ⚠️ 摘要 + warnings 逐条 echo（spec §7 E6）."""

        async def _stream_warning(*args, **kwargs):
            yield {"done": False, "delta": "清晨"}
            yield {"done": False, "delta": "薄雾"}
            yield {
                "done": True,
                "format_valid": False,
                "warnings": ["字数不足，格式校验未通过"],
                "word_count": 4,
                "model": "test-model",
            }

        fake_http_client.stream_sse.side_effect = _stream_warning
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

    def test_next_count_two_streams_twice(self, cli_runner, fake_http_client):
        """--count 2: 两次流式生成 + 两个摘要行（spec §4.1，F38 §5.2 同 client 循环）."""
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
        # --count N → stream_sse 恰好被调用 N 次
        assert fake_http_client.stream_sse.call_count == 2


class TestWriteContinueStreaming:
    """write continue 默认流式输出（spec §4.1/§9 M6）.

    设计假设:
    - 默认（json_output=False）下 CLI 消费 client.stream_sse（mode=continue）
    - 摘要行: "✅ 续写完成: {word_count} 字 ({model})"
    - 成功退出码 0
    """

    def test_continue_streams_deltas_then_summary(self, cli_runner, fake_http_client):
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
    - 默认（json_output=False）下 CLI 消费 client.stream_sse（mode=revise）
    - 摘要行: "✅ 修订完成: {word_count} 字 ({model})"
    - 成功退出码 0
    """

    def test_revise_streams_deltas_then_summary(self, cli_runner, fake_http_client):
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
      token_usage/retry_count(恒 0)/mode(值 "generate") 完整透传（spec §4.2）
    - --count > 1 + --json: data 为数组信封
    - 成功退出码 0
    """

    def test_next_json_silent_collect_envelope(self, cli_runner, fake_http_client):
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

    def test_next_count_two_json_array(self, cli_runner, fake_http_client):
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
    """流式错误路径（spec §7 E1/E3/E4/§9 M6，F38 §5.3 映射）.

    设计假设:
    - 错误类归属: HttpApiError（infrastructure/http）——F38 后 CLI 只见 HTTP 状态
    - NOT_FOUND（E1）: stream_sse 在流开始前抛 HttpApiError(404, "项目不存在")
      → print_error(cli_ctx, "NOT_FOUND", ...) → 退出码 1，JSON 错误信封
      code == "NOT_FOUND"
    - LLM_ERROR（E3）: 流中 error 帧 {"done": true, "error": "..."} →
      LLM_ERROR；流前 HttpApiError(500, code="LLM_ERROR") 同码（F38 §5.3）
    - KeyboardInterrupt（E4/Ctrl+C）: 流生成器抛 KeyboardInterrupt →
      退出码 130（Typer 默认）
    - 错误信封: {"ok": false, "error": {"code": ..., "message": ...}}（output.py print_error）
    """

    def test_next_not_found_error(self, cli_runner, fake_http_client):
        """项目不存在（HTTP 404）→ 退出码 1 + NOT_FOUND 错误信封（spec §7 E1）."""
        fake_http_client.stream_sse.side_effect = _http_err(404, "项目不存在")
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

    def test_next_llm_error_in_stream(self, cli_runner, fake_http_client):
        """流中 error 帧 → 退出码 1 + LLM_ERROR 错误信封（spec §7 E3/F38 §5.4）."""

        async def _stream_error_frame(*args, **kwargs):
            yield {"done": True, "error": "LLM 调用失败，请稍后重试"}

        fake_http_client.stream_sse.side_effect = _stream_error_frame
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

    def test_next_keyboard_interrupt_exit_130(self, cli_runner, fake_http_client):
        """Ctrl+C（KeyboardInterrupt）→ 退出码 130（spec §4.1/§7 E4）."""

        async def _stream_interrupt(*args, **kwargs):
            raise KeyboardInterrupt
            yield  # pragma: no cover — 使函数为 async generator

        fake_http_client.stream_sse.side_effect = _stream_interrupt
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


class TestWriteCollectStreamFallback:
    """_collect_stream 防御回退（spec §4.1 注释: 流异常终止无 done 帧——按空结果回退）."""

    def test_next_stream_without_done_frame(self, cli_runner, fake_http_client):
        """流只含空 delta 帧（delta 为空且 done=False）且无 done 帧 → 空结果回退:
        content 空 + 「生成内容为空」警告 + format_valid=False."""

        async def _stream_no_done(*args, **kwargs):
            yield {"done": False, "delta": ""}

        fake_http_client.stream_sse.side_effect = _stream_no_done
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
        assert payload["data"]["content"] == ""
        assert payload["data"]["word_count"] == 0
        assert payload["data"]["format_valid"] is False
        assert payload["data"]["model"] == ""
        assert payload["data"]["warnings"] == ["生成内容为空"]


class TestWriteContinueErrors:
    """write continue 错误分支（spec §7 E1/E3）：章节不存在 / 内核校验 404 /
    流前 LLM 500."""

    def test_continue_chapter_not_found(self, cli_runner, fake_http_client):
        """续写目标章节不存在（GET /chapters 404）→ NOT_FOUND 信封 + 退出码 1
        （CLI 层防御，stream_sse 未调用）."""
        fake_http_client.get.side_effect = _http_err(404, "章节不存在")
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
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"
        assert payload["error"]["message"] == "章节不存在"
        fake_http_client.stream_sse.assert_not_called()

    def test_continue_llm_not_found_message(self, cli_runner, fake_http_client):
        """内核前置校验失败（流前 404，章节不存在）→ NOT_FOUND 语义（spec §7 E1）."""
        fake_http_client.stream_sse.side_effect = _http_err(404, "章节不存在")
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
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"
        assert "章节不存在" in payload["error"]["message"]

    def test_continue_llm_error(self, cli_runner, fake_http_client):
        """流前 LLM 500（LLM_ERROR 头）→ LLM_ERROR 信封 + 退出码 1（spec §7 E3）."""
        fake_http_client.stream_sse.side_effect = _http_err(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
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
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "LLM_ERROR"
        assert "LLM 调用失败" in payload["error"]["message"]


class TestWriteReviseErrors:
    """write revise 错误分支（spec §7 E1/E3）：章节不存在 / 内核校验 404 /
    流前 LLM 500."""

    def test_revise_chapter_not_found(self, cli_runner, fake_http_client):
        """修订目标章节不存在（GET /chapters 404）→ NOT_FOUND 信封 + 退出码 1
        （CLI 层防御，stream_sse 未调用）."""
        fake_http_client.get.side_effect = _http_err(404, "章节不存在")
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
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"
        assert payload["error"]["message"] == "章节不存在"
        fake_http_client.stream_sse.assert_not_called()

    def test_revise_llm_not_found_message(self, cli_runner, fake_http_client):
        """内核前置校验失败（流前 404，章节不存在）→ NOT_FOUND 语义（spec §7 E1）."""
        fake_http_client.stream_sse.side_effect = _http_err(404, "章节不存在")
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
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"

    def test_revise_llm_error(self, cli_runner, fake_http_client):
        """流前 LLM 500（LLM_ERROR 头）→ LLM_ERROR 信封 + 退出码 1（spec §7 E3）."""
        fake_http_client.stream_sse.side_effect = _http_err(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
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
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "LLM_ERROR"
