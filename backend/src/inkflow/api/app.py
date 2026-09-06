"""InkFlow FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

import inkflow
from inkflow.api.deps import get_provider_config_service
from inkflow.api.middleware.correlation import CorrelationIdMiddleware
from inkflow.api.middleware.docs_gate import DocsGateMiddleware
from inkflow.api.middleware.token_auth import TokenAuthMiddleware
from inkflow.api.routers import (
    agent,
    agent_runs,
    agent_templates,
    agents,
    audit,
    books,
    chapter,
    chapter_audit,
    characters,
    chat_messages,
    chat_stream,
    context,
    export,
    extractions,
    foreshadowings,
    i18n,
    index,
    knowledge_graph,
    logs,
    maps,
    mcp,
    memory,
    outlines,
    project,
    provider_configs,
    search,
    sessions,
    settings,
    skills,
    style,
    timeline,
    world_settings,
    writing,
)

# #766 阶段③：chat_resume 的 Depends(get_chat_agent_service) 依赖 chat_stream 模块级
# 注册 deps.ChatStreamRequest（FastAPI 注解求值），必须在 chat_stream 之后导入。
from inkflow.api.routers import chat_resume as chat_resume_router
from inkflow.api.routers import (
    config as config_router,
)
from inkflow.core.config import config
from inkflow.core.database import (
    async_session_factory,
    create_tables,
    engine,
    ensure_agent_executions_hitl_payload_column,
    ensure_agent_executions_relations_column,
    ensure_agent_executions_thread_id_column,
    ensure_agent_executions_trace_column,
    ensure_agent_role_key_column,
    ensure_agents_grants_column,
    ensure_character_drop_is_deleted,
    ensure_characters_brief_column,
    ensure_chat_messages_conversation_id_column,
    ensure_chat_messages_is_deleted_column,
    ensure_conversation_title_column,
    ensure_conversations_delete_permission_column,
    ensure_drafts_volume_id_column,
    ensure_foreshadowing_drop_is_deleted,
    ensure_map_columns,
    ensure_outline_columns,
    ensure_outline_drop_is_deleted,
    ensure_outline_volume_id_column,
    ensure_preference_superseded_column,
    ensure_project_columns,
    ensure_project_watermark_column,
    ensure_provider_builtin_key_column,
    ensure_timeline_drop_is_deleted,
    ensure_user_preference_superseded_column,
    ensure_world_categories,
    ensure_world_categories_kind_column,
    ensure_world_drop_is_deleted,
    ensure_world_parent_id_column,
    ensure_world_root_unique_index,
    ensure_writing_plan_progress_reason_column,
    run_character_group_members_migration,
)
from inkflow.core.log import setup_logging
from inkflow.core.startup_reconcile import reconcile_stale_running_plans
from inkflow.domain.ports.extraction_errors import RAGUnavailableError
from inkflow.domain.services.agent_entity_service import seed_builtin_agents
from inkflow.domain.services.skill_service import (
    ensure_builtin_skills,
    migrate_skills_from_db,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理——启动/关闭钩子。"""
    from inkflow.core.langsmith_tracing import apply_langsmith_tracing

    apply_langsmith_tracing()
    setup_logging()
    await create_tables()
    # #126 A1：旧库轻量列迁移 —— create_tables 之后、seed 之前补 builtin_key 列，
    # 新库 create_all 已含列（no-op）；旧库加列后由 seed 按 name 命中回填。
    async with engine.begin() as conn:
        await conn.run_sync(ensure_agent_executions_hitl_payload_column)
        await conn.run_sync(ensure_agent_executions_relations_column)
        await conn.run_sync(ensure_agent_executions_thread_id_column)
        await conn.run_sync(ensure_agent_executions_trace_column)
        await conn.run_sync(ensure_agent_role_key_column)
        await conn.run_sync(ensure_agents_grants_column)
        await conn.run_sync(ensure_provider_builtin_key_column)
        await conn.run_sync(ensure_project_columns)
        await conn.run_sync(ensure_project_watermark_column)
        await conn.run_sync(ensure_preference_superseded_column)
        await conn.run_sync(ensure_user_preference_superseded_column)
        await conn.run_sync(ensure_world_parent_id_column)
        await conn.run_sync(ensure_world_categories_kind_column)
        await conn.run_sync(ensure_world_categories)
        await conn.run_sync(ensure_map_columns)
        await conn.run_sync(ensure_outline_columns)
        await conn.run_sync(ensure_outline_volume_id_column)
        await conn.run_sync(ensure_drafts_volume_id_column)
        await conn.run_sync(ensure_world_drop_is_deleted)
        await conn.run_sync(ensure_world_root_unique_index)
        await conn.run_sync(ensure_character_drop_is_deleted)
        await conn.run_sync(ensure_characters_brief_column)
        await conn.run_sync(ensure_outline_drop_is_deleted)
        await conn.run_sync(ensure_timeline_drop_is_deleted)
        await conn.run_sync(ensure_foreshadowing_drop_is_deleted)
        await conn.run_sync(ensure_chat_messages_is_deleted_column)
        await conn.run_sync(ensure_chat_messages_conversation_id_column)
        await conn.run_sync(ensure_conversation_title_column)
        await conn.run_sync(ensure_conversations_delete_permission_column)
        await conn.run_sync(ensure_writing_plan_progress_reason_column)
    # #831：角色分组 N:M 迁移需重建 characters 表移除旧 group_id 列。旧列被 FK
    # 引用时 SQLite DROP COLUMN 会拒止（#820 残留回归）；且在主迁移事务（FK=ON）
    # 内无法通过 PRAGMA foreign_keys=OFF 切换（事务内 no-op），直接 DROP 会沿 FK
    # CASCADE 清空 character_relations / 回填后的 character_group_members（数据丢失）。
    # 故在独立 AUTOCOMMIT 连接上以 FK=OFF 执行（见 run_character_group_members_migration），
    # 位于主迁移事务提交之后避免写锁冲突。
    await run_character_group_members_migration()
    # #106 F1：启动后幂等 seed 内置 4 provider（ProviderConfigService 同名跳过，
    # 全新安装注册表为空 → seed 补全；重复启动不重复插入）
    async with async_session_factory() as session:
        await get_provider_config_service(session).seed_builtin_providers()
        # #522 ADR-039：skill 存储去表改文件系统真源——启动先幂等回补内置
        # 6 skill（data_dir/skills/<name>/SKILL.md，删了回补），再一次性迁移
        # 旧 skills 表 user_upload 行（raw SQL，表不存在返回 0），最后 seed
        # 内置 Agent（skill_ids 已为目录名英文 slug，无需先 seed skill）
        ensure_builtin_skills(config.data_dir / "skills")
        await migrate_skills_from_db(session, config.data_dir / "skills")
        await seed_builtin_agents(session)
    # #953：内核启动对账——重启后 writing_plans 残留 running 态 → failed（防 422
    # 「存在进行中的」挡掉重跑）；须在 seed 之后、scheduler 之前执行
    await reconcile_stale_running_plans(async_session_factory)
    # #479 G2: 知识图谱定时提取调度器装配（应用级 session 长活，shutdown 关闭；
    # 手动触发端点与定时触发共用 RelationExtractionService，G1 契约
    # extraction_run_repo=None，run 记录落盘归 #496 承接）
    from inkflow.api.deps_kg_extract import get_relation_extraction_service
    from inkflow.domain.services.settings_service import SettingsService
    from inkflow.infrastructure.database.repositories.project_repo import (
        SQLiteProjectRepository,
    )
    from inkflow.infrastructure.database.repositories.settings_repo import (
        SQLiteSettingsRepository,
    )
    from inkflow.infrastructure.scheduler.kg_extract_scheduler import (
        KnowledgeExtractScheduler,
    )

    scheduler_session = async_session_factory()
    scheduler = KnowledgeExtractScheduler(
        settings_service=SettingsService(SQLiteSettingsRepository(scheduler_session)),
        project_repository=SQLiteProjectRepository(scheduler_session),
        relation_extraction_service=get_relation_extraction_service(scheduler_session),
        extraction_run_repo=None,
    )
    await scheduler.start()
    app.state.kg_scheduler = scheduler
    app.state.kg_session = scheduler_session
    yield
    await scheduler.stop()
    await scheduler_session.close()
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

