"""Coverage backfill batch 2: session_cmd `_run` 返回 None 的 NOT_FOUND 守卫。

镜像 tests/cli/test_cli_session_coverage.py 的 fake_http_client 模式，经公开
``inkflow session`` 子命令驱动：内核 HTTP 返回空响应（None）时，get/update/restore
必须落到 NOT_FOUND + 退出码 1（303/357/609 行）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.session import app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """patch ensure_kernel + InkFlowHTTPClient（命令模块命名空间）-> fake client。"""
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
            "inkflow.cli.commands.session.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.session.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_get_null_response_maps_not_found(cli_runner, fake_http_client) -> None:
    """GET /sessions/{id} 返回 None -> NOT_FOUND + exit 1（302-303）。"""
    fake_http_client.get.return_value = None

    result = cli_runner.invoke(
        app,
        ["get", "--id", str(uuid.uuid4())],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 1
    assert "NOT_FOUND" in result.stdout


def test_update_null_response_maps_not_found(cli_runner, fake_http_client) -> None:
    """PATCH /sessions/{id} 返回 None -> NOT_FOUND + exit 1（356-357）。"""
    fake_http_client.patch.return_value = None

    result = cli_runner.invoke(
        app,
        ["update", "--id", str(uuid.uuid4()), "--title", "新标题"],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 1
    assert "NOT_FOUND" in result.stdout


def test_restore_null_response_maps_not_found(cli_runner, fake_http_client) -> None:
    """POST /sessions/{id}/restore 返回 None -> NOT_FOUND + exit 1（608-609）。"""
    fake_http_client.post.return_value = None

    result = cli_runner.invoke(
        app,
        ["restore", "--id", str(uuid.uuid4())],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 1
    assert "NOT_FOUND" in result.stdout
