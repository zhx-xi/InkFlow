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
from inkflow.cli.commands import agent_cmd, chapter, project, write  # noqa: E402

app.add_typer(project.app, name="project")
app.add_typer(chapter.volume_app, name="volume")
app.add_typer(chapter.chapter_app, name="chapter")
app.add_typer(write.app, name="write")
app.add_typer(agent_cmd.app, name="agent")


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="监听地址"),
    port: int = typer.Option(8765, "--port", "-p", help="监听端口"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="自动打开浏览器"),
) -> None:
    """启动 Web 服务"""
    import uvicorn

    if open_browser:
        import threading
        import webbrowser

        url = f"http://{host}:{port}/docs"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    typer.echo(f"🚀 InkFlow 服务启动于 http://{host}:{port}")
    typer.echo(f"📖 API 文档: http://{host}:{port}/docs")
    uvicorn.run("inkflow.api.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
