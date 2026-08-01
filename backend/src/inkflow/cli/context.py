"""CLI 上下文 — 跨命令共享状态."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CliContext:
    """CLI 命令间共享的上下文.

    由根 app callback 创建，通过 typer.Context.obj 传递给各子命令。
    """

    json_output: bool = False
    """True 时所有命令输出 JSON 信封格式."""
