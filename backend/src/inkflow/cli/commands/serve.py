"""Serve 命令 — `inkflow serve`."""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

import typer

from inkflow.logging import instrument

app = typer.Typer(name="serve", help="启动 Web 服务", no_args_is_help=True)

# 模块级运行状态：非 reload 时 uvicorn 在后台线程中运行，serve 主线程输出
# INKFLOW_READY 交付行后 join 保活；Ctrl+C 经 _current_server 优雅关闭。
_server_thread: threading.Thread | None = None
_current_server: Any | None = None  # uvicorn.Server 引用，Ctrl+C 优雅关闭用
# #1487 / ADR-066 ①：存活期互斥句柄由**本（内核）进程**持有到退出（模块级保活，
# 防被 GC 回收；绝不释放 —— 随进程退出由 OS 回收）。
_lifetime_mutex_handle: object | None = None
# #1487 / ADR-066 ②：空闲回收看门狗（阈值未设置时为 None）
_idle_watchdog: Any | None = None


# ── 装配缝（测试 patch 点）──────────────────────────────────────────────


def _acquire_kernel_lifetime_mutex(kind: str, state_file: Path) -> object | None:
    """内核自持存活期互斥（ADR-066 ①）：成功 → 句柄（须持有到进程退出）；被占 → None。"""
    from inkflow.infrastructure.kernel.bootstrap import hold_lifetime_mutex

    return hold_lifetime_mutex(kind, state_file)


def _write_kernel_registry(kind: str, state_file: Path, payload: dict) -> None:
    """内核自注册（ADR-066 ③）：`<kind>-<pid>.json` 写进按 kind 分域的注册表目录。"""
    from inkflow.infrastructure.kernel import registry

    entry = {"kind": kind, "data_dir": str(state_file.parent), **payload}
    registry.write_instance(entry, registry.registry_dir_for(kind, state_file))


def _write_gui_record() -> None:
    """GUI **内置内核**形态 → 自登记 GUI exe 到机器级 `gui.json`（#1537）；其它形态 no-op。

    判定只看内核自身 exe 路径（`resources/kernel/` 下的形态 = GUI spawn 的），
    故 CLI zip / venv / 手工 serve 一律不写（**测试环境天然零副作用**）。
    """
    from inkflow.infrastructure.kernel import registry

    gui = registry.detect_bundled_gui_exe()
    if gui is not None:
        registry.record_bundled_gui(gui)


def _remove_kernel_registry(kind: str, state_file: Path, pid: int) -> None:
    """内核退出时自删注册条目（幂等；ADR-066 ③）。"""
    from inkflow.infrastructure.kernel import registry

    registry.remove_instance(registry.registry_dir_for(kind, state_file), kind=kind, pid=pid)


def _start_idle_watchdog(timeout: float, on_idle: Any) -> Any:
    """启动空闲看门狗（ADR-066 ②）：空闲超阈 → on_idle()（置 server.should_exit）。"""
    from inkflow.infrastructure.kernel.idle_reclaim import activity_tracker, start_idle_watchdog

    return start_idle_watchdog(activity_tracker(), timeout, on_idle=on_idle)


