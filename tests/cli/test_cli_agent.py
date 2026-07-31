"""CLI Agent 命令集成测试 — CliRunner。

测试范围：inkflow agent run/status/validate/template --help。
需 pytest marker: @pytest.mark.agent
"""

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

runner = CliRunner()


class TestAgentCLI:
    """Agent CLI 命令测试。"""

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """去除 ANSI 转义码（CI 环境 rich_markup_mode 会引入颜色码）。"""
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @pytest.mark.agent
    def test_agent_run_help(self):
        """inkflow agent run --help 输出帮助信息。"""
        result = runner.invoke(app, ["agent", "run", "--help"])
        assert result.exit_code == 0
        assert "--project-id" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_agent_status_help(self):
        """inkflow agent status --help 输出帮助。"""
        result = runner.invoke(app, ["agent", "status", "--help"])
        assert result.exit_code == 0
        assert "--run-id" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_agent_validate_help(self):
        """inkflow agent validate --help 输出帮助。"""
        result = runner.invoke(app, ["agent", "validate", "--help"])
        assert result.exit_code == 0
        assert "--file" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_agent_template_list_help(self):
        """inkflow agent template list --help。"""
        result = runner.invoke(app, ["agent", "template", "--help"])
        assert result.exit_code == 0
        assert "--json" in self._strip_ansi(result.stdout)
