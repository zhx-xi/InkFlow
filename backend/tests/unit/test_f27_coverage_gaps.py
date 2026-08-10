"""F27 覆盖率缺口补测 — DraftService/AuditLogService/装配层/save/异常分支（coverage-gap 补测模式）.

代码已实现（GREEN 落盘），本文件补测应直接通过（非 RED）。
覆盖缺口（coverage report 2026-08-10）：
- draft_service.py 26%：confirm/reject 全流程 + create 校验
- audit_log_service.py 53%：record 成功/异常静默
- agentic_writer_service.py 83%：invoke 抛错 → FAILED；BaseMessage 对象形态（非 dict）
- agent_run_repo.py 72%：save 方法（insert/update 双路径）
- agentic_writer.py 77%：build_writer_agent_system_prompt / build_agentic_writer 装配
- agent_runs.py 82%：reject 404/409 + _parse_id 非法 UUID

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
DRAFT_ID = "draft-0001"
RUN_ID = "run-0001"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _draft(**overrides) -> dict:
    d = {
        "id": DRAFT_ID,
        "project_id": PROJECT_ID,
        "chapter_id": CHAPTER_ID,
        "content": "草稿正文。",
        "status": "draft",
        "summary": "测试",
        "created_at": _utcnow(),
        "confirmed_at": None,
    }
    d.update(overrides)
    return d


# ── DraftService 全流程（mock 依赖） ────────────────────────────────


def _make_draft_service(**overrides):
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    chapter = AsyncMock()
    audit = AsyncMock()
    svc = DraftService(draft_repo=repo, chapter_service=chapter, audit_service=audit, **overrides)
    return svc, {"repo": repo, "chapter": chapter, "audit": audit}


async def test_draft_create_empty_content_rejected():
    """create 空 content → ValueError（service 层校验，ADR-F 约束①）。"""
    svc, _ = _make_draft_service()
    with pytest.raises(ValueError, match="不能为空"):
        await svc.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="   ")


async def test_draft_create_success_with_audit():
    """create 成功 → repo.create 一次 + audit draft_saved。"""
    from inkflow.domain.models.draft import Draft, DraftStatus

    svc, deps = _make_draft_service()
    deps["repo"].create.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="草稿正文。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    draft = await svc.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="草稿正文。")
    assert draft.id == DRAFT_ID
    deps["repo"].create.assert_awaited_once()
    deps["audit"].record.assert_awaited_once()
    assert "draft_saved" in str(deps["audit"].record.await_args)


async def test_draft_confirm_not_found():
    """confirm 草稿不存在 → DraftNotFoundError。"""
    from inkflow.domain.services.draft_service import DraftNotFoundError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = None
    with pytest.raises(DraftNotFoundError):
        await svc.confirm(DRAFT_ID)


async def test_draft_confirm_state_error():
    """confirm 状态非 draft → DraftStateError（重复确认 409 语义）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftStateError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    with pytest.raises(DraftStateError):
        await svc.confirm(DRAFT_ID)


