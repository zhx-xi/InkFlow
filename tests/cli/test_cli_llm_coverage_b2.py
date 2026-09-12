"""Coverage backfill batch 2: llm_cmd provider update --force 查询参数。

镜像 tests/cli/test_cli_llm_coverage.py 的 patch 模式，经公开
``inkflow llm provider update --force`` 驱动：force 时 path 追加 ``?force=true``
（173-174 行）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.llm import app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(env={"NO_COLOR": "1"})


def test_provider_update_force_appends_query(cli_runner) -> None:
    """provider update --force -> PATCH /provider-configs/{id}?force=true（173-174）。"""
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
            "inkflow.cli.commands.llm.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.llm.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.patch.return_value = {"id": "p1", "name": "prov"}
        mock_cls.return_value = mock_instance

        result = cli_runner.invoke(
            app,
            ["provider", "update", "--id", "p1", "--force"],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0
    assert mock_instance.patch.await_args.args[0] == "/provider-configs/p1?force=true"
