"""InkFlow CLI 根应用 — `inkflow` 命令入口."""

from __future__ import annotations

import sys

import typer

from inkflow import __version__
from inkflow.cli.context import CliContext
from inkflow.cli.log_bridge import cli_log_sink

_JSON_GLOBAL_HINT = "--json 是全局选项，请放在子命令前（如 inkflow --json config show）"


def _has_misplaced_json(args: list[str]) -> bool:
    """True if a --json token appears AFTER the command word(s) (non-option tokens)."""
    seen_non_option = False
    for arg in args:
        if arg == "--json":
            if seen_non_option:
                return True
        elif not arg.startswith("-"):
            seen_non_option = True
    return False


class _JsonHintGroup(typer.main.TyperGroup):
    """#865: when --json is misplaced after a subcommand, show a friendly hint.

    Only fires when the resolved leaf command does NOT declare its own `--json`
    option (so `agent status --json`, `book plan start X --json`, ... keep working).
    """

    def _leaf_declares_json(self, args: list[str]) -> bool:
        """Walk the command tree to the deepest command named by non-option tokens.

        Return True if that leaf command (or group) declares its own `--json` param.
        """
        node: object = self
        for arg in args:
            if arg.startswith("-"):
                continue
            sub = getattr(node, "commands", {}).get(arg)
            if sub is None:
                break
            node = sub
        for param in getattr(node, "params", []):
            if "--json" in (getattr(param, "opts", None) or []):
                return True
        return False

    def main(
        self,
        args=None,
        prog_name=None,
        complete_var=None,
        standalone_mode=True,
        windows_expand_args=True,
        **extra,
    ):
        scan_args = list(args) if args is not None else list(sys.argv[1:])
        if _has_misplaced_json(scan_args) and not self._leaf_declares_json(scan_args):
            if standalone_mode:
                typer.echo(f"❌ {_JSON_GLOBAL_HINT}", err=True)
                raise SystemExit(2)
            import click

            raise click.UsageError(_JSON_GLOBAL_HINT)
        # #942: CLI 会话主体包在 cli_log_sink 内转发内核（SystemExit/异常路径
        # 同样触发退出 flush；隔离性：子 app 直接 CliRunner 不经本入口 → 零 patch）
        with cli_log_sink():
            return super().main(
                args, prog_name, complete_var, standalone_mode, windows_expand_args, **extra
            )


app = typer.Typer(
    name="inkflow",
    help="InkFlow — AI 辅助小说创作工具",
    no_args_is_help=True,
    rich_markup_mode="rich",
    cls=_JsonHintGroup,
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
    knowledge_graph,
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
app.add_typer(knowledge_graph.app, name="knowledge")
app.add_typer(memory_cmd.app, name="memory")
app.add_typer(context_app, name="context")
app.add_typer(skill_app, name="skill")
app.add_typer(skills_app, name="skills")
# serve 用 command() 直接注册避免 inkflow serve serve 嵌套
app.command(name="serve")(_serve_fn)
# search 同款：单命令组压平，command() 直接注册避免 inkflow search search 嵌套
app.command(name="search")(search.search_cmd)
