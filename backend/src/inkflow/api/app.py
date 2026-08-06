"""InkFlow FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

import inkflow
from inkflow.api.deps import get_provider_config_service
from inkflow.api.middleware.token_auth import TokenAuthMiddleware
from inkflow.api.routers import (
    agent,
    agent_templates,
    audit,
    chapter,
    characters,
    context,
    extractions,
    foreshadowings,
    outlines,
    project,
    provider_configs,
    settings,
    style,
    timeline,
    world_settings,
    writing,
)
from inkflow.core.config import config
from inkflow.core.database import (
    async_session_factory,
    create_tables,
    engine,
    ensure_provider_builtin_key_column,
)
from inkflow.core.log import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理——启动/关闭钩子。"""
    setup_logging()
    await create_tables()
    # #126 A1：旧库轻量列迁移 —— create_tables 之后、seed 之前补 builtin_key 列，
    # 新库 create_all 已含列（no-op）；旧库加列后由 seed 按 name 命中回填。
    async with engine.begin() as conn:
        await conn.run_sync(ensure_provider_builtin_key_column)
    # #106 F1：启动后幂等 seed 内置 4 provider（ProviderConfigService 同名跳过，
    # 全新安装注册表为空 → seed 补全；重复启动不重复插入）
    async with async_session_factory() as session:
        await get_provider_config_service(session).seed_builtin_providers()
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
app.openapi = _custom_openapi  # type: ignore[method-assign]  # 运行时替换 FastAPI 实例方法，静态类型禁止对方法赋值

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
app.include_router(provider_configs.router)
app.include_router(agent_templates.router)
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
app.include_router(settings.router)


# ---- 健康检查 ----
@app.get("/health", tags=["系统"])
async def health_check():
    """服务健康检查端点。"""
    return {"status": "ok", "version": inkflow.__version__, "mode": config.mode}
