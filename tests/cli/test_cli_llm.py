"""LLM CLI 命令测试."""

import json
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


class TestLlmListErrors:
    def test_list_key_load_error(self, cli_runner, mock_key_manager):
        """km.load 异常 → key_status=error + key_masked=****（防御分支，spec §4.2）."""
        from inkflow.cli.commands.llm import app

        mock_key_manager.load.side_effect = RuntimeError("key 文件损坏")
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0]["provider"] == "deepseek"
        assert data["data"][0]["key_status"] == "error"
        assert data["data"][0]["key_masked"] == "****"


class TestLlmSetKeyErrors:
    def test_set_key_empty_exit_1(self, cli_runner, mock_key_manager):
        """--key 为空字符串 → VALIDATION_ERROR 信封 + 退出码 1."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["set-key", "--provider", "deepseek", "--key", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["message"] == "API Key 不能为空"
        mock_key_manager.store.assert_not_called()

    def test_set_key_blank_interactive(self, cli_runner, mock_key_manager, monkeypatch):
        """交互输入全空白 → VALIDATION_ERROR 信封 + 退出码 1（strip 校验分支）."""
        from inkflow.cli.commands.llm import app

        monkeypatch.setattr("inkflow.cli.commands.llm.getpass", lambda _: "   ")
        result = cli_runner.invoke(
            app,
            ["set-key", "--provider", "deepseek"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        mock_key_manager.store.assert_not_called()

    def test_set_key_store_error(self, cli_runner, mock_key_manager):
        """km.store 异常 → CONFIG_ERROR 信封 + 退出码 1."""
        from inkflow.cli.commands.llm import app

        mock_key_manager.store.side_effect = RuntimeError("磁盘写入失败")
        result = cli_runner.invoke(
            app,
            ["set-key", "--provider", "deepseek", "--key", "sk-xxx"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "CONFIG_ERROR"
        assert "磁盘写入失败" in data["error"]["message"]

    def test_set_key_json_success(self, cli_runner, mock_key_manager):
        """set-key --json 成功 → saved 信封 + store 透传（strip 后）."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["set-key", "--provider", "deepseek", "--key", "sk-json-key"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"] == {"provider": "deepseek", "status": "saved"}
        mock_key_manager.store.assert_called_once_with("deepseek", "sk-json-key")
