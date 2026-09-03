"""RED 契约（#860）：book run 书级编排 key 解析与 write next 同源 + 失败态确定性。

缺陷背景（0.12.1rc5 实证，issue #860 P0）：books.py `_build_book_service` 取 key 用
`get_provider_config(provider)` 裸调用 + `except ValueError: pass`（L266-275）→ 全局默认
模型为空或 named provider 无 key 时 `api_key=""` 静默继续 → `build_agentic_writer` 构造
`ChatOpenAI` 缺凭据（harness.py L113 `if api_key:` 短路 → L117 构造抛 OpenAIError）→
`book_service.write_book` 章循环 `except Exception: progress=failed`（L204-209）→ 30 章全
failed、tokens_used=0、顶层 status=completed（假绿）。

对比铁证：同环境 `write next` 走 `deps.get_agentic_writer_service` →
`resolve_llm_credentials(config.llm_default_model)`（api/_llm_resolver.py L40-58，
注册表回退 + 全无 key → HTTPException 422），能拿到 key。两路径 key 解析不一致。

本契约锁定（修复 = `_build_book_service` 复用 `resolve_llm_credentials`）：
1. `_build_book_service` 必须调用 `resolve_llm_credentials(config.llm_default_model)`
   （与 write next 同源同参）。
2. writer agent（build_agentic_writer）必须收到 resolve 返回的非空 model/api_key/base_url。
3. 失败态确定性：全部 provider 无 key → resolve 抛 HTTPException(422) → POST /runs 直接
   422 fail-fast，绝不启动后台任务产出「30 章全 failed 零 token」假绿。
4. 书级 30 章序列化端到端：装配正确的 writer_factory 下，30 章逐章委托 →
   每章 progress=done、tokens_used 累计>0、execution_refs 逐章落库、草稿真实落库。

【mock 策略】resolve_llm_credentials / build_agentic_writer 均为函数级 import →
patch 源码模块属性（#758 references 判别法）；repo/outline_repo 用 AsyncMock 控章序列；
draft_service 用真实装配（in-memory SQLite 验证草稿落库）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from inkflow.api.deps import get_db
from inkflow.api.routers import books
from inkflow.core.database import Base
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import WritingPlan

MODEL = "deepseek/deepseek-v4-flash"
API_KEY = "test-cred-from-resolver"
BASE_URL = "https://example.test/v1"
CHAPTER_TOKENS = 1_200

# resolve_llm_credentials / build_agentic_writer 在 books.py 为函数级 import
# → patch 源码模块属性（#758 判别法：patch 源码模块而非 inkflow.api.routers.books.*）
RESOLVE_TARGET = "inkflow.api._llm_resolver.resolve_llm_credentials"
BUILDER_TARGET = "inkflow.infrastructure.agent.agentic_writer.build_agentic_writer"


def db_session():
    """in-memory SQLite 会话工厂（镜像 test_book_deps_assembly.py；同步测试用）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(_setup())


