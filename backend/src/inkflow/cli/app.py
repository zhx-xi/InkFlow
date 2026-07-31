"""InkFlow CLI 根应用 — `inkflow` 命令入口."""

from __future__ import annotations

import typer

from inkflow import __version__
from inkflow.cli.context import CliContext

app = typer.Typer(
    name="inkflow",
    help="InkFlow — AI 辅助小说创作工具",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    """--version/-V: 显示版本号并退出."""
    if value:
        typer.echo(f"InkFlow v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="输出 JSON 信封格式"),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="显示版本号并退出",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """InkFlow — AI 长篇小说创作工具."""
    ctx.obj = CliContext(json_output=json_output)
