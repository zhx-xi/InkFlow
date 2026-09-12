"""Coverage backfill batch 2: write_cmd `data is None` 早退分支。

镜像 tests/cli/test_cli_write_coverage.py 的 fake_http_client 模式：agentic
端点返回空响应（None）时 ``write next`` 静默早退（219-220 行）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.write import app
from inkflow.cli.context import CliContext

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
CHAPTER_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


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
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_agentic_null_response_returns_early(cli_runner, fake_http_client) -> None:
    """agentic 端点返回 None -> results is None 早退（219-220）。"""
    fake_http_client.post = AsyncMock(return_value=None)

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
            "--json",
        ],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == ""
    fake_http_client.post.assert_awaited_once()
    assert fake_http_client.post.await_args.args[0] == "/writing/agentic/generate"
