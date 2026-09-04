"""B4 X-Correlation-Id 请求关联中间件 — 纯 ASGI（#496 统一日志页，contract-496 §3）。

契约来源
--------
- specs/f496-log-page/spec.md §2.2 B4：前端 bridge 已发 X-Correlation-Id 头，
  后端埋点从不消费 → correlation_id 查询只能命中 GUI 记录。
- contract-496.md §3：http scope 读 x-correlation-id（scope headers 已小写）→
  非空则 set contextvar（try/finally reset）；非 http scope 透传。
- 纯 ASGI（禁 BaseHTTPMiddleware）：F23 SSE 流式已合入，BaseHTTPMiddleware 会
  缓冲/破坏 StreamingResponse（同 token_auth / docs_gate 决策）。

设计决策
--------
1. 注册在 app.py 最外层（DocsGate 之后）：请求最早进入即设置 contextvar，
   覆盖整个请求生命周期（含 @instrument 埋点链路）。
2. 非空才 set；finally reset（token）——防 contextvar 泄漏到后续请求/异步任务。
3. scope headers 键已小写（ASGI 规范），值按 latin-1 解码（同 token_auth）。
"""

from __future__ import annotations

from typing import cast

from inkflow.logging.correlation import (
    reset_request_correlation_id,
    set_request_correlation_id,
)

#: 关联 ID 请求头（ASGI headers 键规范化为小写 bytes）
CORRELATION_HEADER = b"x-correlation-id"


def _extract_correlation_id(scope: dict) -> str:
    """从 ASGI scope headers 提取 X-Correlation-Id 值；缺失/空值返回空串。"""
    for name, value in scope.get("headers", []):
        if cast(bytes, name).lower() == CORRELATION_HEADER:
            return cast(bytes, value).decode("latin-1")
    return ""


class CorrelationIdMiddleware:
    """纯 ASGI X-Correlation-Id 中间件：请求头值 → ContextVar（请求级沿用）。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive, send) -> None:
        # 非 http scope（websocket/lifespan 等）直接透传（同 token_auth 决策）。
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = _extract_correlation_id(scope)
        if not correlation_id:
            await self.app(scope, receive, send)
            return

        token = set_request_correlation_id(correlation_id)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_correlation_id(token)
