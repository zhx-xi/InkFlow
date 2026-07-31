"""CLI 输出格式化 — 人类/JSON 双模式."""

from __future__ import annotations

import json
import sys
from typing import Any

import typer

from inkflow.cli.context import CliContext


def print_result(ctx: CliContext, data: Any) -> None:
    """输出成功结果.

    --json: 信封格式到 stdout
    人类模式: typer.echo 到 stdout
    """
    if ctx.json_output:
        json.dump({"ok": True, "data": data}, sys.stdout, ensure_ascii=False, indent=2)
        print()
    elif isinstance(data, str):
        typer.echo(data)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "id" in item and "name" in item:
                typer.echo(f"  [{item['id']}] {item['name']}")
            else:
                typer.echo(f"  {item}")
    elif isinstance(data, dict):
        for k, v in data.items():
            typer.echo(f"{k}: {v}")
    else:
        typer.echo(str(data))


def print_error(ctx: CliContext, code: str, message: str, exit_code: int = 1) -> None:
    """输出错误并退出.

    --json: 错误信封到 stdout
    人类模式: 错误消息到 stderr
    """
    if ctx.json_output:
        json.dump(
            {"ok": False, "error": {"code": code, "message": message}},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        print()
    else:
        typer.echo(f"❌ {message}", err=True)
    raise typer.Exit(code=exit_code)


def mask_key(key: str) -> str:
    """遮掩 API Key，仅显示前缀和后缀 4 位."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"
