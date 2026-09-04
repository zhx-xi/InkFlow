"""#929 RED 契约：book run 写作凭据「项目感知 + per-delegate」解析。

缺陷背景（rc2 实证，issue #929 R3）：`_build_book_service` 装配期一次性
`resolve_llm_credentials(config.llm_default_model)`（books.py:263）并把结果闭包
捕获进 `_writer_factory`——**项目级 `project.config.model` 从未参与解析**
（#735 agent>项目>全局 链在 book 轨断裂）。rc2 中项目明明配了
deepseek/deepseek-v4-flash，装配却走空全局 → 静默回退捡到 zhipu embedding-3 → 400 1213。

契约（.hermes/plans/contract-929.md §4/§5b）：
- `_writer_factory` 每次委托：读 `_project_config_getter(expected_project_id).model`
  → `resolve_llm_credentials(config.llm_default_model, project_model=<项目模型>)`；
- `_build_book_service` 装配期不再 resolve（解析延迟到委托/预检）；
- `start_run` 入口无条件预检（项目感知，保 #860 无凭据 422 语义）。

【R】= 当前必 FAIL；【G】= 回归守护。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from inkflow.api.deps import get_db
from inkflow.api.routers import books
from inkflow.core.database import Base
from inkflow.domain.models.writing_plan import WritingPlan

MODEL = "deepseek/deepseek-v4-flash"
API_KEY = "test-cred-from-resolver"
BASE_URL = "https://example.test/v1"
RESOLVE_TARGET = "inkflow.api._llm_resolver.resolve_llm_credentials"
BUILDER_TARGET = "inkflow.infrastructure.agent.agentic_writer.build_agentic_writer"


def db_session():
    """sync 版会话工厂（镜像 test_book_key_resolution_860.db_session）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(_setup())


