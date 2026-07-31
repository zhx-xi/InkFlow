"""CLI 输出格式化测试 — 信封/退出码/掩码."""

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    """Typer CliRunner fixture."""
    return CliRunner(mix_stderr=False)


@pytest.fixture
def cli_ctx_human():
    """人类可读模式 CliContext."""
    return CliContext(json_output=False)


@pytest.fixture
def cli_ctx_json():
    """JSON 模式 CliContext."""
    return CliContext(json_output=True)


# ── CliContext 单元测试 ──


class TestCliContext:
    def test_default_json_output_false(self):
        """默认 json_output 为 False."""
        ctx = CliContext()
        assert ctx.json_output is False

    def test_json_output_true(self):
        """显式设置 json_output=True."""
        ctx = CliContext(json_output=True)
        assert ctx.json_output is True

    def test_dataclass_equality(self):
        """两个相同值的 CliContext 相等."""
        a = CliContext(json_output=True)
        b = CliContext(json_output=True)
        assert a == b
