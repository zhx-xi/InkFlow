"""F44 书级编排 API 端点：访谈式 Planner + 书级运行（spec §3.1，阶段 1）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.writing_plan import BookLimits
from inkflow.domain.services.book_service import BookService, ChapterAlreadyWrittenError
from inkflow.domain.services.planner_service import PlannerService

router = APIRouter(prefix="/api/v1/agent/books", tags=["Books"])


class PlannerStartRequest(BaseModel):
    """启动访谈会话请求体。"""

    project_id: uuid.UUID
    one_liner: str


class PlannerRespondRequest(BaseModel):
    """回复本轮问题请求体（或 auto=true 全部你决定）。"""

    answers: dict[str, str] = Field(default_factory=dict)
    auto: bool = False


class BookRunRequest(BaseModel):
    """启动书级运行请求体。"""

    writing_plan_id: uuid.UUID
    limits: dict[str, int] | None = None
    mode: str = "static"


def get_planner_service(db: AsyncSession = Depends(get_db)) -> PlannerService:
    """获取 PlannerService 实例（repo 注入，测试可 dependency_overrides 覆盖）。"""
    from inkflow.domain.services.planner_service import PlannerService
    from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

    return PlannerService(repo=SQLiteBookRepository(db))


def get_book_service(db: AsyncSession = Depends(get_db)) -> BookService:
    """获取 BookService 实例（repo + outline_repo + 安全闸 + 项目级上限注入）。"""
    from inkflow.domain.services.book_service import BookService
    from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository
    from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

    repo = SQLiteBookRepository(db)

    class _OutlineListAdapter:
        """outline_repo 适配：BookService 传 UUID project_id → 转 int 调真实仓储。

        双体系（outline 表 int 主键 vs F44 UUID）：plan.project_id 是
        uuid.UUID(int=project_int) 形式，.int 即 ORM int 主键。
        """

        def __init__(self, inner: SQLiteOutlineRepository) -> None:
            self._inner = inner

        async def list(self, project_id, **kwargs):
            pid = project_id.int if isinstance(project_id, uuid.UUID) else project_id
            return await self._inner.list(pid, **kwargs)

    outline_repo = _OutlineListAdapter(SQLiteOutlineRepository(db))

    async def _content_checker(chapter_id: uuid.UUID) -> bool:
        """安全阀内容检查：该章已有内容（Chapter.content 非空 或 Draft 存在）→ True。"""
        from inkflow.domain.services.chapter_service import ChapterService
        from inkflow.domain.services.draft_service import (  # noqa: F401  # Draft 检查预留（M2）
            DraftService,
        )

        chapter_svc = ChapterService(db)
        chapter: object | None = await chapter_svc.get_chapter(chapter_id)
        return chapter is not None and bool((getattr(chapter, "content", "") or "").strip())

    async def _project_config_getter(project_id: uuid.UUID):
        """项目级上限默认（Q2=C：ProjectConfig.extra，§2.4/D11）。

        父侧已核实：Project ORM 主键为 int，domain id = uuid.UUID(int=orm.id)
        （project_repo._orm_to_domain L32）——UUID → int 用 project_id.int。
        """
        try:
            from inkflow.infrastructure.database.repositories.project_repo import (
                SQLiteProjectRepository,
            )

            project_repo = SQLiteProjectRepository(db)
            project = await project_repo.get(project_id.int)
            if project is None:
                return None
            return getattr(project, "config", None)
        except Exception:
            return None

    return BookService(
        repo=repo,
        outline_repo=outline_repo,
        content_checker=_content_checker,
        project_config_getter=_project_config_getter,
    )


def _parse_id(id_str: str, detail: str = "会话不存在") -> uuid.UUID:
    """安全解析 UUID，非法时按 404 处理。"""
    try:
        return uuid.UUID(id_str)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=detail) from err


@router.post("/planner", status_code=201)
async def start_planner(
    data: PlannerStartRequest,
    svc: PlannerService = Depends(get_planner_service),
):
    """启动访谈会话，返回第一轮问题（≤5 问）。"""
    session = await svc.start(data.project_id, data.one_liner)
    return {
        "session_id": str(session.id),
        "round": session.round,
        "questions": session.asked_questions,
        "max_rounds": 5,
    }


@router.post("/planner/{session_id}/respond")
async def respond_planner(
    session_id: str,
    data: PlannerRespondRequest,
    svc: PlannerService = Depends(get_planner_service),
):
    """回复本轮问题，返回下一轮问题或完成结果（WritingPlan）。"""
    try:
        result = await svc.respond(_parse_id(session_id), data.answers, auto=data.auto)
    except ValueError as e:
        detail = str(e)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        raise HTTPException(status_code=422, detail=detail) from e
    return {
        "session_id": str(result.session_id),
        "round": result.round,
        "completed": result.completed,
        "questions": result.questions,
        "writing_plan": (
            result.writing_plan.model_dump(mode="json") if result.writing_plan is not None else None
        ),
    }


@router.get("/planner/{session_id}")
async def get_planner_session(
    session_id: str,
    svc: PlannerService = Depends(get_planner_service),
):
    """查询访谈会话状态（已问问题/回答快照）。"""
    session = await svc.get(_parse_id(session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.model_dump(mode="json")


@router.post("/runs", status_code=202)
async def start_run(
    data: BookRunRequest,
    svc: BookService = Depends(get_book_service),
):
    """启动书级运行（202 异步语义），返回 {run_id, status}。"""
    limits = BookLimits(**data.limits) if data.limits is not None else None
    try:
        return await svc.write_book(data.writing_plan_id, limits)
    except ChapterAlreadyWrittenError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        detail = str(e)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        raise HTTPException(status_code=422, detail=detail) from e


@router.get("/runs/{run_id}")
async def get_run_status(
    run_id: str,
    svc: BookService = Depends(get_book_service),
):
    """查询书级运行状态（进度树 + 计数器）。"""
    result = await svc.get_status(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return result
