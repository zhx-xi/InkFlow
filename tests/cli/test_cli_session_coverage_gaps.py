"""Coverage backfill: session CLI 非法 UUID → NOT_FOUND（F24 spec §7）。

`session get --id 非UUID` → _parse_uuid 打印 NOT_FOUND 并退出 1。
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.session import app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    return CliRunner(env={"NO_COLOR": "1"})


def test_get_invalid_uuid_maps_to_not_found(cli_runner) -> None:
    result = cli_runner.invoke(
        app,
        ["get", "--id", "not-a-uuid"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "会话不存在" in result.output
