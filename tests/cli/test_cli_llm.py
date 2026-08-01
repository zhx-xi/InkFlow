"""LLM CLI 命令测试."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    # click 8.4 / typer 0.27 已移除 mix_stderr 参数，默认混合输出
    return CliRunner()


@pytest.fixture
def mock_key_manager():
    with patch("inkflow.cli.commands.llm.APIKeyManager", autospec=True) as mock_cls:
        mock_km = MagicMock()
        mock_km.list_providers.return_value = ["deepseek", "openai"]
        mock_km.load.return_value = "sk-test1234abcd"
        mock_cls.return_value = mock_km
        yield mock_km


class TestLlmList:
    def test_list_json(self, cli_runner, mock_key_manager):
        """llm list --json."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=True))
        assert result.exit_code == 0

    def test_list_human(self, cli_runner, mock_key_manager):
        """llm list 人类模式."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=False))
        assert result.exit_code == 0


class TestLlmSetKey:
    def test_set_key_interactive(self, cli_runner, mock_key_manager, monkeypatch):
        """set-key 交互输入."""
        from inkflow.cli.commands.llm import app

        monkeypatch.setattr("inkflow.cli.commands.llm.getpass", lambda _: "sk-test-key")
        result = cli_runner.invoke(
            app,
            ["set-key", "--provider", "deepseek"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        mock_key_manager.store.assert_called_once_with("deepseek", "sk-test-key")

    def test_set_key_cli_warning(self, cli_runner, mock_key_manager):
        """--key 明文参数输出 WARNING."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["set-key", "--provider", "deepseek", "--key", "sk-plain"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "WARNING" in result.output or "警告" in result.output
