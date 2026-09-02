"""F1 前端集成测试的 fake LLM 启动器（Node 子进程 spawn）。

复用 backend/tests/fake_llm（ADR-047）：bind(:0) 取未关闭 socket 传给 uvicorn（防 Windows
端口 TIME_WAIT 二次 bind 冲突 #872），打印 `FAKE_READY <port>`，阻塞直至被终止。
前端 vitest.integration 测试经 stdout 解析端口，把 base_url 注入内核 INKFLOW_LLM_BASE_URL。
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

# 动态解析 backend 路径（本文件 <repo>/frontend/packages/renderer/src/api/__integration__/，
# repo root = 上 6 级）；避免硬编码本地绝对路径导致 CI 下 import 失败（#883 实测）。
_REPO_ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(_REPO_ROOT / "backend"))
from tests.fake_llm.server import create_app


def main() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("fake LLM 未在 10s 内启动")
        time.sleep(0.02)
    print(f"FAKE_READY {port}", flush=True)
    # 阻塞直至被 kill
    while not server.should_exit:
        time.sleep(0.1)


if __name__ == "__main__":
    main()
