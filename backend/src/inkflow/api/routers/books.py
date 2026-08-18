"""F44 书级编排 API 端点：访谈式 Planner + 书级运行（spec §3.1，阶段 1）。"""

from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.writing_plan import BookLimits
from inkflow.domain.services.book_service import BookService, ChapterAlreadyWrittenError
from inkflow.domain.services.planner_service import PlannerService
from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline
from inkflow.infrastructure.agent.execution_store import ExecutionStore
from inkflow.infrastructure.background.tasks import spawn_background_task

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


class ConfirmRunRequest(BaseModel):
    """卷级 HITL 确认请求体。"""

    approved: bool = False
    decision: str = ""


class InterveneRequest(BaseModel):
    """书级运行干预请求体（§3.2）：pause/resume/redirect/edit。"""

    action: str
    target: str | None = None
    to: str | None = None
    payload: dict | None = None


def get_planner_service(db: AsyncSession = Depends(get_db)) -> PlannerService:
    """获取 PlannerService 实例（repo + write_auto/outline/character 装配，#460）。"""
    from inkflow.domain.services.character_service import CharacterService
    from inkflow.domain.services.outline_service import OutlineService
    from inkflow.domain.services.planner_service import PlannerService
    from inkflow.infrastructure.database.repositories.character_repo import (
        SQLiteCharacterRepository,
    )
    from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository
    from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

    outline_svc = OutlineService(repository=SQLiteOutlineRepository(db))
    character_svc = CharacterService(repository=SQLiteCharacterRepository(db))

    async def _write_auto(project_id: uuid.UUID, one_liner: str) -> object:
        """「全部你决定」委托：复用 AgentService 执行 F42 builtin:write_auto 管线。"""
        from inkflow.api.routers.agent import _svc
        from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest

        await _svc(db).execute(
            PipelineExecuteRequest(
                project_id=project_id,
                pipeline="builtin:write_auto",
                variables={"chapter_title": one_liner},
            )
        )
        return None

    async def _outline_service(
        project_id: uuid.UUID,
        name: str,
        description: str,
        level: str,
    ) -> object:
        """访谈完成路径：planner 产出直接落库整体大纲（level=overall），返回含 id 的实体。"""
        return await outline_svc.create_outline(
            project_id=project_id,
            name=name,
            description=description,
            level=level,
        )

    async def _character_service(project_id: uuid.UUID, name: str) -> object:
        """访谈完成路径：planner 产出直接落库主角角色，返回含 id 的实体。"""
        return await character_svc.create_character(project_id=project_id, name=name)

    return PlannerService(
        repo=SQLiteBookRepository(db),
        write_auto=_write_auto,
        outline_service=_outline_service,
        character_service=_character_service,
    )


# 模块级单例（镜像 agent.py _supervisor_pipeline 模式）：checkpointer 存实例内，
# execute/confirm 须同实例——API 每次请求经 get_book_service 复用同一 pipeline
_book_volume_pipeline: BookVolumePipeline | None = None


def _build_book_service(db: AsyncSession) -> BookService:
    """装配真实 BookService（repo + outline_repo + 安全闸 + 项目级上限 + 执行记录仓储）。"""
    global _book_volume_pipeline
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

    # 卷级编排单例装配：writer_factory/draft_service 先注入 None（构造零风险，
    # BookVolumePipeline 执行时缺失才报错）；真实 writer 装配留待 M2 冒烟
    # （F27 完整装配链，本批先保证 API 契约 + 单例存在）
    if _book_volume_pipeline is None:
        from inkflow.infrastructure.llm import LangChainLLMClient

        _book_volume_pipeline = BookVolumePipeline(
            LangChainLLMClient(),
            writer_factory=None,
            draft_service=None,
        )

    return BookService(
        repo=repo,
        outline_repo=outline_repo,
        content_checker=_content_checker,
        project_config_getter=_project_config_getter,
        volume_pipeline=_book_volume_pipeline,
        execution_store=ExecutionStore(db),
    )


def get_book_service(db: AsyncSession = Depends(get_db)) -> BookService:
    """获取 BookService 实例（薄壳委托 _build_book_service；测试可 dependency_overrides 覆盖）。"""
    return _build_book_service(db)


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
    """启动书级运行（202 异步语义）：prepare_run 预校验（错误立即 404/409/422）→
    返回 {run_id, status}；status=running 时后台 asyncio task fire-and-forget
    执行（#456 F44 阶段4 后台任务）。"""
    limits = BookLimits(**data.limits) if data.limits is not None else None
    try:
        result = await svc.prepare_run(data.writing_plan_id, limits, mode=data.mode)
    except ChapterAlreadyWrittenError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        detail = str(e)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        raise HTTPException(status_code=422, detail=detail) from e
    if result["status"] != "running":
        return result
    spawn_background_task(
        _run_book(svc, data.writing_plan_id, limits, mode=data.mode),
        key=result["run_id"],
    )
    return result


async def _run_book(
    svc: BookService,
    plan_id: uuid.UUID,
    limits: BookLimits | None,
    mode: str,
) -> None:
    """后台执行体（fire-and-forget）：write_book/write_book_volume 全量执行；
    未预期异常 → mark_failed 落库（状态映射 running → failed）。"""
    try:
        if mode == "volume":
            await svc.write_book_volume(plan_id, limits)
        else:
            await svc.write_book(plan_id, limits)
    except Exception:
        with contextlib.suppress(Exception):
            await svc.mark_failed(str(plan_id))


@router.post("/runs/{run_id}/confirm")
async def confirm_run(
    run_id: str,
    data: ConfirmRunRequest,
    svc: BookService = Depends(get_book_service),
):
    """卷级 HITL 确认：waiting_hitl → resume 继续/中止（§3.1/§13.3 M8）。"""
    try:
        return await svc.confirm_run(run_id, approved=data.approved, decision=data.decision)
    except ValueError as e:
        detail = str(e)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        if "未处于等待确认状态" in detail:
            raise HTTPException(status_code=422, detail=detail) from e
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


@router.post("/runs/{run_id}/intervene")
async def intervene_run(
    run_id: str,
    data: InterveneRequest,
    svc: BookService = Depends(get_book_service),
):
    """书级运行干预（pause/resume/redirect/edit，§3.2）：快操作状态落库，异常 404/422。"""
    try:
        return await svc.intervene(
            run_id, action=data.action, target=data.target, to=data.to, payload=data.payload
        )
    except ValueError as e:
        detail = str(e)
        if "运行不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        raise HTTPException(status_code=422, detail=detail) from e


@router.get("/runs/{run_id}/summary")
async def get_run_summary(
    run_id: str,
    svc: BookService = Depends(get_book_service),
):
    """书级运行回归摘要（§3.3）：进度树 + 计数器 + steps + next。"""
    result = await svc.get_summary(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return result
