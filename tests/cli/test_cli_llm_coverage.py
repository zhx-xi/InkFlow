"""Coverage backfill: llm CLI KernelStartupError 分支（F7 错误映射）。

``llm provider list`` 时 ensure_kernel 抛 KernelStartupError → KERNEL_ERROR + exit 1
（llm.py _run 46-47 行）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.llm import app
from inkflow.cli.context import CliContext
from inkflow.infrastructure.kernel import KernelStartupError


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_provider_list_kernel_startup_error(cli_runner) -> None:
    with patch(
        "inkflow.cli.commands.llm.ensure_kernel",
        AsyncMock(side_effect=KernelStartupError("kernel boom")),
    ):
        result = cli_runner.invoke(
            app,
            ["provider", "list"],
            obj=CliContext(json_output=False),
        )

    assert result.exit_code == 1
    assert "内核启动失败" in result.output
