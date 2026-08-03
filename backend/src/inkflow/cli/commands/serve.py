"""Serve 命令 — `inkflow serve`."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(name="serve", help="启动 Web 服务", no_args_is_help=True)

# 模块级运行状态：非 reload 时 uvicorn 在后台线程中运行，serve 主线程输出
# INKFLOW_READY 交付行后 join 保活；Ctrl+C 经 _current_server 优雅关闭。
_server_thread: threading.Thread | None = None
_current_server: Any | None = None  # uvicorn.Server 引用，Ctrl+C 优雅关闭用


def _run_server(host: str, port: int, reload: bool) -> int:
    """启动 uvicorn 服务并返回实际监听端口。

    非 reload：后台线程运行 uvicorn，等待启动就绪（server.started）后返回
    端口——服务已在运行，serve 输出 INKFLOW_READY 交付行（真实时序修复，
    #77 load-bearing bug）。reload：uvicorn reload supervisor 需主线程语义
    （subprocess 管理），直接阻塞运行，无交付契约。
    """
    import socket
    import time

    import uvicorn

    actual_port = port
    if port == 0:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((host, 0))
        actual_port = sock.getsockname()[1]
        sock.close()

    config = uvicorn.Config(
        "inkflow.api.app:app",
        host=host,
        port=actual_port,
        reload=reload,
        log_level="info",
    )
    server = uvicorn.Server(config)

    if reload:
        server.run()  # 开发热重载：阻塞主线程；无交付契约（spec Q3）
        return actual_port

    global _server_thread, _current_server
    _current_server = server
    _server_thread = threading.Thread(target=server.run, name="inkflow-uvicorn", daemon=False)
    _server_thread.start()
    while not server.started:
        time.sleep(0.02)
    return actual_port


def _write_port_file(path: Path, payload: dict) -> None:
    """原子写入端口文件（先写临时文件再 os.replace，防壳读到半截 JSON）."""
    import json
    import os

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="监听地址"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口（0 = 系统动态分配）"),
    port_file: Path | None = typer.Option(None, "--port-file", help="交付端口文件路径（JSON）"),
    token: str | None = typer.Option(None, "--token", help="鉴权 token（缺省随机生成）"),
    open_browser: bool = typer.Option(False, "--open-browser", help="自动打开浏览器"),
    reload: bool = typer.Option(False, "--reload", help="开发模式热重载"),
) -> None:
    """启动 InkFlow Web 服务."""
    import json
    import os
    import secrets
    import threading
    import webbrowser

    from inkflow import __version__

    # token 解析：显式指定原样使用，缺省随机生成（每次启动不同）
    effective_token = token or secrets.token_urlsafe(32)
    # env 注入必须先于 _run_server：reload 子进程经 env 继承 token，校验保持启用
    os.environ["INKFLOW_SERVER_TOKEN"] = effective_token

    if open_browser:
        url = f"http://{host}:{port}/docs"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    typer.echo(f"🚀 InkFlow 服务启动于 http://{host}:{port}")

    actual_port = _run_server(host, port, reload)

    if not reload:
        payload = {
            "port": actual_port,
            "token": effective_token,
            "pid": os.getpid(),
            "version": __version__,
        }
        typer.echo(f"INKFLOW_READY {json.dumps(payload, ensure_ascii=False)}")
        if port_file is not None:
            _write_port_file(port_file, payload)

    if not reload and _server_thread is not None:
        try:
            _server_thread.join()
        except KeyboardInterrupt:
            # Ctrl+C：通知 uvicorn 优雅退出（主循环 tick 检查 should_exit）
            if _current_server is not None:
                _current_server.should_exit = True
            _server_thread.join(timeout=5)
