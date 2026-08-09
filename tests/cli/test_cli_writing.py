"""CLI 写作命令集成测试 — CliRunner + 有状态 fake InkFlowHTTPClient（F38 HTTP mock 轨）.

测试范围：inkflow write next/continue/revise。
需 pytest marker: @pytest.mark.writing

F38 改造（#169）：mock 目标从 domain Service/LLM 客户端迁移到 ensure_kernel +
InkFlowHTTPClient（HTTP JSON 响应 + SSE 流式 mock）；create_tables/session/LLM
patch 已移除（isolated_db 不再需要——命令不再直连 DB）。有状态 fake client
以内存章节表模拟 GET /chapters/{id}（continue/revise 取章节原文拼请求体）。
RED 阶段命令模块无 ensure_kernel/InkFlowHTTPClient 属性 → fake_http_client
fixture 的 patch setup 抛 AttributeError（同根因，预期 RED）。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

from .conftest import _parse_json_output

runner = CliRunner()

_CONTENT = "# 试炼场风波\n\n清晨的薄雾尚未散尽……"


def _http_err(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError（infrastructure.http RED 阶段不存在，禁顶部 import）."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


class _FakeHTTPClient:
    """有状态 fake InkFlowHTTPClient — 内存章节表模拟，不触发真实 LLM/DB.

    F23（spec §4，Q3 拍板）: CLI 默认流式——只消费 stream_sse（mode 判别）；
    非流式端点（generate/continue/revise）为兜底路径，本文件用例不触发。

    - get("/chapters/{id}") → 内存章节 dict（content 预置）；未知 id → 404
    - stream_sse("/writing/stream") → 预置 delta + done 帧（dict 形态，§6.2）
    - stream_error 置位后 stream_sse 在首帧前抛 HttpApiError（流前错误路径）
    """

    def __init__(self, handle):
        self.stream_error = None
        self.chapters = {
            "22222222-2222-2222-2222-222222222222": {
                "id": "22222222-2222-2222-2222-222222222222",
                "title": "试炼场",
                "content": _CONTENT,
            }
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, path, *, params=None):
        if path.startswith("/chapters/"):
            cid = path.rsplit("/", 1)[-1]
            if cid in self.chapters:
                return self.chapters[cid]
            raise _http_err(404, "章节不存在")
        raise AssertionError(f"unexpected GET {path}")

    async def post(self, path, *, json=None):
        raise AssertionError(f"unexpected POST {path}")

    async def stream_sse(self, path, *, json=None):
        assert path == "/writing/stream", path
        assert json is not None and json.get("mode") in (
            "generate",
            "continue",
            "revise",
        )
        if self.stream_error is not None:
            raise self.stream_error
        yield {"done": False, "delta": _CONTENT}
        yield {
            "done": True,
            "format_valid": True,
            "word_count": 2347,
            "model": "deepseek/deepseek-chat",
            "token_usage": {
                "prompt_tokens": 1820,
                "completion_tokens": 2600,
                "total_tokens": 4420,
            },
            "warnings": [],
        }


@pytest.fixture
def fake_http_client():
    """patch ensure_kernel + InkFlowHTTPClient（命令模块命名空间）→ 有状态 fake client."""
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
        patch("inkflow.cli.commands.write.InkFlowHTTPClient") as mock_cls,
    ):
        mock_cls.return_value = _FakeHTTPClient(fake_handle)
        yield mock_cls.return_value


class TestWriteCLI:
    """inkflow write 子命令测试 — 有状态 fake HTTP client."""

    @pytest.mark.writing
    def test_write_help(self):
        """inkflow write --help 正常且包含三个子命令."""
        result = runner.invoke(app, ["write", "--help"])
        assert result.exit_code == 0
        assert "AI 写作" in result.stdout
        assert all(cmd in result.stdout for cmd in ["next", "continue", "revise"])

    @pytest.mark.writing
    def test_write_next_human(self, fake_http_client):
        """next 默认人类可读输出."""
        result = runner.invoke(
            app,
            [
                "write",
                "next",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "章节生成成功" in result.output
        assert "2347 字" in result.output

    @pytest.mark.writing
    def test_write_next_json(self, fake_http_client):
        """next --json 输出 WritingResult JSON."""
        result = runner.invoke(
            app,
            [
                "--json",
                "write",
                "next",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
            ],
        )
        assert result.exit_code == 0, result.output
        data = _parse_json_output(result.output)
        assert data["mode"] == "generate"
        assert data["word_count"] == 2347
        assert data["format_valid"] is True

    @pytest.mark.writing
    def test_write_continue_json(self, fake_http_client):
        """continue --json 输出 WritingResult JSON."""
        result = runner.invoke(
            app,
            [
                "--json",
                "write",
                "continue",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--target-words",
                "3000",
            ],
        )
        assert result.exit_code == 0, result.output
        data = _parse_json_output(result.output)
        assert data["mode"] == "continue"
        assert data["word_count"] == 2347

    @pytest.mark.writing
    def test_write_revise_json(self, fake_http_client):
        """revise --json 输出 WritingResult JSON."""
        result = runner.invoke(
            app,
            [
                "--json",
                "write",
                "revise",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--instruction",
                "节奏太慢，删减环境描写",
                "--range",
                "第 3 段",
            ],
        )
        assert result.exit_code == 0, result.output
        data = _parse_json_output(result.output)
        assert data["mode"] == "revise"
        assert data["word_count"] == 2347

    @pytest.mark.writing
    def test_write_next_llm_error(self, fake_http_client):
        """LLM 调用失败 → 退出码 1，stderr 输出错误信息（F38: 流前 500 + LLM_ERROR 头）."""
        fake_http_client.stream_error = _http_err(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
        )
        result = runner.invoke(
            app,
            [
                "write",
                "next",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
            ],
        )
        assert result.exit_code == 1
        assert "LLM 调用失败" in result.stderr
