"""fake LLM black-box fixture（S3a，ADR-047 S1+）：起真监听端口的 uvicorn server。

黑盒测试（真实 LangChainLLMClient 经 HTTP 打 fake server）需要真实网络端口
（TestClient 是进程内 ASGI，无法被 httpx/urllib 真请求触达）。本 fixture 起
线程 uvicorn → yield SimpleNamespace(server, base_url)；每例结束关闭。

坑（Windows #872 实证）：bind(:0) 取号后**关闭**socket，再让 uvicorn 二次 bind 会撞
`[Errno 10048]`（Windows 端口 TIME_WAIT 不即时释放）→ 必须把**未关闭的已 bind socket**
直接传给 `server.run(sockets=[sock])`，uvicorn 复用该 socket 不重新 bind。
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
import uvicorn

from .server import create_app


@pytest.fixture
def fake_llm() -> Iterator[SimpleNamespace]:
    """起真 uvicorn fake LLM server，yield SimpleNamespace(server, base_url)。

    每例新 server 实例（state.received_prompts / error_counts 干净），例后关闭端口。
    黑盒测试经 base_url 发真 HTTP 请求；断言收到的 payload 用 server.state。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    api = create_app()
    server = uvicorn.Server(uvicorn.Config(api, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    # 等 started（防先请求后启动竞态）
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            sock.close()
            raise TimeoutError("fake_llm server 未在 10s 内启动")
        if not thread.is_alive():
            sock.close()
            raise TimeoutError("fake_llm server 线程提前退出")
        time.sleep(0.02)
    yield SimpleNamespace(app=api, base_url=f"http://127.0.0.1:{port}/v1")
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()