async def adb_session():
    """async 版会话工厂（pytest-asyncio 运行中循环内不可 asyncio.run）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _plan(project_id: uuid.UUID) -> WritingPlan:
    return WritingPlan(
        id=uuid.uuid4(),
        project_id=project_id,
        title="蜀山，我是掌门",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _chapters(plan: WritingPlan, n: int) -> list[Outline]:
    """n 个 level=chapter 大纲节点（sort_order 升序，chapter_id=None 免正文检查）。"""
    return [
        Outline(
            id=uuid.uuid4(),
            project_id=plan.project_id,
            name=f"第{i + 1}章",
            description=f"第{i + 1}章大纲切片",
            sort_order=i,
            level="chapter",
            parent_id=plan.root_outline_id,
            chapter_id=None,
            extra={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        for i in range(n)
    ]


def _fake_agent():
    """F27 writer agent 替身——真实 graph result 形态（probe_usage.py 2026-09-03 实测）：

    顶层键 = {messages, files}，**无顶层 usage**；token 计数在最终 AIMessage 的
    usage_metadata（dict，含 total_tokens）。顶层 usage dict 是 #860 前的旧自造形态，
    真实 deepagents 从不返回它——锁死真实形态防「零 token 假绿」回归。
    """
    agent = AsyncMock()
    agent.invoke.return_value = {
        "messages": [
            SimpleNamespace(
                content="本章正文内容……",
                tool_calls=[],
                usage_metadata={
                    "input_tokens": 900,
                    "output_tokens": 300,
                    "total_tokens": CHAPTER_TOKENS,
                },
            )
        ],
        "files": {},
    }
    return agent


def _reset_singletons() -> None:
    books._book_volume_pipeline = None
    books._book_agentic_pipeline = None


# ── 契约 1：key 解析与 write next 同源 ─────────────────────────────


def test_build_book_service_uses_resolve_llm_credentials():
    """#860 核心：_build_book_service 必须经 resolve_llm_credentials 解析凭据。

    RED 形态：当前代码直接 get_provider_config + except ValueError: pass，
    resolve 从未被调用 → resolve.called False → 断言失败。
    """
    from inkflow.core.config import config

    session_factory = db_session()
    _reset_singletons()
    with (
        patch(RESOLVE_TARGET, return_value=(MODEL, API_KEY, BASE_URL)) as resolve,
        patch(BUILDER_TARGET, return_value=_fake_agent()),
    ):
        books._build_book_service(session_factory())

    assert resolve.called, (
        "#860: _build_book_service 必须复用 resolve_llm_credentials"
        "（与 write next 同源），不得裸调 get_provider_config + 吞 ValueError"
    )
    assert resolve.call_args.args == (config.llm_default_model,), (
        "resolve_llm_credentials 调用参数必须 = config.llm_default_model"
        "（与 deps.get_agentic_writer_service L278 同源同参）"
    )


# ── 契约 2：writer agent 收到非空凭据 ─────────────────────────────


@pytest.mark.asyncio
async def test_writer_factory_passes_nonempty_credentials():
    """writer_factory 构造 agent 时 model/api_key/base_url 必须为 resolve 返回值。

    RED 形态：当前代码 api_key=""/model="" 传给 build_agentic_writer →
    harness.py:113 `if api_key:` False → ChatOpenAI Missing credentials → 章全 failed。
    断言非空凭据透传即锁死该路径。
    """
    session_factory = await adb_session()
    _reset_singletons()
    fake = _fake_agent()
    with (
        patch(RESOLVE_TARGET, return_value=(MODEL, API_KEY, BASE_URL)),
        patch(BUILDER_TARGET, return_value=fake) as builder,
    ):
        svc = books._build_book_service(session_factory())
        agent = await svc._writer_factory(
            system_prompt="brief",
            expected_project_id=uuid.uuid4(),
            expected_chapter_id=None,
        )

    assert agent is fake
    kwargs = builder.call_args.kwargs
    assert kwargs["api_key"] == API_KEY, "#860: api_key 必须来自 resolve（非空）"
    assert kwargs["model"] == MODEL, "#860: model 必须来自 resolve"
    assert kwargs["base_url"] == BASE_URL


# ── 契约 3：失败态确定性——无 key fail-fast 422，不假绿 ─────────────


def test_start_run_fails_fast_when_no_key_configured():
    """全部 provider 无 key → resolve 抛 HTTPException(422) → POST /runs 422。

    RED 形态：当前代码不调 resolve，装配"成功"→ 后台任务照常启动 →
    30 章全 failed 零 token 顶层 completed 假绿。修复后凭据解析失败必须在
    入口 fail-fast（422），绝不进入章委托。
    """
    session_factory = db_session()
    _reset_singletons()

    def _raise_no_key(_default: str) -> tuple[str, str, str]:
        raise HTTPException(
            status_code=422,
            detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型",
        )

    app = FastAPI()
    app.include_router(books.router)
    app.dependency_overrides[get_db] = lambda: session_factory()

    with (
        patch(RESOLVE_TARGET, side_effect=_raise_no_key),
        patch(BUILDER_TARGET, return_value=_fake_agent()),
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/agent/books/runs",
            json={"writing_plan_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 422, (
        f"#860: 无 key 必须入口 fail-fast 422，实际 {resp.status_code}——"
        "静默放行 → 后台任务 30 章全 failed 零 token 假绿"
    )


# ── 契约 4：30 章序列化端到端——每章 done + tokens_used>0 ────────────


@pytest.mark.asyncio
async def test_book_run_thirty_chapters_all_done_with_tokens():
    """装配正确的 BookService 跑 30 章：progress 全 done、tokens_used 累计>0、
    execution_refs 逐章落库、草稿经真实 DraftService 落库（完成态判据）。

    RED 形态：当前闭包捕获空 key（契约 2 已证）→ 真实环境即 #860 全 failed；
    本用例在正确 resolve 桩下锁定端到端序列化契约，同时防回归。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    session_factory = await adb_session()
    _reset_singletons()
    plan = _plan(uuid.UUID(int=7))
    chapters = _chapters(plan, 30)

    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    repo.update_writing_plan.return_value = None
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, 30)

    with (
        patch(RESOLVE_TARGET, return_value=(MODEL, API_KEY, BASE_URL)),
        patch(BUILDER_TARGET, return_value=_fake_agent()),
    ):
        svc = books._build_book_service(session_factory())

    # repo/outline 控制面替换；writer_factory/draft_service 保持真实装配
    svc._repo = repo
    svc._outline_repo = outline_repo
    svc._content_checker = None
    svc._project_config_getter = None

    result = await svc.write_book(
        plan.id,
        limits=BookLimits(max_chapters=30, max_agent_calls=200, max_tokens=1_000_000),
    )

    assert result["status"] == "completed"
    done = [k for k, v in plan.progress.items() if v == "done"]
    assert len(done) == 30, f"#860 假绿：30 章应全 done，实际进度 {set(plan.progress.values())}"
    assert plan.limits.get("tokens_used") == 30 * CHAPTER_TOKENS, (
        "tokens_used 必须逐章累计>0（零 token = 未真正调 LLM）"
    )
    assert len(plan.execution_refs) == 30, "每章 execution_refs 必须落库（草稿 id）"

    total = (await svc._draft_service.list(plan.project_id, limit=100))[1]
    assert total == 30, f"30 章草稿必须真实落库，实际 {total}"


