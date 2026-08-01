"""Serve CLI 命令测试."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_runner():
    return CliRunner()


class TestServe:
    # typer 0.27 会把「单命令 + 无 callback」的 Typer 实例压平为命令本身
    # （get_command 返回 TyperCommand 而非 TyperGroup），因此直接 invoke
    # 不再需要 "serve" 子命令参数：invoke(app, []) 即执行 serve 命令。
    def test_serve_defaults(self, cli_runner):
        """serve 默认参数."""
        from inkflow.cli.commands.serve import app

        with patch("uvicorn.run") as mock_run:
            result = cli_runner.invoke(app, [])
            assert result.exit_code == 0
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["host"] == "127.0.0.1"
            assert call_kwargs["port"] == 8000

    def test_serve_custom_host_port(self, cli_runner):
        """serve 自定义 host/port."""
        from inkflow.cli.commands.serve import app

        with patch("uvicorn.run") as mock_run:
            result = cli_runner.invoke(app, ["--host", "0.0.0.0", "--port", "9999"])
            assert result.exit_code == 0
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["host"] == "0.0.0.0"
            assert call_kwargs["port"] == 9999

    def test_serve_open_browser(self, cli_runner):
        """serve --open-browser 注册 webbrowser 定时任务（Timer 被 mock 不会真开浏览器）."""
        from inkflow.cli.commands.serve import app

        with patch("uvicorn.run") as mock_run:
            with patch("threading.Timer") as mock_timer, patch("webbrowser.open") as mock_wb:
                result = cli_runner.invoke(app, ["--open-browser"])
                assert result.exit_code == 0
                mock_run.assert_called_once()
                mock_timer.assert_called_once()
                mock_wb.assert_not_called()
