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


# ── 注册子命令 ──

from inkflow.cli.commands import (  # noqa: E402
    agent_cmd,
    chapter,
    character,
    outline,
    project,
    timeline,
    world,
    write,
)
from inkflow.cli.commands.config_cmd import app as config_app  # noqa: E402
from inkflow.cli.commands.llm import app as llm_app  # noqa: E402
from inkflow.cli.commands.serve import serve as _serve_fn  # noqa: E402

app.add_typer(project.app, name="project")
app.add_typer(character.app, name="character")
app.add_typer(world.app, name="world")
app.add_typer(outline.app, name="outline")
app.add_typer(timeline.app, name="timeline")
app.add_typer(chapter.chapter_app, name="chapter")
app.add_typer(chapter.volume_app, name="volume")
app.add_typer(write.app, name="write")
app.add_typer(llm_app, name="llm")
app.add_typer(config_app, name="config")
app.add_typer(agent_cmd.app, name="agent")
# serve 用 command() 直接注册避免 inkflow serve serve 嵌套
app.command(name="serve")(_serve_fn)
