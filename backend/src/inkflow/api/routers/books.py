"""F44 书级编排 API 端点：访谈式 Planner + 书级运行（spec §3.1，阶段 1）。"""

from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.agent_book import AgenticBookConfig
from inkflow.domain.models.writing_plan import BookLimits
from inkflow.domain.services.book_service import BookService, ChapterAlreadyWrittenError
from inkflow.domain.services.planner_service import PlannerService
from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline
from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline
from inkflow.infrastructure.agent.execution_store import ExecutionStore
from inkflow.infrastructure.background.tasks import spawn_background_task
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1/agent/books", tags=["Books"])


class PlannerStartRequest(BaseModel):
    """启动访谈会话请求体。"""

    project_id: uuid.UUID
    one_liner: str
    mode: str = "new"
    """起点模式（#544）：new / continue / branch。"""
    source_outline_id: uuid.UUID | None = None
    """起点源大纲 id（continue/branch 用）。"""


class PlannerRespondRequest(BaseModel):
    """回复本轮问题请求体（或 auto=true 全部你决定；confirm=true 末尾总体确认）。"""

    answers: dict[str, str] = Field(default_factory=dict)
    auto: bool = False
    confirm: bool = False
    """末尾总体确认（v1.2 #475：confirming=true 时可用，§3.2）。"""


