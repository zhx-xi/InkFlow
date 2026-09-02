"""S3f-T1 G1（#869）：/docs /redoc 按 config.debug 运行时门控中间件。

契约来源
--------
- .hermes/plans/contract-s3f-t1.md §1.1（行为矩阵 / debug 读取时机 / 注册顺序）。
- specs/f51-debug-mode/spec.md §5.4（debug 时"才"可直达 /docs；非 debug 默认关闭）。
- specs/f19-gui/spec.md §2.3.1（token 豁免 /docs /redoc——G1 后豁免语义仅 debug 态
  成立，S3f-T1 契约升级）。

设计决策
--------
1. 纯 ASGI 中间件（非 BaseHTTPMiddleware）：同 token_auth 决策 #1——F23 SSE 流式已
   合入，BaseHTTPMiddleware 会缓冲/破坏 StreamingResponse 流式响应；纯 ASGI 只在
   请求进入时拦截（http scope），响应原样透传零干扰。
2. config.debug 每次请求时读取（禁止 import/实例化时缓存）：tests/api/ 共享同一
   pytest 进程，测试在 import 之后 monkeypatch.setattr(config, "debug", ...) 控制
   ——缓存读取会使测试结果取决于 pytest 收集顺序（同 token_auth 设计决策 #2）。
3. /openapi.json 恒不受门控：快照 ci_cd/export_openapi.py 直调 app.openapi() +
   gen:api 契约 + token_auth HTTPBearer scheme 用例依赖；门控路径仅 /docs /redoc。
4. 404 响应不暴露 debug 存在：JSON {"detail": "Not Found"}（与 FastAPI 默认 404
   同形，防探测路径开关状态）。
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from inkflow.core.config import config

#: 门控的静态文档路径（/openapi.json 恒透传，不列入——见模块 docstring 决策 #3）
_GATED_PATHS = ("/docs", "/redoc")


class DocsGateMiddleware:
    """纯 ASGI docs 门控中间件。

    行为（与测试契约逐条对应）：
    - config.debug=False → /docs /redoc（含子路径，前缀匹配）→ 404
      {"detail": "Not Found"}（不暴露 debug 存在）。
    - config.debug=True → 原样透传（FastAPI 默认 Swagger/ReDoc 页 200）。
    - /openapi.json 与其他路径恒不受影响（透传）。
    - 非 http scope（websocket 等）→ 原样透传。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 非 http scope（websocket 等）直接透传，响应原样透传零干扰（同 token_auth）。
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 门控路径判定对齐 token_auth 前缀匹配：/docs /redoc（含子路径）。
        # debug 每次请求时读取（硬性契约，见模块 docstring 决策 #2）：config 单例
        # 由 serve --debug / INKFLOW_DEBUG 回写，请求期生效。
        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in _GATED_PATHS) and not config.debug:
            response = JSONResponse(
                content={"detail": "Not Found"},
                status_code=404,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