def _run_server(host: str, port: int, reload: bool, debug: bool = False) -> int:
    """启动 uvicorn 服务并返回实际监听端口。

    非 reload：后台线程运行 uvicorn，等待启动就绪（server.started）后返回
    端口——服务已在运行，serve 输出 INKFLOW_READY 交付行（真实时序修复，
    #77 load-bearing bug）。reload：uvicorn reload supervisor 需主线程语义
    （subprocess 管理），直接阻塞运行，无交付契约。

    Args:
        debug: F51 debug 模式 → uvicorn log_level="debug"（否则 "info"）。
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

    log_level = "debug" if debug else "info"
    # #1477 1.4：uvicorn 的 access/error 走 Loguru 桥 → 落进自管理内核日志（可轮转）；
    # 否则它们走 stderr → 被 _spawn_kernel 重定向进引导日志（绕过轮转）。
    from inkflow.infrastructure.kernel.kernel_logging import uvicorn_log_config

    config = uvicorn.Config(
        "inkflow.api.app:app",
        host=host,
        port=actual_port,
        reload=reload,
        log_level=log_level,
        log_config=uvicorn_log_config(level=log_level),
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
@instrument(caller_type="cli")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="监听地址"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口（0 = 系统动态分配）"),
    port_file: Path | None = typer.Option(None, "--port-file", help="交付端口文件路径（JSON）"),
    token: str | None = typer.Option(None, "--token", help="鉴权 token（缺省随机生成）"),
    open_browser: bool = typer.Option(False, "--open-browser", help="自动打开浏览器"),
    reload: bool = typer.Option(False, "--reload", help="开发模式热重载"),
    debug: bool = typer.Option(
        False, "--debug", help="Debug 模式（等价 INKFLOW_DEBUG=1；env 优先）"
    ),
) -> None:
    """启动 InkFlow Web 服务."""
    import json
    import os
    import secrets
    import threading
    import webbrowser

    from inkflow import __version__
    from inkflow.core.config import config
    from inkflow.infrastructure.kernel.bootstrap import (
        KERNEL_CONFLICT_EXIT_CODE,
        KERNEL_CONFLICT_LINE,
        _default_state_file,
    )
    from inkflow.infrastructure.kernel.idle_reclaim import (
        activity_tracker,
        resolve_idle_timeout,
    )
    from inkflow.infrastructure.kernel.instance_kind import resolve_instance_kind

    # ── 内核准入（#1487 / ADR-066 ①）：存活期互斥由**内核进程自持** ──────────
    # 任何路径（GUI spawn / CLI / MCP / 手工 serve）拉起的同 kind 内核都撞同一互斥
    # → 「机器级限 1」名实相符；拿不到 → 退出码 3（拉起方据此报既有实例 / 先停旧起新）。
    global _lifetime_mutex_handle, _idle_watchdog
    kernel_kind = resolve_instance_kind()
    kernel_state_file = port_file or _default_state_file()
    _lifetime_mutex_handle = _acquire_kernel_lifetime_mutex(kernel_kind, kernel_state_file)
    if _lifetime_mutex_handle is None:
        conflict = {"kind": kernel_kind, "data_dir": str(kernel_state_file.parent)}
        typer.echo(f"{KERNEL_CONFLICT_LINE} {json.dumps(conflict, ensure_ascii=False)}")
        raise typer.Exit(code=KERNEL_CONFLICT_EXIT_CODE)

    is_debug = config.debug or debug

    # S3f-T1 G2（#869）：debug 态必须回写 config 单例 + 进程 env——uvicorn
    # import-string 首次 import app / reload 子进程继承；docs 门控按 config.debug
    # 每次请求运行时判定，不回写则 flag/env 态自动打开的 /docs 404 死链。
    # 非 debug 路径不回写（随机 token / info 级别 / 既有契约零破坏）。
    if is_debug:
        config.debug = True
        os.environ["INKFLOW_DEBUG"] = "1"

    # token 解析：显式指定原样使用；debug 缺省用可预测 token（INKFLOW_DEBUG_TOKEN
    # 可覆盖）；非 debug 缺省随机生成（每次启动不同）
    if token is not None:
        effective_token = token
    elif is_debug:
        effective_token = os.environ.get("INKFLOW_DEBUG_TOKEN", "inkflow-debug-token")
    else:
        effective_token = secrets.token_urlsafe(32)
    # env 注入必须先于 _run_server：reload 子进程经 env 继承 token，校验保持启用
    os.environ["INKFLOW_SERVER_TOKEN"] = effective_token

    if open_browser:
        url = f"http://{host}:{port}/docs"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # #1477 1.4：内核日志自管理（分片 + 库轮转）。
    # 🔴 这里只**标记**日志路径，真正的 sink 装配交给 `core.log.setup_logging`
    # （lifespan 内调用）——它开头就 `logger.remove()`，提前装 sink 会被清掉
    # （实测：分片文件只记到 uvicorn 前两行，其余全落回 stderr → 引导日志）。
    # 内核分支不再加 stderr sink：stderr 已被 Popen 重定向到引导日志，
    # 全量日志再灌进去正是 #1477 的膨胀根因（实测 246MB 且无归档）。
    from inkflow.infrastructure.kernel.bootstrap import kernel_runtime_log_path

    os.environ["INKFLOW_KERNEL_LOG_FILE"] = str(
        kernel_runtime_log_path(kernel_kind, kernel_state_file)
    )

    typer.echo(f"🚀 InkFlow 服务启动于 http://{host}:{port}")

    if is_debug:
        actual_port = _run_server(host, port, reload, True)
    else:
        # 非 debug 保持 3 参调用（装配缝第 4 参缺省 False，既有 mock 兼容）
        actual_port = _run_server(host, port, reload)

    # F51 debug 默认自动打开 /docs（_run_server 返回后，用实际监听端口防 :0 死链）
    # F51 v1.1 (#949): debug auto-open /docs escape hatch - INKFLOW_DEBUG_NO_BROWSER=1/true/on
    # skips the Timer registration (e2e / headless usage); default unset = still opens.
    no_browser = os.environ.get("INKFLOW_DEBUG_NO_BROWSER", "").strip().lower() in {
        "1",
        "true",
        "on",
    }
    if is_debug and not no_browser:
        docs_url = f"http://{host}:{actual_port}/docs"
        threading.Timer(1.5, lambda: webbrowser.open(docs_url)).start()

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
        # 内核自注册（#1487 / ADR-066 ③）：就绪后写自己的注册条目（退出时自删），
        # 使 GUI 自己 spawn 的内核也出现在注册表/托盘中。
        from datetime import UTC, datetime

        with contextlib.suppress(OSError):  # 不可写 → 降级：仅影响可见性，不阻塞内核
            _write_kernel_registry(
                kernel_kind,
                kernel_state_file,
                {**payload, "started_at": datetime.now(UTC).isoformat()},
            )
            # GUI 自登记（#1537）：内置内核形态 → 写机器级 gui.json，供 CLI 探测便携版 GUI
            _write_gui_record()
        # 空闲回收看门狗（#1487 / ADR-066 ②）：阈值未设置 → 不启动（手工 serve 常驻不变）
        idle_timeout = resolve_idle_timeout()
        if idle_timeout is not None:
            # 🔴 倒计时起点 = **就绪时刻**，不是进程/import 时刻：内核冷启动 import 树
            # 可达数秒（CI ~60s），若从模块导入起算，小阈值下内核刚就绪即被回收
            # （#1487 实证抓出：6s 阈值内核起来后 /health 立即连不上）。
            activity_tracker().touch()

            def _on_idle() -> None:
                if _current_server is not None:
                    _current_server.should_exit = True

            _idle_watchdog = _start_idle_watchdog(idle_timeout, _on_idle)

    if not reload and _server_thread is not None:
        try:
            _server_thread.join()
        except KeyboardInterrupt:
            # Ctrl+C：通知 uvicorn 优雅退出（主循环 tick 检查 should_exit）
            if _current_server is not None:
                _current_server.should_exit = True
            _server_thread.join(timeout=5)
        finally:
            # 自删注册条目 + 停看门狗（存活期互斥随进程退出由 OS 回收，spec §5.6）
            if _idle_watchdog is not None:
                _idle_watchdog.stop()
            _remove_kernel_registry(kernel_kind, kernel_state_file, os.getpid())
