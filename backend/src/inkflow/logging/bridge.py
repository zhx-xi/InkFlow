"""F20/#942 通用日志转发引擎 — loguru sink → POST /logs（CLI/MCP 双进程共用）。

#924 的转发器/sink/flush 形态与调用方进程无关：本模块把缓冲、attach、flush
与 log_sink 上下文提升为通用引擎；mcp.log_bridge 与 cli.log_bridge 分别以
模块级 _make_client 工厂缝接入（monkeypatch 在 attach 时动态生效）。
"""

from __future__ import annotations

import contextlib
import importlib
from collections import deque
from collections.abc import Callable, Iterator
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


class LogForwarder:
    """缓冲并转发结构化日志的内核桥接（CLI/MCP 共用引擎，进程级单例）。

    client_factory 为模块级工厂缝：None → attach 时运行时读本模块
    ``_make_client``（monkeypatch.setattr 动态生效）。
    """

    def __init__(self, client_factory: Callable[[int, str], Any] | None = None) -> None:
        self.pending: deque[dict[str, Any]] = deque(maxlen=_PENDING_MAXLEN)
        self.client: httpx.Client | None = None
        self._endpoint: tuple[int, str] | None = None
        self._client_factory = client_factory

    def _resolve_factory(self, port: int, token: str) -> Any:
        """解析当前工厂：注入优先，缺省回退模块属性（patch 生效）。"""
        if self._client_factory is not None:
            return self._client_factory(port, token)
        return _make_client(port, token)

    def attach(self, port: int, token: str) -> None:
        """绑定内核 HTTP 端点；端点未变且已有 client 则复用，否则重建。

        token 仅存在于 client 请求头，绝不进入 pending/body（F20 §6.3/§271）。
        """
        endpoint = (port, token)
        if endpoint == self._endpoint and self.client is not None:
            return
        self._close_client()
        self.client = self._resolve_factory(port, token)
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

        client 为 None（未 attach）时是廉价 no-op——非会话面零转发。
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


#: log_sink 重入守卫——仅最外层 enter 装 sink/补丁，最外层 exit 拆除
_sink_depth = 0


def is_sink_active() -> bool:
    """log_sink 是否已进入（会话面；最外层安装期间为 True）。"""
    return _sink_depth > 0


@contextlib.contextmanager
def log_sink(forwarder: LogForwarder) -> Iterator[None]:
    """注册转发 sink + 包装 ensure_kernel（成功后 attach），供 mcp/cli 使用。

    嵌套/重复进入不叠加 handler（depth 守卫）；最外层退出时尽力 final flush、
    还原 ensure_kernel、移除 handler 并关闭 client（全部 best-effort）。
    """
    global _sink_depth
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
        # 运行时读模块属性（测试在进入前 patch 的是同一个模块对象）；延迟
        # `from inkflow.infrastructure.kernel import ensure_kernel` 会取到被包装
        # 的版本 → ensure 成功即 attach(handle.port, handle.token)。
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
