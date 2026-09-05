"""F20/#924 MCP 进程日志桥接 — loguru sink → POST /logs 转发内核 StructuredLogStore。

MCP 宿主进程（inkflow-mcp）的 @instrument(caller_type="mcp") 埋点默认只落
stderr，不进内核 StructuredLogStore，GUI 日志页「内核」分类存在 MCP 盲区
（issue #924）。本模块提供进程级转发单例与 mcp_log_sink() 上下文：把带
caller_type 的结构化记录缓冲，并按需 POST 到内核 /api/v1/logs。

GREEN 契约来源：backend/tests/unit/mcp/test_mcp_log_bridge.py（模块 docstring
为权威规格；字段/级别/参数/路径逐字对齐）。
"""

from __future__ import annotations

import contextlib
import importlib
from collections import deque
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

if TYPE_CHECKING:
    from loguru import Message

#: 缓冲上限：满则丢最旧，静默（F20 契约）
_PENDING_MAXLEN = 200


def _norm_level(name: str) -> str:
    """loguru 级别名归一：WARNING → WARN（与内核 store/API 口径一致）。"""
    return "WARN" if name == "WARNING" else name


class McpLogForwarder:
    """缓冲并转发 MCP 结构化日志的内核桥接（进程级单例）。"""

    def __init__(self) -> None:
        self.pending: deque[dict[str, Any]] = deque(maxlen=_PENDING_MAXLEN)
        self.client: httpx.Client | None = None
        self._endpoint: tuple[int, str] | None = None

    def attach(self, port: int, token: str) -> None:
        """绑定内核 HTTP 端点；端点未变且已有 client 则复用，否则重建。

        token 仅存在于 client 请求头，绝不进入 pending/body（F20 §6.3/§271）。
        """
        endpoint = (port, token)
        if endpoint == self._endpoint and self.client is not None:
            return
        self._close_client()
        self.client = _make_client(port, token)
        self._endpoint = endpoint

    def reset(self) -> None:
        """清空缓冲并释放 client/端点（测试隔离缝）。"""
        self.pending.clear()
        self._close_client()
        self._endpoint = None

    def sink(self, message: Message) -> None:
        """loguru sink 回调：仅缓冲带 caller_type 的结构化记录（INFO+ 由 handler 把关）。

        整段 try/except 静默——日志故障绝不上抛业务（contract-496 §1 同语义）。
        """
        with contextlib.suppress(Exception):
            extra = message.record["extra"]
            if "caller_type" not in extra:
                return
            body: dict[str, Any] = {
                "level": _norm_level(str(message.record["level"].name)),
                "caller_type": extra["caller_type"],
                "caller_name": extra["caller_name"],
                "event": extra["event"],
                "message_key": extra["message_key"],
                "params": extra.get("params", {}),
                "correlation_id": extra.get("correlation_id", ""),
            }
            for key in (
                "project_id",
                "entity_id",
                "duration_ms",
                "error_code",
                "trace_id",
                "span_id",
                "parent_span_id",
            ):
                if key in extra:
                    body[key] = extra[key]
            self.pending.append(body)

    def flush(self) -> None:
        """逐条 POST /logs（timeout=5s）；成功/失败均消费缓冲，永不抛异常。

        client 为 None（未 attach）时是廉价 no-op——非 stdio 会话面零转发。
        """
        client = self.client
        if client is None:
            return
        while self.pending:
            body = self.pending[0]
            with contextlib.suppress(Exception):
                client.post("/logs", json=body, timeout=5.0)
            self.pending.popleft()

    def _close_client(self) -> None:
        """best-effort 关闭并置空 client。"""
        if self.client is not None:
            with contextlib.suppress(Exception):
                self.client.close()
            self.client = None


def _make_client(port: int, token: str) -> httpx.Client:
    """构造转发 client（模块级工厂缝，测试 monkeypatch 点）。"""
    return httpx.Client(
        base_url=f"http://127.0.0.1:{port}/api/v1",
        headers={"X-InkFlow-Token": token},
        timeout=5.0,
    )


_forwarder: McpLogForwarder | None = None


def get_forwarder() -> McpLogForwarder:
    """返回进程级转发单例。"""
    global _forwarder
    if _forwarder is None:
        _forwarder = McpLogForwarder()
    return _forwarder


#: mcp_log_sink 重入守卫——仅最外层 enter 装 sink/补丁，最外层 exit 拆除
_sink_depth = 0


def is_bridge_active() -> bool:
    """mcp_log_sink 是否已进入（stdio 会话面；最外层安装期间为 True）。

    server.call_tool_result 的未知工具路径据此惰性 attach：仅在 stdio 会话内
    经 ensure_kernel 拿端点，非 stdio 直调面保持零探测。
    """
    return _sink_depth > 0


@contextlib.contextmanager
def mcp_log_sink() -> Iterator[None]:
    """注册转发 sink + 包装 ensure_kernel（成功后 attach），供 main()/测试使用。

    嵌套/重复进入不叠加 handler（depth 守卫）；最外层退出时尽力 final flush、
    还原 ensure_kernel、移除 handler 并关闭 client（全部 best-effort）。
    """
    global _sink_depth
    forwarder = get_forwarder()
    outermost = _sink_depth == 0
    handler_id: int | None = None
    kernel_mod: Any = None
    original: Any = None
    if outermost:
        handler_id = logger.add(
            forwarder.sink,
            level="INFO",
            filter=lambda record: "caller_type" in record["extra"],
        )
        # 运行时读模块属性（测试在进入前 patch 的是同一个模块对象）；工具 func
        # 内延迟 `from inkflow.infrastructure.kernel import ensure_kernel` 会取到
        # 被包装的版本 → ensure 成功即 attach(handle.port, handle.token)。
        kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
        original = kernel_mod.ensure_kernel

        async def _wrapped_ensure(*args: Any, **kwargs: Any) -> Any:
            """await 原 ensure_kernel；成功 → attach，异常透传（不 attach）。"""
            handle = await original(*args, **kwargs)
            forwarder.attach(handle.port, handle.token)
            return handle

        kernel_mod.ensure_kernel = _wrapped_ensure
    _sink_depth += 1
    try:
        yield
    finally:
        _sink_depth -= 1
        if outermost:
            with contextlib.suppress(Exception):
                forwarder.flush()
            if kernel_mod is not None:
                kernel_mod.ensure_kernel = original
            if handler_id is not None:
                with contextlib.suppress(Exception):
                    logger.remove(handler_id)
            forwarder._close_client()
