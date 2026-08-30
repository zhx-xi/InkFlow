"""Coverage backfill: write CLI 未覆盖分支（F3/F23 spec §4.1 + F27 agentic）。

镜像 tests/cli/test_cli_write.py 的 fake_http_client 模式：
- 无 ctx.obj（根 app 未注入 CliContext）→ _get_cli_ctx 兜底人类模式（43 行）
- 流无 done 帧 → 空结果兜底（101->99 弧，spec 防御语义）
- --mode agentic 无 draft_id → 「未生成草稿」（211 行）
- continue/revise 流内 error 帧 → LLM_ERROR（271/316 行）
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.write import app
from inkflow.cli.context import CliContext

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
CHAPTER_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


@pytest.fixture
def cli_runner(monkeypatch):
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", False)
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
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
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _sse(*events: dict) -> AsyncMock:
    """stream_sse mock：返回 async generator，逐条 yield SSE 事件 dict。"""

    async def _gen(*_args, **_kwargs):
        for ev in events:
            yield ev

    return MagicMock(return_value=_gen())


def test_next_without_obj_defaults_human_mode(
    cli_runner, fake_http_client
) -> None:
    """无 ctx.obj → CliContext() 兜底，人类模式输出（43 行）。"""
    fake_http_client.stream_sse = _sse(
        {"done": False, "delta": "正文"},
        {
            "done": True,
            "format_valid": True,
            "warnings": [],
            "word_count": 2,
            "model": "deepseek-v4-flash",
            "token_usage": {"total": 10},
        },
    )

    result = cli_runner.invoke(
        app,
        [
            "next",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
            "--outline",
            "第一章大纲",
        ],
    )

    assert result.exit_code == 0
    assert "章节生成成功" in result.output


def test_stream_without_done_frame_falls_back(
    cli_runner, fake_http_client
) -> None:
    """流仅 delta 无 done 帧 → 空结果兜底（101->99 弧）。"""
    fake_http_client.stream_sse = _sse({"done": False, "delta": "正文"})

    result = cli_runner.invoke(
        app,
        [
            "next",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
            "--outline",
            "第一章大纲",
            "--json",
        ],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert data["format_valid"] is False
    assert data["warnings"] == ["生成内容为空"]


def test_agentic_without_draft_prints_not_generated(
    cli_runner, fake_http_client
) -> None:
    """--mode agentic 响应无 draft_id/status → 「未生成草稿」（211 行）。"""
    fake_http_client.post = AsyncMock(
        return_value={
            "steps": [],
            "token_usage_total": 0,
            "terminated_by": "",
        }
    )

    result = cli_runner.invoke(
        app,
        [
            "next",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
            "--outline",
            "第一章大纲",
            "--mode",
            "agentic",
        ],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "未生成草稿" in result.output


def test_continue_error_frame_maps_llm_error(
    cli_runner, fake_http_client
) -> None:
    """continue 流内 error 帧 → LLM_ERROR + exit 1（271 行）。"""
    fake_http_client.get = AsyncMock(return_value={"content": "已有内容"})
    fake_http_client.stream_sse = _sse({"done": True, "error": "LLM 调用失败"})

    result = cli_runner.invoke(
        app,
        [
            "continue",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
        ],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "LLM 调用失败" in result.output


def test_revise_error_frame_maps_llm_error(cli_runner, fake_http_client) -> None:
    """revise 流内 error 帧 → LLM_ERROR + exit 1（316 行）。"""
    fake_http_client.get = AsyncMock(return_value={"content": "已有内容"})
    fake_http_client.stream_sse = _sse({"done": True, "error": "LLM 调用失败"})

    result = cli_runner.invoke(
        app,
        [
            "revise",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
            "--instruction",
            "改得更紧凑",
        ],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "LLM 调用失败" in result.output


def test_kernel_startup_error_maps_to_kernel_error(
    cli_runner, fake_http_client, monkeypatch
) -> None:
    """ensure_kernel 抛 KernelStartupError → KERNEL_ERROR 人类文案 + exit 1（43 行）。"""
    from inkflow.infrastructure.kernel import KernelStartupError

    monkeypatch.setattr(
        "inkflow.cli.commands.write.ensure_kernel",
        AsyncMock(side_effect=KernelStartupError("kernel boom")),
    )

    result = cli_runner.invoke(
        app,
        [
            "next",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
            "--outline",
            "第一章大纲",
        ],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "内核启动失败" in result.output


def test_agentic_tool_sequence_dedupes_and_skips_empty(
    cli_runner, fake_http_client
) -> None:
    """agentic steps 中重复/空 tool_name → 工具序列去重跳过（101->99 弧）。"""
    fake_http_client.post = AsyncMock(
        return_value={
            "status": "completed",
            "draft_id": "draft-1",
            "steps": [
                {"tool_calls": [{"tool_name": "read"}]},
                {"tool_calls": [{"tool_name": "read"}]},
                {"tool_calls": [{}]},
            ],
            "token_usage_total": 10,
            "terminated_by": "llm",
        }
    )

    result = cli_runner.invoke(
        app,
        [
            "next",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
            "--outline",
            "第一章大纲",
            "--mode",
            "agentic",
        ],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "工具: [read]" in result.output
