"""F27 覆盖率缺口补测 B — SQLiteAgentRunRepository.save + agentic_writer 装配.

原 test_f27_coverage_gaps.py 拆分（1131 行超 monster-file 900 护栏，2026-08-10）。
代码已实现（GREEN），补测直接通过（非 RED）。

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
WRONG_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")  # #275: 与请求上下文不符的伪造 id


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    """模板渲染：load("writer_agent") + render 结果 messages[0] 为 system prompt。

    #275 契约升级：无参调用向后兼容——render 变量 dict 恒含 project_id/chapter_id 键
    （值为空串），模板变量化后 validate() 仍通过。
    """
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
    pm.render.assert_called_once_with(template, {"project_id": "", "chapter_id": ""})
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


# ── #275: 系统提示注入 project_id/chapter_id（工具上下文装配契约） ──


def test_build_writer_agent_system_prompt_injects_project_context() -> None:
    """#275 装配契约: 传 project_id/chapter_id → render 收到真实值 + 结果含二者.

    RED 预期: 当前实现 render(template, {}) → assert_called_once_with 断言失败
    （clean FAILED）。
    """
    from inkflow.infrastructure.agent.agentic_writer import (
        build_writer_agent_system_prompt,
    )

    pm = MagicMock()
    template = MagicMock()
    template.system_prompt = "SP {project_id} {chapter_id}"
    pm.load.return_value = template
    rendered = MagicMock()
    rendered.messages = [{"content": f"SP {PROJECT_ID} {CHAPTER_ID}"}]
    pm.render.return_value = rendered

    result = build_writer_agent_system_prompt(
        pm,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
    )

    pm.render.assert_called_once_with(
        template,
        {"project_id": str(PROJECT_ID), "chapter_id": str(CHAPTER_ID)},
    )
    assert str(PROJECT_ID) in result
    assert str(CHAPTER_ID) in result


async def test_build_agentic_writer_forwards_context_to_save_draft_tool() -> None:
    """#718 装配契约: build_agentic_writer 注入期望上下文 → save_draft 工具绑定上下文
    （LLM 传入的 project_id 被忽略，工具总是使用 deps.expected_*——比 #275 防御更强，
    杜绝编造全零 UUID 落孤儿数据）。

    #718 语义变更: 旧 #275 是「参数与期望不符 → 拒绝 {ok:false}」；新契约是「装配期
    绑定，工具总是使用 deps.expected_*（忽略 caller 传入的冲突 id）」——这个变更消除了
    chat 写工具因 LLM 误报 project_id 导致 {ok:false} → 循环失败的「无限 running」根因。
    """
    from inkflow.domain.models.draft import Draft, DraftStatus
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
        try:
            build_agentic_writer(
                model="zhipu/glm-4.5",
                api_key="k",
                base_url="http://x",
                deps=deps,
                system_prompt="SP",
                expected_project_id=PROJECT_ID,
                expected_chapter_id=CHAPTER_ID,
            )
        except TypeError as exc:
            pytest.fail(f"build_agentic_writer 应支持 expected_project_id（#718）: {exc}")

    tools = mock_build.call_args.kwargs["tools"]
    save_tool = next(t for t in tools if t.spec.name == "save_draft")

    deps.draft_service.create.return_value = Draft(
        id="draft-275",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="正文",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )

    # 传入「错误」project_id：工具忽略 caller 值，绑定 deps.expected_project_id → 成功落库
    # （旧 #275 契约: {ok:false} 拒绝 → 本测试已翻转）
    result = await save_tool.func(
        project_id=WRONG_ID,
        chapter_id=CHAPTER_ID,
        content="正文",
    )
    assert '"ok": true' in result
    create_call = deps.draft_service.create.await_args
    assert create_call.kwargs["project_id"] == PROJECT_ID  # 绑定到装配期期望值（忽略 WRONG_ID）
    assert create_call.kwargs["chapter_id"] == CHAPTER_ID

    # 正确 project_id（或省略）→ 同样绑定期望值 → 成功
    deps.draft_service.create.reset_mock()
    right = await save_tool.func(
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="正文",
    )
    assert '"ok": true' in right
    deps.draft_service.create.assert_awaited_once()


async def test_deep_agent_invoke_adapter_sync_result() -> None:
    """#275 覆盖率补测: DeepAgentInvokeAdapter 同步返回分支——inner.invoke
    返回非 Awaitable dict → 直接透传（真实 deepagents graph 为同步方法）."""
    from inkflow.infrastructure.agent.agentic_writer import DeepAgentInvokeAdapter

    inner = MagicMock()
    inner.invoke = MagicMock(return_value={"messages": [{"type": "ai", "content": "正文。"}]})
    adapter = DeepAgentInvokeAdapter(inner)

    result = await adapter.invoke([{"type": "user", "content": "你好"}])

    assert result["messages"][0]["content"] == "正文。"
    inner.invoke.assert_called_once_with(
        {"messages": [{"type": "user", "content": "你好"}]}, config=None
    )