# ---- Docs 门控（S3f-T1 G1 #869，纯 ASGI；注册在 token_auth 之后 = 外层：
#       后注册者先执行——非 debug /docs /redoc 404 先于 token 401；debug 透传后
#       token 豁免语义不变） ----
app.add_middleware(DocsGateMiddleware)

# ---- X-Correlation-Id 沿用（B4 #496，纯 ASGI；注册在 DocsGate 之后 = 最外层：
#       请求最早进入即设置 contextvar，覆盖整个请求生命周期的埋点链路） ----
app.add_middleware(CorrelationIdMiddleware)


# ---- 全局异常处理：RAG 向量库不可用（#341，覆盖端点构造期与前置刷新冒泡）----
@app.exception_handler(RAGUnavailableError)
async def _rag_unavailable_handler(request: Request, exc: RAGUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ---- 注册路由 ----
app.include_router(audit.router)
app.include_router(export.router)
app.include_router(project.router)
app.include_router(provider_configs.router)
app.include_router(agent_templates.router)
app.include_router(style.router)
app.include_router(config_router.router)
app.include_router(chapter.router)
app.include_router(chapter_audit.router)
app.include_router(characters.router)
app.include_router(maps.router)
app.include_router(mcp.router)
app.include_router(writing.router)
app.include_router(chat_stream.router)
app.include_router(chat_resume_router.router)
app.include_router(agent.router)
app.include_router(books.router)
app.include_router(agent_runs.router)
app.include_router(agents.router)
app.include_router(skills.router)
app.include_router(memory.router)
app.include_router(context.router)
app.include_router(world_settings.router)
app.include_router(outlines.router)
app.include_router(timeline.router)
app.include_router(foreshadowings.router)
app.include_router(knowledge_graph.router)
app.include_router(extractions.router)
app.include_router(sessions.router)
app.include_router(chat_messages.router)
app.include_router(settings.router)
app.include_router(logs.router)
app.include_router(index.router)
app.include_router(i18n.router)
app.include_router(search.router)


# ---- 健康检查 ----
@app.get("/health", tags=["系统"])
async def health_check():
    """服务健康检查端点。"""
    return {"status": "ok", "version": inkflow.__version__, "mode": config.mode}
