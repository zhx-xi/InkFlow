"""InkFlow FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from inkflow.api.middleware.token_auth import TokenAuthMiddleware
from inkflow.api.routers import (
    agent,
    audit,
    chapter,
    characters,
    context,
    extractions,
    foreshadowings,
    outlines,
    project,
    style,
    timeline,
    world_settings,
    writing,
)
from inkflow.core.config import config
from inkflow.core.database import create_tables
from inkflow.core.log import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理——启动/关闭钩子。"""
    setup_logging()
    await create_tables()
    yield
    # TODO: 关闭数据库连接


app = FastAPI(
    title="InkFlow API",
    version="0.1.0",
    description="InkFlow — AI 辅助小说创作工具 REST API",
    lifespan=lifespan,
)


def _custom_openapi():
    """生成 OpenAPI schema 并注入全局 HTTPBearer security scheme（spec §2.3.1 末条）。

    FastAPI 0.141+ 已移除 ``FastAPI(security=[...])`` 参数——该参数被静默吞入
    ``app.extra``，不产生任何 OpenAPI 声明（实测 components.securitySchemes 缺失），
    故在 schema 生成后显式注入：Swagger UI Authorize 按钮的数据基础，兼作
    ADR-024 云端 JWT（Authorization: Bearer...）前置。

    仅文档声明，【禁止】作为路由依赖（测试契约 #3：强制校验只由 HTTP 中间件完成，
    HTTPBearer 依赖会返回 403/自带 WWW-Authenticate 挑战，破坏 401 契约）。
    """
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})["HTTPBearer"] = {
        "type": "http",
        "scheme": "bearer",
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


# 自定义 openapi 注入 HTTPBearer scheme（FastAPI 0.141+ 无 security= 参数）
app.openapi = _custom_openapi  # type: ignore[method-assign]

# ---- CORS（白名单来自 config.server_cors_origins，spec §2.3.2） ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.server_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Token 鉴权（纯 ASGI，spec §2.3.1；注册在 CORS 之后：CORS 外层、token 内层） ----
app.add_middleware(TokenAuthMiddleware)

# ---- 注册路由 ----
app.include_router(audit.router)
app.include_router(project.router)
app.include_router(style.router)
app.include_router(chapter.router)
app.include_router(characters.router)
app.include_router(writing.router)
app.include_router(agent.router)
app.include_router(context.router)
app.include_router(world_settings.router)
app.include_router(outlines.router)
app.include_router(timeline.router)
app.include_router(foreshadowings.router)
app.include_router(extractions.router)


# ---- 健康检查 ----
@app.get("/health", tags=["系统"])
async def health_check():
    """服务健康检查端点。"""
    return {"status": "ok", "version": "0.1.0", "mode": config.mode}