def test_extract_usage_tokens_branches():
    """_extract_usage_tokens 全分支契约（#860 token 提取修复，新代码全覆盖）：

    1) 消息对象 usage_metadata 属性（真实 deepagents 形态）→ 逐条求和；
    2) 消息 dict 形态 usage_metadata（防御分支）；
    3) 顶层 usage fallback（旧服务层契约形态，无消息 metadata 时）；
    4) 全缺失 → 0（不抛）。
    """
    from inkflow.domain.services.book_service import _extract_usage_tokens

    # 1) 对象属性形态（两条 AIMessage 求和 = ReAct 多轮调用）
    msgs = [
        SimpleNamespace(usage_metadata={"total_tokens": 40}),
        SimpleNamespace(usage_metadata={"total_tokens": 60}),
    ]
    assert _extract_usage_tokens({"messages": msgs}) == 100

    # 2) dict 消息形态（防御分支）
    assert _extract_usage_tokens({"messages": [{"usage_metadata": {"total_tokens": 7}}]}) == 7

    # 3) 顶层 usage fallback（消息无 metadata 且顶层 usage 非零）
    plain = [SimpleNamespace(content="x")]
    assert _extract_usage_tokens({"messages": plain, "usage": {"total_tokens": 12}}) == 12

    # 4) 全缺失 → 0（不抛异常）
    assert _extract_usage_tokens({}) == 0
    assert _extract_usage_tokens({"messages": [SimpleNamespace(content="x")], "usage": {}}) == 0
