"""#1485 提取 CLI 新参数与回滚命令契约（RED）—— `extract run --granularity/--dry-run`
与 `extract rollback`。

RED 预期（实现前必须 FAIL）:
- ``--granularity`` 未定义 → 退出码 2（Typer 未知选项）
- ``--dry-run`` 未定义 → 退出码 2
- ``rollback`` 子命令不存在 → 退出码 2

依据: specs/f14-extraction/spec.md §4.1 + §5.8.3-§5.8.5（#1485）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.extract import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 无 mix_stderr）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（F38 HTTP 轨）。"""
    fake_handle = SimpleNamespace(
        port=38291, token="test-token", pid=1, version="0.1.0", started_at="", reused=True
    )
    with (
        patch(
            "inkflow.cli.commands.extract.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.extract.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _json_response(**overrides: object) -> dict:
    """构造统一提取结果信封（默认 setting 成功态）。"""
    payload: dict[str, object] = {
        "type": "setting",
        "status": "success",
        "skipped_reason": None,
        "processed_sources": 1,
        "skipped_sources": 0,
        "created": 2,
        "updated": 1,
        "warnings": [],
        "model": "openai/gpt-4o",
        "indexed": False,
        "batch_id": "ext-batch-1",
        "detail": {},
    }
    payload.update(overrides)
    return payload


def test_run_passes_granularity_and_dry_run(cli_runner, fake_http_client) -> None:
    """`extract run --granularity coarse --dry-run` → body 携带两字段。"""
    fake_http_client.post = AsyncMock(return_value=_json_response())

    result = cli_runner.invoke(
        app,
        [
            "run",
            "--project-id",
            str(PID),
            "--type",
            "setting",
            "--text",
            "第一章",
            "--granularity",
            "coarse",
            "--dry-run",
        ],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0, result.output
    body = fake_http_client.post.await_args.kwargs["json"]
    assert body["granularity"] == "coarse"
    assert body["dry_run"] is True


def test_run_defaults_are_backward_compatible(cli_runner, fake_http_client) -> None:
    """反向守护：不传新参数 → fine / dry_run=False（既有行为不变）。"""
    fake_http_client.post = AsyncMock(return_value=_json_response())

    result = cli_runner.invoke(
        app,
        ["run", "--project-id", str(PID), "--type", "setting", "--text", "第一章"],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0, result.output
    body = fake_http_client.post.await_args.kwargs["json"]
    assert body["granularity"] == "fine"
    assert body["dry_run"] is False


def test_rollback_command_posts_batch_id(cli_runner, fake_http_client) -> None:
    """`extract rollback --batch-id` → POST 到 rollback 端点并回显删除计数。"""
    fake_http_client.post = AsyncMock(
        return_value={"batch_id": "ext-batch-1", "deleted": 3, "warnings": []}
    )

    result = cli_runner.invoke(
        app,
        ["rollback", "--project-id", str(PID), "--batch-id", "ext-batch-1"],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0, result.output
    url = fake_http_client.post.await_args.args[0]
    assert url == f"/projects/{PID}/extractions/rollback"
    assert fake_http_client.post.await_args.kwargs["json"] == {"batch_id": "ext-batch-1"}


def test_rollback_requires_batch_id(cli_runner, fake_http_client) -> None:
    """缺 --batch-id → 退出码 2（Typer 必填）。"""
    fake_http_client.post = AsyncMock(return_value={})

    result = cli_runner.invoke(
        app, ["rollback", "--project-id", str(PID)], obj=CliContext(json_output=True)
    )

    assert result.exit_code == 2
