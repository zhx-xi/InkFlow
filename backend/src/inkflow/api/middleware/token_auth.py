"""X-InkFlow-Token 鉴权中间件（#77 内核进程化，spec §2.3.1 / §2.1.3）。

契约来源
--------
- specs/f19-gui/spec.md §2.3.1（token 中间件）：路径豁免 /docs /redoc
  /openapi.json；env ``INKFLOW_SERVER_TOKEN`` 未设置时直通（无 token 模式）；
  401 响应精确 ``{"detail": "Unauthorized"}``、无 WWW-Authenticate 挑战。
- specs/f19-gui/spec.md §2.1.3（token 传递）：请求头 ``X-InkFlow-Token``。
- 2026-08-03 评审 Q2 = 选项 B：/health 不豁免（与数据面端点同规则，
  堵 DNS rebinding 探测通道；壳解析 INKFLOW_READY 行拿 token 零成本）。

设计决策
--------
1. 纯 ASGI 中间件（非 BaseHTTPMiddleware / @app.middleware("http")）：
   F23 SSE 流式（PR #83）已合入，BaseHTTPMiddleware 会缓冲/破坏
   StreamingResponse 流式响应。纯 ASGI 只在请求进入时拦截（http scope），
   响应原样透传零干扰；非 http scope（websocket 等）直接透传。
2. env 每次请求时读取（禁止 import/实例化时缓存）：tests/api/ 共享同一
   pytest 进程，``inkflow.api.app`` import 顺序不可控；测试在 import 之后
   monkeypatch.setenv/delenv。缓存读取会使测试结果取决于 pytest 收集顺序
   （spec §2.3.1「避免 config 单例启动时序问题」同理）。
3. OPTIONS 预检显式豁免（测试契约设计假设 #10 选项 b）：浏览器跨域预检
   不携带自定义头 X-InkFlow-Token，必须放行 preflight。选显式豁免而非
   依赖注册顺序（选项 a：CORS 外层短路）——自包含，防未来 app.py
   注册顺序改动破坏行为。
4. 401 响应不携带 WWW-Authenticate 头（非 HTTP Basic/Bearer 挑战语义，
   防探测）。
"""

import hmac
import os

from fastapi.responses import JSONResponse

#: token 传递请求头（spec §2.1.3）
TOKEN_HEADER = "X-InkFlow-Token"

#: token 来源环境变量（spec §2.3.1）：serve 启动时注入进程环境
ENV_TOKEN = "INKFLOW_SERVER_TOKEN"

#: 静态文档豁免路径（spec §2.3.1，Q2 选项 B：仅此三路径，/health 不豁免）
_EXEMPT_PATHS = ("/docs", "/redoc", "/openapi.json")


class TokenAuthMiddleware:
    """纯 ASGI token 鉴权中间件。

    行为（与测试契约逐条对应）：

    - env ``INKFLOW_SERVER_TOKEN`` 未设置 → 直通（无 token 模式，
      既有测试零破坏）。
    - 路径豁免：/docs /redoc /openapi.json（前缀匹配）→ 放行。
    - OPTIONS 预检 → 放行（浏览器 preflight 不携带自定义头）。
    - 其余请求：``X-InkFlow-Token`` 匹配 env token → 放行；
      缺失/不匹配 → 401 ``{"detail": "Unauthorized"}``（无内部细节、
      无 WWW-Authenticate 头）。
    - 非 http scope（websocket 等）→ 原样透传。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 非 http scope（websocket 等）直接透传，响应原样透传零干扰。
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # OPTIONS 预检显式豁免：浏览器 preflight 不携带自定义头
        # （测试契约设计假设 #10，选项 b——自包含，不依赖注册顺序）。
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # 静态文档豁免：/docs /redoc /openapi.json（前缀匹配）。
        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in _EXEMPT_PATHS):
            await self.app(scope, receive, send)
            return

        # env 每次请求时读取（硬性契约，见模块 docstring 设计决策 #2）。
        expected = os.environ.get(ENV_TOKEN)
        if not expected:
            # 无 token 模式：env 未设置 → 直通（spec §2.3.1 补充行）。
            await self.app(scope, receive, send)
            return

        provided = _extract_token(scope)
        if provided is None or not _tokens_match(expected, provided):
            response = JSONResponse(
                content={"detail": "Unauthorized"},
                status_code=401,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _extract_token(scope):
    """从 ASGI scope headers 中提取 X-InkFlow-Token 值（大小写不敏感）。

    ASGI headers 为 (bytes, bytes) 元组列表，键已规范化为小写。
    缺失时返回 None。
    """
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-inkflow-token":
            return value.decode("latin-1")
    return None


def _tokens_match(expected, provided):
    """常量时间比较，防时序侧信道（token 为 secrets.token_urlsafe 输出）。"""
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))
