"""CLI 输出格式化测试 — 信封/退出码/掩码."""

import io as _io
import json as _json
from contextlib import redirect_stdout as _redirect_stdout

import pytest
import typer as _typer
from typer.testing import CliRunner

from inkflow.cli.context import CliContext
from inkflow.cli.output import mask_key, print_error, print_result


@pytest.fixture
def cli_runner():
    """Typer CliRunner fixture."""
    return CliRunner()


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


# ── output.py 测试 ──


class TestPrintResult:
    def test_json_envelope(self, cli_ctx_json):
        """--json 模式输出信封."""
        buf = _io.StringIO()
        with _redirect_stdout(buf):
            print_result(cli_ctx_json, {"id": "abc"})
        output = _json.loads(buf.getvalue())
        assert output == {"ok": True, "data": {"id": "abc"}}

    def test_json_envelope_list(self, cli_ctx_json):
        """--json 模式输出列表信封."""
        buf = _io.StringIO()
        with _redirect_stdout(buf):
            print_result(cli_ctx_json, [{"id": "1", "name": "A"}])
        output = _json.loads(buf.getvalue())
        assert output["ok"] is True
        assert isinstance(output["data"], list)

    def test_human_string(self, cli_ctx_human, capsys):
        """人类模式字符串输出."""
        print_result(cli_ctx_human, "✅ 操作成功")
        captured = capsys.readouterr()
        assert "✅ 操作成功" in captured.out

    def test_human_list(self, cli_ctx_human, capsys):
        """人类模式列表输出."""
        data = [{"id": "1", "name": "test"}]
        print_result(cli_ctx_human, data)
        captured = capsys.readouterr()
        assert "test" in captured.out

    def test_human_dict(self, cli_ctx_human, capsys):
        """人类模式字典输出."""
        print_result(cli_ctx_human, {"key": "value"})
        captured = capsys.readouterr()
        assert "key" in captured.out


class TestPrintError:
    def test_json_envelope(self, cli_ctx_json):
        """--json 模式错误信封 + 退出码."""
        with pytest.raises(_typer.Exit) as exc:
            print_error(cli_ctx_json, "NOT_FOUND", "项目不存在", exit_code=1)
        assert exc.value.exit_code == 1

    def test_human_mode_stderr(self, cli_ctx_human, capsys):
        """人类模式错误输出到 stderr."""
        with pytest.raises(_typer.Exit):
            print_error(cli_ctx_human, "NOT_FOUND", "项目不存在")
        captured = capsys.readouterr()
        assert "❌ 项目不存在" in captured.err

    def test_default_exit_code(self, cli_ctx_json):
        """默认退出码为 1."""
        with pytest.raises(_typer.Exit) as exc:
            print_error(cli_ctx_json, "LLM_ERROR", "调用失败")
        assert exc.value.exit_code == 1


class TestMaskKey:
    def test_normal_key(self):
        """正常 Key 遮掩: sk-1234567890abcdef → sk-****cdef."""
        assert mask_key("sk-1234567890abcdef") == "sk-****cdef"

    def test_short_key(self):
        """短 Key 仅显示 ****."""
        assert mask_key("short") == "****"

    def test_empty_key(self):
        """空 Key 返回空字符串."""
        assert mask_key("") == ""


# ── Root App 测试 ──


class TestRootApp:
    def test_help_output(self, cli_runner):
        """inkflow --help 输出非空."""
        from inkflow.cli.app import app

        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "InkFlow" in result.output

    def test_version_output(self, cli_runner):
        """inkflow --version 输出版本号."""
        from inkflow.cli.app import app

        result = cli_runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "InkFlow" in result.output

    def test_no_args_shows_help(self, cli_runner):
        """无参数时显示 help 并退出码 2."""
        from inkflow.cli.app import app

        result = cli_runner.invoke(app, [])
        assert result.exit_code == 2

    def test_json_flag_sets_context(self, cli_runner):
        """--json 设置 ctx.obj.json_output=True."""
        from inkflow.cli.app import app

        # 使用 invoke 并检查 ctx.obj 需要通过 callback 间接验证
        # 这里验证 --json 选项能被解析
        result = cli_runner.invoke(app, ["--json", "--help"])
        assert result.exit_code == 0