async def test_draft_confirm_no_target_chapter():
    """confirm 无目标章节（draft 与参数均无）→ DraftStateError。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftStateError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=None,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    with pytest.raises(DraftStateError):
        await svc.confirm(DRAFT_ID)


async def test_draft_confirm_success():
    """confirm 成功 → chapter_service.update_chapter + CONFIRMED + audit。"""
    from inkflow.domain.models.chapter import ChapterStatus
    from inkflow.domain.models.draft import Draft, DraftStatus

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="确认正文。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    deps["repo"].update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="确认正文。",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    confirmed = await svc.confirm(DRAFT_ID)
    assert confirmed.status == DraftStatus.CONFIRMED
    # 经 chapter_service.update_chapter（内容 + status=FINAL，service 层不碰 ORM）
    deps["chapter"].update_chapter.assert_awaited_once()
    dto = deps["chapter"].update_chapter.await_args.args[1]
    assert dto.content == "确认正文。"
    assert dto.status == ChapterStatus.FINAL
    deps["repo"].update_status.assert_awaited_once()
    deps["audit"].record.assert_awaited_once()
    assert "draft_confirmed" in str(deps["audit"].record.await_args)


async def test_draft_reject_success():
    """reject 成功 → REJECTED + audit draft_rejected。"""
    from inkflow.domain.models.draft import Draft, DraftStatus

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    deps["repo"].update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.REJECTED,
        created_at=_utcnow(),
    )
    rejected = await svc.reject(DRAFT_ID)
    assert rejected.status == DraftStatus.REJECTED
    deps["audit"].record.assert_awaited_once()
    assert "draft_rejected" in str(deps["audit"].record.await_args)


async def test_draft_reject_not_found():
    """reject 草稿不存在 → DraftNotFoundError。"""
    from inkflow.domain.services.draft_service import DraftNotFoundError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = None
    with pytest.raises(DraftNotFoundError):
        await svc.reject(DRAFT_ID)


# ── AuditLogService ─────────────────────────────────────────────────


async def test_audit_log_record_success():
    """record 成功 → repo.add 收到构造好的 AuditLog（actor 拼 summary 前缀）。"""
    from inkflow.domain.services.audit_log_service import AuditLogService

    repo = AsyncMock()
    svc = AuditLogService(repo)
    await svc.record(
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        severity_summary="draft_saved",
        summary="草稿保存 10 字",
        degraded=True,
        actor="agent:writer",
    )
    repo.add.assert_awaited_once()
    added = repo.add.await_args.args[0]
    assert added.project_id == PROJECT_ID
    assert added.chapter_id == CHAPTER_ID
    assert added.severity_summary == "draft_saved"
    assert "[agent:writer]" in added.summary
    assert added.degraded is True


async def test_audit_log_record_silent_on_error():
    """repo.add 抛错 → 返回 None 不抛出（记录失败不影响主流程）。"""
    from inkflow.domain.services.audit_log_service import AuditLogService

    repo = AsyncMock()
    repo.add.side_effect = RuntimeError("db down")
    svc = AuditLogService(repo)
    result = await svc.record(project_id=PROJECT_ID, severity_summary="x")
    assert result is None


# ── SQLiteAgentRunRepository.save（真实 SQLite 轨） ──────────────────


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite（ORM 惰性导入必须在 create_all 之前——规则 1l）。"""

    # 惰性导入注册全部相关表（create_all 依赖 Base.metadata 已注册）
    from inkflow.infrastructure.database.models.agent_run import (  # noqa: F401  # 惰性导入注册 ORM 表（create_all 依赖 metadata）
        AgentRunORM,
        DraftORM,
    )
    from inkflow.infrastructure.database.models.chapter import (  # noqa: F401  # 惰性导入注册 ORM 表（create_all 依赖 metadata）
        ChapterORM,
        VolumeORM,
    )
    from inkflow.infrastructure.database.models.project import (
        ProjectORM,  # noqa: F401  # 惰性导入注册 ORM 表（create_all 依赖 metadata）
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """1 个项目。"""
    from inkflow.infrastructure.database.models.project import ProjectORM

    proj = ProjectORM(name="测试项目")
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


async def test_agent_run_repo_save_insert(db_session, project):
    """save 不存在 run → insert（running 状态可读回）。"""
    from inkflow.domain.models.agent_run import AgentRun, AgentRunStatus
    from inkflow.infrastructure.database.repositories.agent_run_repo import (
        SQLiteAgentRunRepository,
    )

    repo = SQLiteAgentRunRepository(db_session)
    run = AgentRun(
        id=RUN_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        status=AgentRunStatus.RUNNING,
        steps=[],
        model="",
        token_usage_total=0,
        terminated_by="",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    saved = await repo.save(run)
    assert saved is not None
    assert saved.id == RUN_ID
    fetched = await repo.get(RUN_ID)
    assert fetched is not None
    assert fetched.status == AgentRunStatus.RUNNING


async def test_agent_run_repo_save_update(db_session, project):
    """save 已存在 run → 更新最终态（steps JSON 快照写回）。"""
    from inkflow.domain.models.agent_run import (
        AgentRun,
        AgentRunStatus,
        AgentStep,
        AgentToolCall,
    )
    from inkflow.infrastructure.database.repositories.agent_run_repo import (
        SQLiteAgentRunRepository,
    )

    repo = SQLiteAgentRunRepository(db_session)
    run = AgentRun(
        id=RUN_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        status=AgentRunStatus.RUNNING,
        steps=[],
        model="",
        token_usage_total=0,
        terminated_by="",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    await repo.save(run)
    step = AgentStep(
        index=0,
        message_content="",
        tokens=120,
        tool_calls=[
            AgentToolCall(
                step_index=0,
                tool_name="search_characters",
                arguments={"project_id": str(PROJECT_ID)},
                result='{"ok": true, "data": []}',
            )
        ],
    )
    run.status = AgentRunStatus.COMPLETED
    run.steps = [step]
    run.final_content = "最终正文。"
    run.token_usage_total = 420
    run.terminated_by = "llm"
    await repo.save(run)
    fetched = await repo.get(RUN_ID)
    assert fetched is not None
    assert fetched.status == AgentRunStatus.COMPLETED
    assert fetched.terminated_by == "llm"
    assert len(fetched.steps) == 1
    assert fetched.steps[0].tool_calls[0].tool_name == "search_characters"


# ── agentic_writer.py 装配（mock build_deep_agent） ─────────────────


def test_build_writer_agent_system_prompt():
    """模板渲染：load("writer_agent") + render 结果 messages[0] 为 system prompt。"""
    from inkflow.infrastructure.agent.agentic_writer import (
        build_writer_agent_system_prompt,
    )

    pm = MagicMock()
    template = MagicMock()
    template.system_prompt = "模板兜底"
    pm.load.return_value = template
    rendered = MagicMock()
    rendered.messages = [{"content": "渲染后的 system prompt"}]
    pm.render.return_value = rendered
    result = build_writer_agent_system_prompt(pm)
    pm.load.assert_called_once_with("writer_agent")
    pm.render.assert_called_once_with(template, {})
    assert result == "渲染后的 system prompt"


async def test_build_agentic_writer_assembles_six_tools():
    """build_agentic_writer → build_deep_agent 收到 6 工具（5 只读 + save_draft）+ 模板 prompt。"""
    from inkflow.infrastructure.agent.agentic_writer import (
        AgenticWriterDeps,
        build_agentic_writer,
    )

    deps = AgenticWriterDeps(
        character_service=AsyncMock(),
        foreshadowing_service=AsyncMock(),
        summary_service=AsyncMock(),
        chapter_audit_service=AsyncMock(),
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
    )
    fake_agent = MagicMock()
    with patch(
        "inkflow.infrastructure.agent.agentic_writer.build_deep_agent",
        return_value=fake_agent,
    ) as mock_build:
        agent = build_agentic_writer(
            model="zhipu/glm-4.5",
            api_key="k",
            base_url="http://x",
            deps=deps,
            system_prompt="SP",
        )
    assert agent is not fake_agent  # 适配器包装（真实冒烟 2026-08-10：deepagents invoke 需 dict）
    assert hasattr(agent, "invoke")  # 服务层契约：仍可 invoke(messages)
    kwargs = mock_build.call_args.kwargs
    assert kwargs["system_prompt"] == "SP"
    assert len(kwargs["tools"]) == 6
    names = [t.spec.name for t in kwargs["tools"]]
    assert names[:5] == [
        "search_characters",
        "check_foreshadowing",
        "get_prior_summary",
        "audit_chapter",
        "count_words",
    ]
    assert names[5] == "save_draft"
    # 适配器 invoke 包装行为：裸消息列表 → {"messages": [...]} dict（真实 graph 形态）
    fake_agent.invoke = AsyncMock(return_value={"messages": [{"type": "ai", "content": "正文。"}]})
    result = await agent.invoke([{"type": "user", "content": "你好"}])
    fake_agent.invoke.assert_awaited_once()
    call = fake_agent.invoke.await_args
    assert call.args[0] == {"messages": [{"type": "user", "content": "你好"}]}
    assert result["messages"][0]["content"] == "正文。"


# ── agentic_writer_service 异常分支 + BaseMessage 双形态 ────────────


async def test_agentic_invoke_error_failed():
    """agent.invoke 抛错 → status=FAILED + save 被调 + 不抛出（ADR-D 防御）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    async def _boom(messages, config=None):
        raise RuntimeError("provider timeout")

    agent = MagicMock()
    agent.invoke = _boom
    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda: agent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.FAILED
    deps["run_repo"].save.assert_awaited()
    deps["audit_service"].record.assert_awaited()
    assert "run_failed" in str(deps["audit_service"].record.await_args)


async def test_agentic_base_message_object_form():
    """BaseMessage 对象形态（非 dict）的消息历史也能映射 steps（_msg_type/_tool_calls 双形态）。"""
    from langchain_core.messages import AIMessage, ToolMessage

    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _ObjAgent:
        """invoke 返回 langchain BaseMessage 对象列表（真实 deepagents 形态）。"""

        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                        response_metadata={"usage": {"total_tokens": 120}},
                    ),
                    ToolMessage(
                        content='{"ok": true, "data": ["角色A"]}',
                        name="search_characters",
                        tool_call_id="call_1",
                    ),
                    AIMessage(
                        content="最终正文。",
                        response_metadata={"usage": {"total_tokens": 300}},
                    ),
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=_ObjAgent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    assert run.terminated_by == "llm"
    assert run.final_content == "最终正文。"
    # 工具调用 result 从 ToolMessage 回填（对象形态）
    tool_names = [tc.tool_name for step in run.steps for tc in step.tool_calls]
    assert "search_characters" in tool_names
    results = [tc.result for step in run.steps for tc in step.tool_calls]
    assert any("角色A" in r for r in results)
    assert run.token_usage_total == 420  # 120 + 300（对象形态 usage 提取）


# ── agent_runs API 边界（reject 404/409 + _parse_id 防御） ──────────


async def test_agent_runs_parse_id_invalid_404():
    """_parse_id 非法 UUID → 404（防御分支）。"""
    from fastapi import HTTPException

    from inkflow.api.routers.agent_runs import _parse_id

    with pytest.raises(HTTPException) as exc_info:
        _parse_id("not-a-uuid")
    assert exc_info.value.status_code == 404


async def test_agent_runs_reject_404():
    """reject 草稿不存在 → 404（端点错误面）。"""
    from httpx import ASGITransport, AsyncClient

    from inkflow.api.app import app
    from inkflow.api.deps import get_draft_service
    from inkflow.domain.services.draft_service import DraftNotFoundError

    draft_svc = MagicMock()
    draft_svc.reject = AsyncMock(side_effect=DraftNotFoundError("草稿不存在"))
    app.dependency_overrides[get_draft_service] = lambda: draft_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/reject")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "草稿不存在"
    finally:
        app.dependency_overrides.clear()


async def test_agent_runs_reject_409():
    """reject 状态非 draft → 409。"""
    from httpx import ASGITransport, AsyncClient

    from inkflow.api.app import app
    from inkflow.api.deps import get_draft_service
    from inkflow.domain.services.draft_service import DraftStateError

    draft_svc = MagicMock()
    draft_svc.reject = AsyncMock(side_effect=DraftStateError("草稿已确认"))
    app.dependency_overrides[get_draft_service] = lambda: draft_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/reject")
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()


# ── 第二轮缺口补测（coverage 98.37/94.90 → 门禁 98.5/95.0） ─────────


# draft_service 剩余分支（get/list 透传 + audit/chapter None）


async def test_draft_get_and_list_passthrough():
    """get/list 透传 repo（覆盖 103-104/124-130）。"""
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.get.return_value = None
    repo.list.return_value = ([], 0)
    svc = DraftService(draft_repo=repo)
    assert await svc.get("nope") is None
    items, total = await svc.list(PROJECT_ID, status=None)
    assert items == [] and total == 0
    repo.list.assert_awaited_once_with(PROJECT_ID, status=None, offset=0, limit=50)


async def test_draft_create_without_audit_service():
    """audit_service=None 时 create 不落审计（覆盖 90->99 分支）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.create.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo, audit_service=None)
    draft = await svc.create(project_id=PROJECT_ID, content="x")
    assert draft.id == DRAFT_ID


async def test_draft_confirm_without_chapter_service():
    """chapter_service=None 时 confirm 跳过章节写入（仅状态流转，覆盖 None 分支）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo, chapter_service=None, audit_service=None)
    confirmed = await svc.confirm(DRAFT_ID)
    assert confirmed.status == DraftStatus.CONFIRMED


async def test_draft_reject_without_audit_service():
    """audit_service=None 时 reject 不落审计。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.REJECTED,
        created_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo, audit_service=None)
    rejected = await svc.reject(DRAFT_ID)
    assert rejected.status == DraftStatus.REJECTED


# agentic_writer_service 剩余边界分支


async def test_agentic_invoke_returns_non_dict():
    """invoke 返回非 dict → history 为空 → steps 空 + completed 防御（覆盖 238/254/263）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _WeirdAgent:
        async def invoke(self, messages, config=None):
            return "not a dict"

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=_WeirdAgent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    # 无 AI 消息 → empty_content 护栏（历史无 AI 消息 → _is_empty_final True）
    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL


async def test_agentic_request_with_context_and_style():
    """请求带 context + style_hint → 初始消息含上下文与风格（覆盖 244/247）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _CaptureAgent:
        def __init__(self):
            self.seen = []

        async def invoke(self, messages, config=None):
            self.seen.append(list(messages))
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"usage": {"total_tokens": 5}},
                    }
                ]
            }

    agent = _CaptureAgent()
    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda: agent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
            context="前文摘要",
            min_words=1500,
            style_hint="冷峻硬汉风",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    initial = agent.seen[0][0]["content"]
    assert "前文摘要" in initial
    assert "1500" in initial
    assert "冷峻硬汉风" in initial


