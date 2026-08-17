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

from inkflow.cli.commands import (  # noqa: E402  # app 定义后导入
    agent_cmd,
    audit,
    book_cmd,
    chapter,
    character,
    export,
    extract,
    foreshadowing,
    kernel,
    memory_cmd,
    outline,
    project,
    search,
    session,
    style,
    timeline,
    vector,
    world,
    write,
)
from inkflow.cli.commands.config_cmd import app as config_app  # noqa: E402  # app 定义后导入
from inkflow.cli.commands.context_cmd import app as context_app  # noqa: E402  # app 定义后导入
from inkflow.cli.commands.llm import app as llm_app  # noqa: E402  # app 定义后导入
from inkflow.cli.commands.map import app as map_app  # noqa: E402  # app 定义后导入
from inkflow.cli.commands.serve import serve as _serve_fn  # noqa: E402  # app 定义后导入
from inkflow.cli.commands.skill_cmd import app as skill_app  # noqa: E402  # app 定义后导入
from inkflow.cli.commands.skills import app as skills_app  # noqa: E402  # app 定义后导入

app.add_typer(project.app, name="project")
app.add_typer(character.app, name="character")
app.add_typer(world.app, name="world")
app.add_typer(map_app, name="map")
app.add_typer(outline.app, name="outline")
app.add_typer(timeline.app, name="timeline")
app.add_typer(foreshadowing.app, name="foreshadowing")
app.add_typer(export.app, name="export")
app.add_typer(extract.app, name="extract")
app.add_typer(audit.app, name="audit")
app.add_typer(style.app, name="style")
app.add_typer(vector.app, name="vector")
app.add_typer(chapter.chapter_app, name="chapter")
app.add_typer(chapter.volume_app, name="volume")
app.add_typer(write.app, name="write")
app.add_typer(llm_app, name="llm")
app.add_typer(config_app, name="config")
app.add_typer(agent_cmd.app, name="agent")
app.add_typer(book_cmd.app, name="book")
app.add_typer(session.app, name="session")
app.add_typer(kernel.app, name="kernel")
app.add_typer(memory_cmd.app, name="memory")
app.add_typer(context_app, name="context")
app.add_typer(skill_app, name="skill")
app.add_typer(skills_app, name="skills")
# serve 用 command() 直接注册避免 inkflow serve serve 嵌套
app.command(name="serve")(_serve_fn)
# search 同款：单命令组压平，command() 直接注册避免 inkflow search search 嵌套
app.command(name="search")(search.search_cmd)
