"""InkFlow CLI 入口点 — `inkflow <command>`"""

import typer

from inkflow import __version__

app = typer.Typer(
    name="inkflow",
    help="InkFlow — AI 辅助小说创作工具",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"InkFlow v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="显示版本号并退出",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """InkFlow — AI 辅助小说创作工具"""
    pass


# ---- 注册子命令 ----
from inkflow.cli.commands import project  # noqa: E402

app.add_typer(project.app, name="project")


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="监听地址"),
    port: int = typer.Option(8765, "--port", "-p", help="监听端口"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="自动打开浏览器"),
) -> None:
    """启动 Web 服务"""
    typer.echo(f"🚀 InkFlow 服务启动于 http://{host}:{port}")


if __name__ == "__main__":
    app()
