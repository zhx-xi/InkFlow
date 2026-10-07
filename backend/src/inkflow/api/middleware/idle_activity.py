"""空闲活动中间件 —— 每个 HTTP 请求刷新内核空闲倒计时（spec f30 §5.5 / ADR-066 ②）。

纯 ASGI（与既有 `TokenAuthMiddleware` / `CorrelationIdMiddleware` 同构）：不依赖
FastAPI 依赖注入，`/health` 与全部业务端点一律覆盖（**GUI 的 2s `/health` 轮询
因此让常驻内核不被回收**）。

阈值与看门狗在 `serve` 侧装配；本中间件只负责 `touch()`（进程级单例追踪器）。
"""

from __future__ import annotations

from typing import Any


class IdleActivityMiddleware:
    """纯 ASGI 中间件：HTTP 请求 → `activity_tracker().touch()`（lifespan/websocket 跳过）。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            from inkflow.infrastructure.kernel.idle_reclaim import activity_tracker

            activity_tracker().touch()
        await self.app(scope, receive, send)
