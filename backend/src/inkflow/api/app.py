"""InkFlow FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from inkflow.api.routers import agent, chapter, characters, context, project, writing
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

# ---- CORS（本地开发允许 React dev server） ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:8765",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8765",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 注册路由 ----
app.include_router(project.router)
app.include_router(chapter.router)
app.include_router(characters.router)
app.include_router(writing.router)
app.include_router(agent.router)
app.include_router(context.router)


# ---- 健康检查 ----
@app.get("/health", tags=["系统"])
async def health_check():
    """服务健康检查端点。"""
    return {"status": "ok", "version": "0.1.0", "mode": config.mode}