async def test_agentic_token_usage_weird_metadata():
    """usage 非 dict / total_tokens 非法 → token 提取防御（覆盖 88/91-92）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _WeirdMetaAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                        "response_metadata": {"usage": "not-a-dict"},
                    },
                    {"type": "tool", "name": "search_characters", "content": '{"ok": true}'},
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"usage": {"total_tokens": "NaN"}},
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=_WeirdMetaAgent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    assert run.token_usage_total == 0  # 防御：非法 usage 均计 0


async def test_agentic_tool_result_missing():
    """tool_call 无后续同名 tool 消息 → result 空串（覆盖 318->317/320）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _NoResultAgent:
        async def invoke(self, messages, config=None):
            # tool_call 后无对应 tool 消息（异常历史形态）
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"model": "zhipu/glm-4.5"},
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=_NoResultAgent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    assert run.model == "zhipu/glm-4.5"  # 覆盖 _extract_model 命中分支（338）
    results = [tc.result for step in run.steps for tc in step.tool_calls]
    assert any(r == "" for r in results)


async def test_agentic_token_budget_guardrail():
    """累计 tokens 超预算 → token_budget 护栏（覆盖 377）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _TokenHeavyAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"usage": {"total_tokens": 50000}},
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=_TokenHeavyAgent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
        token_budget_default=32000,
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
    assert run.terminated_by == "token_budget"


async def test_agentic_final_tool_calls_defensive_max_steps():
    """最终消息仍含 tool_calls 且无正文 → 防御 max_steps（覆盖 384）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _LoopingAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                    {"type": "tool", "name": "search_characters", "content": '{"ok": true}'},
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c2",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=_LoopingAgent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
        max_steps_default=12,  # 未超 max_steps（2 步 < 12）
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    # 最终含 tool_calls 无正文 → 防御分支 max_steps
    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
    assert run.terminated_by == "max_steps"


