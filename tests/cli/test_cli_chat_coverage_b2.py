"""Coverage backfill batch 2: chat_cmd SSE 帧分派 + _run 错误映射。

镜像 tests/cli/test_cli_chat_981.py 的 fake_http_client 模式，全部经公开
``inkflow chat`` 命令驱动：
- tool_call / interrupt 帧人类模式输出（77/79-80 行）
- JSON 模式 interrupt 帧（79->67 弧）
- done 帧无 run_id -> 空 run 兜底（83->67 + 86-87 行）
- plain 端点 error 帧 -> LLM_ERROR（130-131 行）+ delta 人类输出（135-136 行）
- _run 错误映射：typer.Exit 透传（40-41）/ KernelStartupError（45-46）/
  ValidationError（47-49）/ 通用异常 → DB_ERROR（50-51）
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from pydantic import BaseModel, ValidationError
from typer.testing import CliRunner

from inkflow.cli.app import app
from inkflow.infrastructure.kernel import KernelStartupError


def _sse(frames: list[dict]):
    """stream_sse side_effect：调用返回 async generator，逐帧 yield dict。"""

    def _factory(*_args, **_kwargs):
        async def _gen():
            for frame in frames:
                yield frame

        return _gen()

    return _factory


@pytest.fixture
def cli_runner(monkeypatch):
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", False)
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """patch chat_cmd 命名空间 ensure_kernel + InkFlowHTTPClient -> fake client."""
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
            "inkflow.cli.commands.chat_cmd.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.chat_cmd.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get.return_value = {
            "id": "R1",
            "steps": [],
            "final_content": "ok",
            "token_usage_total": 0,
        }
        mock_instance.stream_sse = MagicMock(side_effect=_sse([]))
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_tool_call_and_interrupt_frames_human(cli_runner, fake_http_client) -> None:
    """人类模式 tool_call 帧打印工具名 + interrupt 帧打印确认提示（77/79-80）。"""
    pid = uuid.uuid4()
    fake_http_client.stream_sse = MagicMock(
        side_effect=_sse(
            [
                {"type": "run_started", "id": "R1"},
                {"type": "tool_call", "name": "search_knowledge"},
                {"type": "interrupt", "payload": {"q": "继续？"}},
                {"type": "done", "run_id": "R1"},
            ]
        )
    )

    result = cli_runner.invoke(app, ["chat", "hi", "--project", str(pid)])

    assert result.exit_code == 0
    assert "search_knowledge" in result.stdout
    assert "继续？" in result.stdout


def test_interrupt_frame_json_mode_skips_echo(cli_runner, fake_http_client) -> None:
    """JSON 模式 interrupt 帧不触发人类提示（79->67 弧，human=False）。"""
    pid = uuid.uuid4()
    fake_http_client.stream_sse = MagicMock(
        side_effect=_sse(
            [
                {"type": "run_started", "id": "R1"},
                {"type": "interrupt", "payload": {"q": "确认"}},
                {"type": "done", "run_id": "R1"},
            ]
        )
    )

    result = cli_runner.invoke(app, ["chat", "hi", "--project", str(pid), "--json"])

    assert result.exit_code == 0
    assert "确认" not in result.stdout


def test_done_frame_without_run_id_falls_back(cli_runner, fake_http_client) -> None:
    """done 帧无 run_id -> 空 run 兜底（83->67 + 86-87）。"""
    pid = uuid.uuid4()
    fake_http_client.stream_sse = MagicMock(
        side_effect=_sse(
            [
                {"type": "delta", "delta": "前半"},
                {"type": "done"},
            ]
        )
    )

    result = cli_runner.invoke(app, ["chat", "hi", "--project", str(pid), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert data["run_id"] == ""
    assert data["final_content"] == "前半"
    assert data["tool_calls"] == []


def test_plain_error_frame_maps_llm_error(cli_runner, fake_http_client) -> None:
    """plain 端点 error 帧 -> LLM_ERROR + exit 1（130-131）。"""
    pid = uuid.uuid4()
    fake_http_client.stream_sse = MagicMock(
        side_effect=_sse([{"error": "流式失败"}])
    )

    result = cli_runner.invoke(
        app, ["chat", "hi", "--project", str(pid), "--plain", "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "LLM_ERROR"


def test_plain_delta_human_prints_content(cli_runner, fake_http_client) -> None:
    """plain 端点人类模式逐 delta 输出（135-136）。"""
    pid = uuid.uuid4()
    fake_http_client.stream_sse = MagicMock(
        side_effect=_sse([{"delta": "清晨"}, {"delta": "薄雾"}, {"done": True}])
    )

    result = cli_runner.invoke(app, ["chat", "hi", "--project", str(pid), "--plain"])

    assert result.exit_code == 0
    assert "清晨薄雾" in result.stdout


def test_kernel_startup_error_maps_to_kernel_error(
    cli_runner, fake_http_client
) -> None:
    """ensure_kernel 抛 KernelStartupError -> KERNEL_ERROR + exit 1（45-46）。"""
    pid = uuid.uuid4()
    with patch(
        "inkflow.cli.commands.chat_cmd.ensure_kernel",
        AsyncMock(side_effect=KernelStartupError("内核起不来")),
    ):
        result = cli_runner.invoke(app, ["chat", "hi", "--project", str(pid)])

    assert result.exit_code == 1
    assert "内核启动失败" in result.output


def test_typer_exit_propagates_unchanged(cli_runner, fake_http_client) -> None:
    """协程内 typer.Exit 原样透传，不被 _run 重映射（40-41）。"""
    pid = uuid.uuid4()
    with patch(
        "inkflow.cli.commands.chat_cmd.ensure_kernel",
        AsyncMock(side_effect=typer.Exit(code=3)),
    ):
        result = cli_runner.invoke(
            app, ["chat", "hi", "--project", str(pid), "--json"]
        )

    assert result.exit_code == 3
    assert result.stdout.strip() == ""


def test_validation_error_maps_to_validation_error(
    cli_runner, fake_http_client
) -> None:
    """协程内 pydantic ValidationError -> VALIDATION_ERROR 信封（47-49）。"""

    class _Model(BaseModel):
        value: int

    try:
        _Model(value="not-int")  # type: ignore[arg-type]  # 故意构造非法输入触发 ValidationError
    except ValidationError as exc:
        raised = exc

    pid = uuid.uuid4()
    with patch(
        "inkflow.cli.commands.chat_cmd.ensure_kernel",
        AsyncMock(side_effect=raised),
    ):
        result = cli_runner.invoke(
            app, ["chat", "hi", "--project", str(pid), "--json"]
        )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "VALIDATION_ERROR"


def test_generic_exception_maps_to_db_error(cli_runner, fake_http_client) -> None:
    """HTTP 层外通用异常 -> DB_ERROR + exit 1（50-51）。"""
    pid = uuid.uuid4()
    fake_http_client.stream_sse = MagicMock(side_effect=RuntimeError("boom"))

    result = cli_runner.invoke(
        app, ["chat", "hi", "--project", str(pid), "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "DB_ERROR"
