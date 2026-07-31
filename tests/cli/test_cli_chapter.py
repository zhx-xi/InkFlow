"""CLI 章节/卷命令集成测试 — CliRunner。

测试范围：inkflow chapter --help, inkflow volume --help。
需 pytest marker: @pytest.mark.chapter
"""

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app


class TestChapterCLI:
    """Chapter CLI 命令测试."""

    @pytest.mark.chapter
    def test_chapter_help(self):
        """inkflow chapter --help 正常."""
        runner = CliRunner()
        result = runner.invoke(app, ["chapter", "--help"])
        assert result.exit_code == 0
        assert "章节管理" in result.stdout

    @pytest.mark.chapter
    def test_volume_help(self):
        """inkflow volume --help 正常."""
        runner = CliRunner()
        result = runner.invoke(app, ["volume", "--help"])
        assert result.exit_code == 0
        assert "卷管理" in result.stdout
