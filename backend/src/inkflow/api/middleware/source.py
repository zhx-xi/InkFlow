"""#1088 批 A3：X-Inkflow-Source 请求头发起方标记中间件（纯 ASGI）。

契约来源
--------
- specs/f23-sse/spec.md §15.2.4（`source` 判定链「显式参数 > 请求头（contextvar）> unknown」）、
  §15.6.3（全局域事件跨项目语义）、§15.4.2（纯 ASGI 硬约束）。
- domain/services/_data_change.py（`set_event_source` / `reset_event_source` 的 ContextVar
  定义位置；domain 不能 import api，故中间件方向引用 domain）。

设计决策
--------
1. **纯 ASGI（禁 BaseHTTPMiddleware）**：镜像 correlation.py 的形态——BaseHTTPMiddleware
   会缓冲/破坏 StreamingResponse（同 token_auth / docs_gate / correlation 决策）。
2. **白名单**：仅 `gui|cli|mcp|agent` 被视为合法发起方；缺失/非法 → 不设（保持默认
   `unknown`，spec §15.2.4 判定链末端）。
3. **finally 复位**：请求结束按 set 返回的 Token 复位 ContextVar，防泄漏到后续请求/任务。
4. 非 http scope（websocket/lifespan 等）直接透传（同 correlation/token_auth 决策）。
"""

from __future__ import annotations

from typing import cast

from inkflow.domain.services._data_change import reset_event_source, set_event_source

#: 发起方请求头（ASGI headers 键规范化为小写 bytes）
SOURCE_HEADER = b"x-inkflow-source"

#: 合法发起方（spec §15.2.4 表：gui|cli|mcp|agent；scheduler 由内核内显式传参，不经 HTTP）
VALID_SOURCES = frozenset({"gui", "cli", "mcp", "agent"})


def _extract_header(scope: dict, name: bytes) -> str:
    """从 ASGI scope headers 提取头值（键名大小写不敏感）；缺失返回空串。"""
    for raw_name, raw_value in scope.get("headers", []):
        if cast(bytes, raw_name).lower() == name:
            return cast(bytes, raw_value).decode("latin-1")
    return ""


class EventSourceMiddleware:
    """纯 ASGI 中间件：X-Inkflow-Source → 事件 source ContextVar（请求级）。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive, send) -> None:
        # 非 http scope（websocket/lifespan 等）直接透传（同 correlation 决策）。
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        source = _extract_header(scope, SOURCE_HEADER).strip().lower()
        token = set_event_source(source) if source in VALID_SOURCES else None
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                reset_event_source(token)
