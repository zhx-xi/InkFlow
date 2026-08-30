"""Coverage backfill: config CLI 错误分支（F32 spec §4/§7）。

镜像 tests/cli/test_cli_config.py：全部通过公开 ``inkflow config set`` 驱动：
- data-dir 空值 → CONFIG_ERROR exit 1
- save_instance_env OSError → CONFIG_ERROR exit 1
- 未知 key → CONFIG_ERROR exit 2
- 数值转换失败 → CONFIG_ERROR exit 1
"""

from __future__ import annotations

import importlib

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.config_cmd import app
from inkflow.cli.context import CliContext

core_config_mod = importlib.import_module("inkflow.core.config")


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(env={"NO_COLOR": "1"})


def test_set_data_dir_empty_invalid(cli_runner) -> None:
    result = cli_runner.invoke(
        app,
        ["set", "data-dir", "   "],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "数据目录不能为空" in result.output


def test_set_data_dir_oserror(cli_runner, monkeypatch, tmp_path) -> None:
    def _boom(_path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(core_config_mod, "save_instance_env", _boom)

    result = cli_runner.invoke(
        app,
        ["set", "data-dir", str(tmp_path / "data")],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "值不合法" in result.output


def test_set_unknown_key_exit_2(cli_runner) -> None:
    result = cli_runner.invoke(
        app,
        ["set", "foo.bar", "x"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 2
    assert "未知配置项" in result.output


def test_set_invalid_float_value(cli_runner) -> None:
    result = cli_runner.invoke(
        app,
        ["set", "default.temperature", "abc"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "值不合法" in result.output