class BookRunRequest(BaseModel):
    """启动书级运行请求体。"""

    writing_plan_id: uuid.UUID
    limits: dict[str, int] | None = None
    mode: str = "static"
    config: dict | None = None
    """agentic 模式配置透传（仅 mode="agentic" 生效；None → 默认 AgenticBookConfig）。"""


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
    """获取 PlannerService 实例（repo + write_auto/outline/character/LLM 提问装配，#460/#475）。"""
    from inkflow.domain.services.character_service import CharacterService
    from inkflow.domain.services.outline_service import OutlineService
    from inkflow.domain.services.planner_service import PlannerService
    from inkflow.infrastructure.database.repositories.character_repo import (
        SQLiteCharacterRepository,
    )
    from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository
    from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
    from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager
    from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

    outline_svc = OutlineService(repository=SQLiteOutlineRepository(db))
    character_svc = CharacterService(repository=SQLiteCharacterRepository(db))

    async def _project_context_getter(project_id: uuid.UUID) -> str:
        """项目设定摘要：outline/character 已落库内容拼接（供 LLM 针对性提问，§5.1）。"""
        try:
            outline_repo = SQLiteOutlineRepository(db)
            character_repo = SQLiteCharacterRepository(db)
            pid = project_id.int if isinstance(project_id, uuid.UUID) else project_id
            outlines, _ = await outline_repo.list(pid, offset=0, limit=50)
            chars, _ = await character_repo.list(pid, offset=0, limit=50)
            parts: list[str] = []
            for outline in outlines or []:
                name = getattr(outline, "name", "")
                desc = getattr(outline, "description", "")
                if name:
                    parts.append(f"大纲：{name}（{desc}）" if desc else f"大纲：{name}")
            for character in chars or []:
                name = getattr(character, "name", "")
                brief = getattr(character, "brief", "")
                if name:
                    parts.append(f"角色：{name}（{brief}）" if brief else f"角色：{name}")
            return "；".join(parts)[:2000]
        except Exception:
            return ""

    async def _write_auto(project_id: uuid.UUID, one_liner: str) -> object:
        """「全部你决定」委托：复用 AgentService 执行 F42 builtin:write_auto 管线。"""
        from inkflow.api.routers.agent import _svc
        from inkflow.core.database import async_session_factory
        from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest

        async with async_session_factory() as session:
            await _svc(session).execute(
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

    async def _character_service(
        project_id: uuid.UUID,
        name: str,
        extra: dict | None = None,
    ) -> object:
        """访谈完成路径：planner 产出直接落库主角角色，返回含 id 的实体.

        #927/#833：经 CharacterCreate DTO 强校验 role_rank——缺省/缺失补
        protagonist（planner 产出恒为主角），非法 role_rank 抛错不静默落库.
        """
        from inkflow.domain.models.character import CharacterCreate

        if extra is None or "role_rank" not in extra:
            extra = {**(extra or {}), "role_rank": "protagonist"}
        create = CharacterCreate(project_id=project_id, name=name, extra=extra)
        return await character_svc.create_character(
            project_id=create.project_id,
            name=create.name,
            extra=create.extra,
        )

    return PlannerService(
        repo=SQLiteBookRepository(db),
        write_auto=_write_auto,
        outline_service=_outline_service,
        character_service=_character_service,
        llm_client=LangChainLLMClient(),
        project_context_getter=_project_context_getter,
        prompt_manager=LangChainPromptManager(),
        outline_repo=SQLiteOutlineRepository(db),
    )


# 模块级单例（镜像 agent.py _supervisor_pipeline 模式）：checkpointer 存实例内，
# execute/confirm 须同实例——API 每次请求经 get_book_service 复用同一 pipeline
_book_volume_pipeline: BookVolumePipeline | None = None


# F49 自主编排单例（镜像 _book_volume_pipeline）：checkpointer 存实例内，execute/resume
# 须同实例——API 每次请求经 get_book_service 复用同一 pipeline
_book_agentic_pipeline: BookAgenticPipeline | None = None


def _build_book_service(db: AsyncSession) -> BookService:
    """装配真实 BookService（repo + outline_repo + 安全闸 + 上限 + 执行记录 + F27 writer）。"""
    global _book_volume_pipeline, _book_agentic_pipeline
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

    # F27 真实装配（镜像 deps.py get_agentic_writer_service）：writer_factory 每次
    # 委托按传入 system_prompt/expected ids 构造真实 deepagents 写作 agent（读/审计/
    # save_draft 工具），draft_service 供委托回收获草稿——修复 #464 book run 章全 failed
    # （零 token/execution_id=null）静默失败。
    from inkflow.api._llm_resolver import resolve_llm_credentials
    from inkflow.api.deps import (
        get_chapter_audit_service,
        get_chapter_service,
        get_character_service,
        get_foreshadowing_service,
        get_memory_service,
        get_summary_service,
    )
    from inkflow.core.config import config
    from inkflow.domain.services.audit_log_service import AuditLogService
    from inkflow.domain.services.draft_service import DraftService
    from inkflow.infrastructure.agent.agentic_writer import (
        AgenticWriterDeps,
        build_agentic_writer,
    )
    from inkflow.infrastructure.database.repositories.audit_log_repo import (
        SQLiteAuditLogRepository,
    )
    from inkflow.infrastructure.database.repositories.draft_repo import (
        SQLiteDraftRepository,
    )

    draft_service = DraftService(
        draft_repo=SQLiteDraftRepository(db),
        chapter_service=get_chapter_service(db),
        audit_service=AuditLogService(SQLiteAuditLogRepository(db)),
        memory_service=get_memory_service(db),
    )
    deps = AgenticWriterDeps(
        character_service=get_character_service(db),
        foreshadowing_service=get_foreshadowing_service(db),
        summary_service=get_summary_service(db),
        chapter_audit_service=get_chapter_audit_service(db),
        draft_service=draft_service,
        audit_service=AuditLogService(SQLiteAuditLogRepository(db)),
    )

    async def _writer_factory(
        *,
        system_prompt: str,
        expected_project_id: uuid.UUID | None,
        expected_chapter_id: uuid.UUID | None,
    ) -> object:
        """构造真实 F27 writer agent（镜像 deps.py _build_agent：deepagents ReAct 链）。

        #929 R3 per-delegate 解析：每次委托读项目配置模型（_project_config_getter
        兄弟闭包）传入 resolve（#735 agent>项目>全局 链在 book 轨生效），不做装配期
        闭包捕获——装配期只有全局模型可用（#738 假象来源）。
        """
        cfg = (
            await _project_config_getter(expected_project_id)
            if expected_project_id is not None
            else None
        )
        model, api_key, base_url = resolve_llm_credentials(
            config.llm_default_model,
            project_model=getattr(cfg, "model", None),
        )
        return build_agentic_writer(
            model=model,
            api_key=api_key,
            base_url=base_url,
            deps=deps,
            system_prompt=system_prompt,
            expected_project_id=expected_project_id,
            expected_chapter_id=expected_chapter_id,
        )

    if _book_volume_pipeline is None:
        from inkflow.infrastructure.llm import LangChainLLMClient

        _book_volume_pipeline = BookVolumePipeline(
            LangChainLLMClient(),
            writer_factory=_writer_factory,
            draft_service=draft_service,
        )

    if _book_agentic_pipeline is None:
        from inkflow.infrastructure.llm import LangChainLLMClient

        _book_agentic_pipeline = BookAgenticPipeline(
            LangChainLLMClient(),
            writer_factory=_writer_factory,
            draft_service=draft_service,
            audit_callable=LangChainLLMClient().chat,
        )

    return BookService(
        repo=repo,
        outline_repo=outline_repo,
        content_checker=_content_checker,
        project_config_getter=_project_config_getter,
        volume_pipeline=_book_volume_pipeline,
        execution_store=ExecutionStore(db),
        writer_factory=_writer_factory,
        draft_service=draft_service,
        agentic_pipeline=_book_agentic_pipeline,
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
@instrument(caller_type="api")
async def start_planner(
    data: PlannerStartRequest,
    svc: PlannerService = Depends(get_planner_service),
):
    """启动访谈会话，返回第一轮问题（≤5 问）。"""
    try:
        session = await svc.start(
            data.project_id,
            data.one_liner,
            mode=data.mode,
            source_outline_id=data.source_outline_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {
        "session_id": str(session.id),
        "round": session.round,
        "questions": session.asked_questions,
        "max_rounds": 5,
        "confirmed_items": session.confirmed_items,
        "conflicts": session.conflicts,
        "confirming": session.confirming,
    }


@router.get("/planner")
@instrument(caller_type="api")
async def list_planner_sessions(
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    svc: PlannerService = Depends(get_planner_service),
):
    """访谈会话列表（#486 会话页）→ {items, total, offset, limit}.

    project_id / status 精确过滤；items 为 PlannerSession JSON（model_dump mode=json）.
    """
    pid = uuid.UUID(project_id) if project_id is not None else None
    items, total = await svc.list(project_id=pid, status=status, offset=offset, limit=limit)
    return {
        "items": [s.model_dump(mode="json") for s in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/planner/{session_id}/respond")
@instrument(caller_type="api")
async def respond_planner(
    session_id: str,
    data: PlannerRespondRequest,
    svc: PlannerService = Depends(get_planner_service),
):
    """回复本轮问题，返回下一轮问题或完成结果（WritingPlan）。"""
    try:
        result = await svc.respond(
            _parse_id(session_id),
            data.answers,
            auto=data.auto,
            confirm=data.confirm,
        )
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
        "confirmed_items": result.confirmed_items,
        "conflicts": result.conflicts,
        "confirming": result.confirming,
        "writing_plan": (
            result.writing_plan.model_dump(mode="json") if result.writing_plan is not None else None
        ),
    }


@router.get("/planner/{session_id}")
@instrument(caller_type="api")
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
@instrument(caller_type="api")
async def start_run(
    data: BookRunRequest,
    svc: BookService = Depends(get_book_service),
):
    """启动书级运行（202 异步语义）：prepare_run 预校验（错误立即 404/409/422）→
    返回 {run_id, status}；status=running 时后台 asyncio task fire-and-forget
    执行（#456 F44 阶段4 后台任务）。"""
    from inkflow.api._llm_resolver import resolve_llm_credentials
    from inkflow.core.config import config

    # #929 §5b：入口无条件预检（在 prepare_run 改状态之前）——项目感知解析凭据，
    # 保 #860「无凭据 → POST /runs 422 优先于 404」语义；plan 查询异常/None →
    # project_model=None 继续预检，404 判定仍归 prepare_run（拒绝零残留）。
    # 仅真实 BookService 路径执行：dependency_overrides 注入 mock 替身的 API
    # 测试形态由替身 prepare_run 契约自管（预检假 422 会误伤 202/403 用例）。
    if isinstance(svc, BookService):
        try:
            plan = await svc._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
                data.writing_plan_id
            )
        except Exception:
            plan = None
        cfg = None
        if plan is not None and svc._project_config_getter is not None:
            cfg = await svc._project_config_getter(plan.project_id)
        resolve_llm_credentials(
            config.llm_default_model,
            project_model=getattr(cfg, "model", None),
        )

    limits = BookLimits(**data.limits) if data.limits is not None else None
    agentic_config = AgenticBookConfig(**data.config) if data.config is not None else None
    try:
        result = await svc.prepare_run(data.writing_plan_id, limits, mode=data.mode)
    except ChapterAlreadyWrittenError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        detail = str(e)
        if "不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        if "未授权" in detail:
            raise HTTPException(status_code=403, detail=detail) from e
        raise HTTPException(status_code=422, detail=detail) from e
    if result["status"] != "running":
        return result
    spawn_background_task(
        _run_book(svc, data.writing_plan_id, limits, mode=data.mode, config=agentic_config),
        key=result["run_id"],
    )
    return result


async def _run_book(
    svc: BookService,
    plan_id: uuid.UUID,
    limits: BookLimits | None,
    mode: str,
    config: AgenticBookConfig | None = None,
) -> None:
    """后台执行体（fire-and-forget）：write_book/write_book_volume/write_book_agentic
    全量执行；未预期异常 → mark_failed 落库（状态映射 running → failed）。"""
    try:
        if mode == "agentic":
            await svc.write_book_agentic(plan_id, limits, config)
        elif mode == "volume":
            await svc.write_book_volume(plan_id, limits)
        else:
            await svc.write_book(plan_id, limits)
    except Exception:
        with contextlib.suppress(Exception):
            await svc.mark_failed(str(plan_id))


@router.post("/runs/{run_id}/confirm")
@instrument(caller_type="api")
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
@instrument(caller_type="api")
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
@instrument(caller_type="api")
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
@instrument(caller_type="api")
async def get_run_summary(
    run_id: str,
    svc: BookService = Depends(get_book_service),
):
    """书级运行回归摘要（§3.3）：进度树 + 计数器 + steps + next。"""
    result = await svc.get_summary(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return result
