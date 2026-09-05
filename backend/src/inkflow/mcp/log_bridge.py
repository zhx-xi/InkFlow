"""F20/#924 MCP 进程日志桥接 — loguru sink → POST /logs 转发内核 StructuredLogStore。

MCP 宿主进程（inkflow-mcp）的 @instrument(caller_type="mcp") 埋点默认只落
stderr，不进内核 StructuredLogStore，GUI 日志页「内核」分类存在 MCP 盲区
（issue #924）。本模块提供进程级转发单例与 mcp_log_sink() 上下文：把带
caller_type 的结构化记录缓冲，并按需 POST 到内核 /api/v1/logs。

引擎逻辑自 #942 起迁至 inkflow.logging.bridge（通用引擎），本模块保留公开面
（McpLogForwarder/_make_client/get_forwarder/mcp_log_sink/is_bridge_active）
并委托引擎，行为零变化。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import httpx

from inkflow.logging.bridge import (
    LogForwarder,
    is_sink_active,
    log_sink,
)
from inkflow.logging.bridge import _make_client as _engine_make_client


class McpLogForwarder(LogForwarder):
    """MCP 侧门面：引擎 subclass，工厂动态读本模块 _make_client 属性。

    monkeypatch.setattr(inkflow.mcp.log_bridge, "_make_client", fake) 在
    attach 时生效（工厂经模块全局查找解析）。
    """

    def __init__(self) -> None:
        super().__init__(client_factory=_default_client)


def _default_client(port: int, token: str) -> Any:
    """运行时读本模块 _make_client（patch 生效）；返回引擎 httpx client。"""
    return _make_client(port, token)


def _make_client(port: int, token: str) -> httpx.Client:
    """构造转发 client（模块级工厂缝，测试 monkeypatch 点）；契约同通用引擎。"""
    return _engine_make_client(port, token)


_forwarder: McpLogForwarder | None = None


def get_forwarder() -> McpLogForwarder:
    """返回进程级转发单例。"""
    global _forwarder
    if _forwarder is None:
        _forwarder = McpLogForwarder()
    return _forwarder


def is_bridge_active() -> bool:
    """mcp_log_sink 是否已进入（stdio 会话面；最外层安装期间为 True）。

    server.call_tool_result 的未知工具路径据此惰性 attach：仅在 stdio 会话内
    经 ensure_kernel 拿端点，非 stdio 直调面保持零探测。
    """
    return is_sink_active()


@contextlib.contextmanager
def mcp_log_sink() -> Iterator[None]:
    """注册转发 sink + 包装 ensure_kernel（成功后 attach），供 main()/测试使用。"""
    with log_sink(get_forwarder()):
        yield
