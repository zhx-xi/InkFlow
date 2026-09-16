"""#1186 P2-b RED 契约 — `inkflow write next --show-context` 打印真实 ContextAssemblyResult.

被测行为（对照当前实现 FAIL）:
    当前 ``cli/commands/write.py:26`` 定义占位常量
    ``_SHOW_CONTEXT_NOTE = "(--show-context 功能将在 F6 联调时启用)"``，
    并在 :240-241 恒打印该占位符 —— 功能完全未接。

spec：specs/f6-context/spec.md §6 L310 / §13 M6 L489
    「``inkflow write next|continue --show-context`` — 在写命令中打印本次组装的
      ContextAssemblyResult（人类可读或 ``--json`` 信封）」

实现约束（父侧裁定，见轨提示词 §4）:
    CLI 恒经 HTTP（Issue #169）→ **必须** 调既有 ``POST /context/assemble``
    （``api/routers/context.py:46``；CLI 无 DB 连接，不得本地 build_context）。
    路径相对 base_url（InkFlowHTTPClient base_url 已含 /api/v1）。

RED 形态：占位符恒在 → 断言「输出不含占位符且含真实上下文」必 FAIL。

测试基建形态镜像 tests/cli/test_cli_write_coverage.py（`_sse` = MagicMock 返回真
async generator —— AsyncMock 会返回 coroutine，`async for` 必炸）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.write import app
from inkflow.cli.context import CliContext

PID = "00000000-0000-0000-0000-000000000001"
CID = "00000000-0000-0000-0000-00000000000a"

_PLACEHOLDER = "--show-context 功能将在 F6 联调时启用"


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def _assembly_payload() -> dict:
    """ContextAssemblyResult 形态（domain/models/context.py:201）。"""
    return {
        "blocks": [
            {
                "layer": "protected",
                "source": "writing_requirements",
                "title": "写作要求",
                "content": "本章须体现医武不分家",
                "tokens": 12,
            }
        ],
        "budget_tokens": 8000,
        "total_tokens": 1234,
        "model": "claude-sonnet-4",
        "dropped": [],
    }


def _sse(*events: dict) -> MagicMock:
    """stream_sse mock：返回 async generator，逐条 yield SSE 事件 dict。"""

    async def _gen(*_args, **_kwargs):
        for ev in events:
            yield ev

    return MagicMock(return_value=_gen())


def _fake_handle() -> SimpleNamespace:
    return SimpleNamespace(
        port=38293,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（镜像 test_cli_write_coverage fixture）。"""
    with (
        patch(
            "inkflow.cli.commands.write.ensure_kernel",
            AsyncMock(return_value=_fake_handle()),
        ),
        patch("inkflow.cli.commands.write.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        mock_instance.stream_sse = _sse(
            {"done": False, "delta": "正文内容。"},
            {
                "done": True,
                "format_valid": True,
                "warnings": [],
                "word_count": 5,
                "model": "m",
            },
        )
        yield mock_instance


def _invoke(runner: CliRunner, *extra: str) -> object:
    return runner.invoke(
        app,
        [
            "next",
            "--project-id",
            PID,
            "--chapter-id",
            CID,
            "--outline",
            "大纲",
            "--show-context",
            *extra,
        ],
        obj=CliContext(),
    )


class TestWriteShowContext:
    def test_show_context_prints_real_assembly_not_placeholder(
        self, cli_runner: CliRunner, fake_http_client: AsyncMock
    ) -> None:
        """P2-b：--show-context 输出真实 ContextAssemblyResult（非占位符，f6 §6 L310）。"""
        fake_http_client.post.return_value = _assembly_payload()

        result = _invoke(cli_runner)

        assert result.exit_code == 0, result.output
        assert _PLACEHOLDER not in result.output, "仍打印占位符（功能未接）"
        # 真实上下文：token 数可见（blocks=1 / budget=8000 / total=1234）
        assert "1234" in result.output, f"--show-context 未打印真实 token 数：\n{result.output}"
        # 必须真的调过 /context/assemble（HTTP 轨，非本地组装）
        called_paths = [c.args[0] for c in fake_http_client.post.call_args_list if c.args]
        assert "/context/assemble" in called_paths, (
            f"未调用 /context/assemble（CLI 恒经 HTTP）：{called_paths}"
        )

    def test_show_context_json_envelope(
        self, cli_runner: CliRunner, fake_http_client: AsyncMock
    ) -> None:
        """P2-b：--json + --show-context → 信封含 context（f6 §6「或 --json 信封」）。"""
        fake_http_client.post.return_value = _assembly_payload()

        result = _invoke(cli_runner, "--json")

        assert result.exit_code == 0, result.output
        assert _PLACEHOLDER not in result.output, "仍打印占位符（功能未接）"
        payload = json.loads(result.output)
        data = payload.get("data", payload)
        assert "context" in data, f"--json 信封缺 context 字段：{list(data)}"
        assert data["context"]["total_tokens"] == 1234