# ── 第三轮缺口补测（line 98.46% → 98.5% 门禁） ────────────────────


async def test_draft_confirm_update_status_none_race():
    """confirm 的 update_status 返回 None（确认前被删）→ DraftNotFoundError（覆盖 166）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftNotFoundError, DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = None  # 竞态：确认前被并发删除
    svc = DraftService(draft_repo=repo, audit_service=None)
    with pytest.raises(DraftNotFoundError):
        await svc.confirm(DRAFT_ID)


async def test_draft_reject_state_error():
    """reject 状态非 DRAFT → DraftStateError（覆盖 194-195）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService, DraftStateError

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo)
    with pytest.raises(DraftStateError, match="草稿已确认"):
        await svc.reject(DRAFT_ID)


async def test_draft_reject_update_status_none_race():
    """reject 的 update_status 返回 None（拒绝前被删）→ DraftNotFoundError（覆盖 201）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftNotFoundError, DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = None
    svc = DraftService(draft_repo=repo, audit_service=None)
    with pytest.raises(DraftNotFoundError):
        await svc.reject(DRAFT_ID)


def test_build_writer_agent_system_prompt_fallback():
    """render 结果无 messages → 回退 template.system_prompt（覆盖 agentic_writer.py:53）。"""
    from inkflow.infrastructure.agent.agentic_writer import (
        build_writer_agent_system_prompt,
    )

    pm = MagicMock()
    template = MagicMock()
    template.system_prompt = "模板兜底 prompt"
    pm.load.return_value = template
    rendered = MagicMock()
    rendered.messages = []
    pm.render.return_value = rendered
    result = build_writer_agent_system_prompt(pm)
    assert result == "模板兜底 prompt"


async def test_agentic_final_content_with_tool_history():
    """自然终止 + 历史含 tool 消息 → _final_content 遍历跳过非 ai 消息（覆盖 261->260）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _ToolThenContentAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                    {"type": "tool", "name": "search_characters", "content": '{"ok": true}'},
                    {"type": "ai", "content": "最终正文。", "response_metadata": {"model": "m"}},
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=_ToolThenContentAgent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    assert run.final_content == "最终正文。"