async def adb_session():
    """async 版会话工厂（运行中循环内不可 asyncio.run）。

    StaticPool：共享单一连接（:memory: 每连接独立库——seed 会话提交后
    getter 新会话必须看到同库，镜像 test_lenient_json 先例）。
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
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


def _fake_agent():
    agent = AsyncMock()
    agent.invoke.return_value = {"messages": [], "files": {}}
    return agent


def _reset_singletons() -> None:
    books._book_volume_pipeline = None
    books._book_agentic_pipeline = None


class TestWriterFactoryProjectAware:
    """R1/R3 核心：委托时解析，项目模型进 resolve。"""

    @pytest.mark.asyncio
    async def test_r1_resolve_receives_project_model(self) -> None:
        """【R】_writer_factory 委托时 resolve 收到 project_model=<项目配置模型>。

        RED 形态：当前 model 为装配期闭包常量，委托路径不调 resolve
        （resolve.call_args.kwargs 无 project_model → FAIL）。
        """
        session_factory = await adb_session()
        _reset_singletons()
        project_id = uuid.UUID(int=929)
        with (
            patch(RESOLVE_TARGET, return_value=(MODEL, API_KEY, BASE_URL)) as resolve,
            patch(BUILDER_TARGET, return_value=_fake_agent()),
        ):
            svc = books._build_book_service(session_factory())
            # 真实 getter（books._project_config_getter）读真实空库 → 项目不存在
            # → project_model=None；契约先锁「委托时 resolve 被调且带 project_model kw」
            await svc._writer_factory(
                system_prompt="brief",
                expected_project_id=project_id,
                expected_chapter_id=None,
            )

        assert resolve.call_count >= 1, (
            "#929 R3: 凭据解析必须发生在委托时（项目模型只有委托时才知道），不得装配期闭包捕获"
        )
        _, kwargs = resolve.call_args
        assert "project_model" in kwargs, (
            f"resolve 必须收到 project_model 关键字（#735 链进 book 轨），实际 kwargs={kwargs}"
        )

    @pytest.mark.asyncio
    async def test_r2_project_model_flows_from_real_getter(self) -> None:
        """【R】getter 返回 config.model="zhipu/glm-4.5" → resolve 收到该值 + build 收到其返回模型。

        替换 svc 内真实 getter 为受控替身（books._build_book_service 闭包 getter →
        经由 _writer_factory 触达；此处直接 patch 实例不可行（闭包），故用
        项目先行入库形态：ProjectORM 落 config.model 后委托。
        """
        session_factory = await adb_session()
        _reset_singletons()
        from inkflow.domain.models.project import Project, ProjectConfig
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        project = Project(
            id=uuid.UUID(int=42),  # 占位；repo.add 自增主键，实际 id 以返回值为准
            name="proj-929",
            config=ProjectConfig(model="zhipu/glm-4.5"),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        async def _seed() -> uuid.UUID:
            async with session_factory() as session:
                created: Project = await SQLiteProjectRepository(session).add(project)
                return created.id

        seeded_id = await _seed()

        with (
            patch(
                RESOLVE_TARGET,
                return_value=("zhipu/glm-4.5", "k-z", "https://z.test/v4/"),
            ) as resolve,
            patch(BUILDER_TARGET, return_value=_fake_agent()) as builder,
        ):
            svc = books._build_book_service(session_factory())
            await svc._writer_factory(
                system_prompt="brief",
                expected_project_id=seeded_id,
                expected_chapter_id=None,
            )

        assert resolve.call_args.kwargs.get("project_model") == "zhipu/glm-4.5", (
            "#929 R3: 项目配置的模型必须传入 resolve（#735 优先级链在 book 轨生效）"
        )
        assert builder.call_args.kwargs["model"] == "zhipu/glm-4.5"
        assert builder.call_args.kwargs["api_key"] == "k-z"

    @pytest.mark.asyncio
    async def test_r3_no_assembly_time_resolve(self) -> None:
        """【R】_build_book_service 装配期零 resolve（解析延迟到委托）。

        RED 形态：当前 books.py:263 装配期同步调 resolve 一次 → call_count>=1 FAIL。
        """
        session_factory = await adb_session()
        _reset_singletons()
        with (
            patch(RESOLVE_TARGET, return_value=(MODEL, API_KEY, BASE_URL)) as resolve,
            patch(BUILDER_TARGET, return_value=_fake_agent()),
        ):
            books._build_book_service(session_factory())

        assert resolve.call_count == 0, (
            "#929: 装配期不得解析凭据（闭包捕获 = 项目模型永远不参与）；延迟到 _writer_factory/预检"
        )


class TestStartRunPrecheck:
    """start_run 入口无条件预检（项目感知；422 优先于 404，零状态残留）。"""

    def test_r4_precheck_uses_project_model(self) -> None:
        """【R】POST /runs → resolve 预检调用带 project_model kw（plan 不存在也预检）。"""
        session_factory = db_session()
        _reset_singletons()
        app = FastAPI()
        app.include_router(books.router)
        app.dependency_overrides[get_db] = lambda: session_factory()

        with (
            patch(RESOLVE_TARGET, return_value=(MODEL, API_KEY, BASE_URL)) as resolve,
            patch(BUILDER_TARGET, return_value=_fake_agent()),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/agent/books/runs",
                json={"writing_plan_id": str(uuid.uuid4())},
            )

        assert resolve.called, "#929 §5b: start_run 必须入口预检（422 先于 404 语义保留）"
        assert "project_model" in resolve.call_args.kwargs, (
            f"预检必须项目感知，实际 kwargs={resolve.call_args.kwargs}"
        )
        # plan 不存在 → prepare_run 404（预检 resolve 已成功桩通过）
        assert resp.status_code == 404

    def test_g1_precheck_422_short_circuits_before_prepare(self) -> None:
        """【G】无凭据 → 422 fail-fast，后台任务零启动（#860 契约 3 语义保留）。"""
        session_factory = db_session()
        _reset_singletons()

        def _raise_no_key(_default: str, **kw) -> tuple[str, str, str]:
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
            patch.object(books, "_run_book", side_effect=AssertionError("must not spawn")),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/agent/books/runs",
                json={"writing_plan_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 422, (
            f"预检 422 必须短路（实际 {resp.status_code}——后台任务或已启动假绿）"
        )
