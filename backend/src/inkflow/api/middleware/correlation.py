"""#931 请求关联中间件 — X-Correlation-Id 兜底生成 + W3C traceparent（纯 ASGI）。

契约来源
--------
- backend/tests/unit/api/middleware/test_correlation_trace_931.py（模块 docstring
  为权威规格）：无头请求兜底 correlation uuid4 + 根 TraceContext；traceparent
  合法头 → 继承 trace 开子 span；缺失/非法 → 新根；响应回写两请求头。
- specs/f496-log-page/spec.md §2.2 B4（#496）：x-correlation-id 沿用语义不变。
- 纯 ASGI（禁 BaseHTTPMiddleware）：F23 SSE 流式已合入，BaseHTTPMiddleware 会
  缓冲/破坏 StreamingResponse（同 token_auth / docs_gate 决策）。

设计决策
--------
1. 注册在 app.py 最外层（DocsGate 之后）：请求最早进入即设置两个 contextvar，
   覆盖整个请求生命周期（含 @instrument 埋点链路与后台任务继承）。
2. 读头大小写不敏感（ASGI scope 键已小写，lower() 兼容混合大小写写头）。
3. send wrapper 在 http.response.start 追加 x-correlation-id 与 traceparent
   （= 当前内核 span），保留既有 headers 不丢弃；finally reset 两个 contextvar。
4. 非 http scope（websocket/lifespan 等）直接透传（同 token_auth 决策）。
"""

from __future__ import annotations

import uuid
from typing import cast

from inkflow.logging.correlation import (
    reset_request_correlation_id,
    set_request_correlation_id,
)
from inkflow.logging.trace import (
    TraceContext,
    make_traceparent,
    new_span_id,
    new_trace_id,
    parse_traceparent,
    reset_trace_context,
    set_trace_context,
)

#: 关联 ID / traceparent 请求头（ASGI headers 键规范化为小写 bytes）
CORRELATION_HEADER = b"x-correlation-id"
TRACEPARENT_HEADER = b"traceparent"


def _extract_header(scope: dict, name: bytes) -> str:
    """从 ASGI scope headers 提取头值（键名大小写不敏感）；缺失返回空串。"""
    for raw_name, raw_value in scope.get("headers", []):
        if cast(bytes, raw_name).lower() == name:
            return cast(bytes, raw_value).decode("latin-1")
    return ""


class CorrelationIdMiddleware:
    """纯 ASGI 中间件：correlation/trace contextvar 建立 + 响应头回写。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive, send) -> None:
        # 非 http scope（websocket/lifespan 等）直接透传（同 token_auth 决策）。
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # correlation：有头沿用（#496 语义不变）；缺失/空值兜底 uuid4（#931 根因 1）。
        correlation_id = _extract_header(scope, CORRELATION_HEADER)
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # trace：合法 traceparent → 子 span（同 trace、新 span、parent=头 span）；
        # 缺失/非法 → 新根（parent_span_id=""）。绝不抛异常、绝不透传非法值。
        trace_ctx = parse_traceparent(_extract_header(scope, TRACEPARENT_HEADER))
        if trace_ctx is None:
            trace_ctx = TraceContext(
                trace_id=new_trace_id(),
                span_id=new_span_id(),
                parent_span_id="",
            )

        corr_token = set_request_correlation_id(correlation_id)
        trace_token = set_trace_context(trace_ctx)

        async def send_with_headers(message: dict) -> None:
            """http.response.start 追加 correlation/traceparent 响应头（保留原列表）。"""
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-correlation-id", correlation_id.encode("latin-1")),
                        (b"traceparent", make_traceparent(trace_ctx).encode("latin-1")),
                    ],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            # Token 顺序复位：trace → correlation（与 set 相反），防泄漏到后续请求/任务。
            reset_trace_context(trace_token)
            reset_request_correlation_id(corr_token)
