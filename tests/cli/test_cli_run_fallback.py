"""CLI _run 兜底分支直测 — F38 #169 覆盖率补测。

Coverage-Gap 补测（2026-08-09）：命令模块 `_run(cli_ctx, coro_fn)` 统一辅助函数的
防御性兜底分支（ValidationError → VALIDATION_ERROR / FileNotFoundError →
VALIDATION_ERROR / Exception → DB_ERROR）在 mock CLI 测试中未触达。直接构造
coro_fn 抛对应异常断言映射。

⚠️ 分支归属（2026-08-09 源码核实，参数化只测实际存在的分支）：
- 仅 HttpApiError/KernelStartupError：project / agent_cmd / write
- +Exception：chapter
- +ValidationError+Exception：audit / timeline / vector / session / foreshadowing
- 全兜底（+ValidationError+FileNotFoundError+Exception）：
  character / extract / outline / style / world

GREEN 实现契约（backend/src/inkflow/cli/commands/ 各模块 _run）：
- except ValidationError as e →
  print_error(cli_ctx, "VALIDATION_ERROR", "; ".join(msg))
- except FileNotFoundError as e →
  print_error(cli_ctx, "VALIDATION_ERROR", f"文本文件不存在: {e.filename}")
- except Exception as e → print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")
"""

from __future__ import annotations

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from inkflow.cli.commands import (
    audit,
    chapter,
    character,
    foreshadowing,
    outline,
    style,
    timeline,
    vector,
    world,
)
from inkflow.cli.commands import extract as extract_mod
from inkflow.cli.commands import session as session_mod
from inkflow.cli.context import CliContext

runner = CliRunner()

# 分支归属表（源码核实 2026-08-09）
_HAS_VALIDATION = [
    character,
    extract_mod,
    outline,
    style,
    world,
    timeline,
    vector,
    session_mod,
    foreshadowing,
]
_HAS_FILE_NOT_FOUND = [character, extract_mod, outline, style, world]
_HAS_EXCEPTION = [
    character,
    extract_mod,
    outline,
    style,
    world,
    audit,
    timeline,
    vector,
    session_mod,
    foreshadowing,
    chapter,
]


def _raise(exc):
    async def _boom():
        raise exc

    return _boom


@pytest.fixture
def cli_ctx():
    return CliContext(json_output=True)


@pytest.mark.parametrize(
    "mod",
    _HAS_VALIDATION,
    ids=[m.__name__.rsplit(".", 1)[-1] for m in _HAS_VALIDATION],
)
def test_run_validation_error(mod, cli_ctx, capsys):
    """coro_fn 抛 ValidationError → VALIDATION_ERROR 信封 + 退出码 1。"""
    exc = ValidationError.from_exception_data("x", [])
    with pytest.raises(typer.Exit) as exc_info:
        mod._run(cli_ctx, _raise(exc))
    assert exc_info.value.exit_code == 1
    out = capsys.readouterr().out
    assert '"code": "VALIDATION_ERROR"' in out


@pytest.mark.parametrize(
    "mod",
    _HAS_FILE_NOT_FOUND,
    ids=[m.__name__.rsplit(".", 1)[-1] for m in _HAS_FILE_NOT_FOUND],
)
def test_run_file_not_found(mod, cli_ctx, capsys):
    """coro_fn 抛 FileNotFoundError → VALIDATION_ERROR「文本文件不存在」。"""
    with pytest.raises(typer.Exit) as exc_info:
        mod._run(cli_ctx, _raise(FileNotFoundError("missing.txt")))
    assert exc_info.value.exit_code == 1
    out = capsys.readouterr().out
    assert '"code": "VALIDATION_ERROR"' in out
    assert "文本文件不存在" in out


@pytest.mark.parametrize(
    "mod",
    _HAS_EXCEPTION,
    ids=[m.__name__.rsplit(".", 1)[-1] for m in _HAS_EXCEPTION],
)
def test_run_exception_db_error(mod, cli_ctx, capsys):
    """coro_fn 抛任意异常 → DB_ERROR 信封 + 退出码 1。"""
    with pytest.raises(typer.Exit) as exc_info:
        mod._run(cli_ctx, _raise(RuntimeError("boom")))
    assert exc_info.value.exit_code == 1
    out = capsys.readouterr().out
    assert '"code": "DB_ERROR"' in out
    assert "boom" in out


@pytest.mark.parametrize(
    "mod",
    _HAS_VALIDATION,
    ids=[m.__name__.rsplit(".", 1)[-1] for m in _HAS_VALIDATION],
)
def test_run_typer_exit_passthrough(mod, cli_ctx, capsys):
    """typer.Exit 透传（不吞掉退出码 2 的用法错误）。"""
    with pytest.raises(typer.Exit) as exc_info:
        mod._run(cli_ctx, _raise(typer.Exit(code=2)))
    assert exc_info.value.exit_code == 2
