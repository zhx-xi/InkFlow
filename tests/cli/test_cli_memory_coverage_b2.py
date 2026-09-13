"""Coverage backfill batch 2: memory_cmd `summarize` 分支。

镜像 tests/cli/test_cli_memory.py 的 fake_http_client 模式，经公开
``inkflow memory summarize`` 驱动：
- 摘要已生成但项目级/用户级锚点未变 -> 两条「锚点未变化」提示（269/273）
- 内核 HTTP 返回 None -> 静默早退（252-253）
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.memory_cmd import app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner() -> CliRunner:
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
            "inkflow.cli.commands.memory_cmd.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.memory_cmd.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_summarize_reports_unchanged_project_and_user_anchors(
    cli_runner, fake_http_client
) -> None:
    """summarized=True 但无 project/user 载荷 -> 两级「锚点未变化」提示（266-273）。"""
    fake_http_client.post.return_value = {"summarized": True}

    result = cli_runner.invoke(
        app,
        ["summarize", "--project-id", str(uuid.uuid4())],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "项目级锚点未变化" in result.output
    assert "用户级锚点未变化" in result.output


def test_summarize_null_response_returns_early(cli_runner, fake_http_client) -> None:
    """summarize 内核返回 None -> 静默早退（252-253）。"""
    fake_http_client.post.return_value = None

    result = cli_runner.invoke(
        app,
        ["summarize", "--project-id", str(uuid.uuid4())],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == ""
    fake_http_client.post.assert_awaited_once()
