"""Serve 命令 — `inkflow serve`."""

from __future__ import annotations

import typer

app = typer.Typer(name="serve", help="启动 Web 服务", no_args_is_help=True)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="监听地址"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口"),
    open_browser: bool = typer.Option(False, "--open-browser", help="自动打开浏览器"),
    reload: bool = typer.Option(False, "--reload", help="开发模式热重载"),
) -> None:
    """启动 InkFlow Web 服务."""
    import uvicorn

    if open_browser:
        import threading
        import webbrowser

        url = f"http://{host}:{port}/docs"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    typer.echo(f"🚀 InkFlow 服务启动于 http://{host}:{port}")
    typer.echo(f"📖 API 文档: http://{host}:{port}/docs")
    uvicorn.run("inkflow.api.app:app", host=host, port=port, reload=reload, log_level="info")
