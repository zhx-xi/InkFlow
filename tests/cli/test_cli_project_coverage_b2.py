"""Coverage backfill batch 2: project_cmd 未覆盖分支。

镜像 tests/cli/test_cli_project.py 的 fake_http_client 模式，经公开
``inkflow project`` 子命令驱动：
- restore --json -> 包装输出成功信封（216-217）
- delete 无 --force 且确认「y」-> 继续执行删除（177->181）
- update --config k=nan -> nan/inf 保持字符串而非 float（236->240）
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.project import app
from inkflow.cli.context import CliContext


def _project_dict() -> dict:
    return {
        "id": "1",
        "name": "测试小说",
        "tags": ["玄幻"],
        "language": "zh-CN",
        "target_words": 100000,
        "is_deleted": False,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


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
            "inkflow.cli.commands.project.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.project.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_restore_json_envelope(cli_runner, fake_http_client) -> None:
    """restore --json -> 成功信封（216-217）。"""
    fake_http_client.post.return_value = _project_dict()

    result = cli_runner.invoke(
        app,
        ["restore", "--id", "1"],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["data"]["name"] == "测试小说"


def test_delete_confirmed_proceeds(cli_runner, fake_http_client) -> None:
    """delete 无 --force 但确认「y」-> 继续执行删除（177->181）。"""
    fake_http_client.delete.return_value = None

    result = cli_runner.invoke(
        app,
        ["delete", "--id", "1"],
        obj=CliContext(json_output=False),
        input="y\n",
    )

    assert result.exit_code == 0
    assert "#1" in result.output
    fake_http_client.delete.assert_awaited_once()


def test_update_config_nan_kept_as_string(cli_runner, fake_http_client) -> None:
    """update --config k=nan -> nan 保持字符串，不转 float（236->240）。"""
    fake_http_client.patch.return_value = _project_dict()

    result = cli_runner.invoke(
        app,
        ["update", "--id", "1", "--config", "ratio=nan"],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0
    body = fake_http_client.patch.await_args.kwargs["json"]
    assert body["config"] == {"ratio": "nan"}
