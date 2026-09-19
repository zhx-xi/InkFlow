"""#1309 端到端：POST /api/v1/chat/agent/stream 对「项目有 model / 全局空」→ 非 422.

与同族单测（test_deps_chat_agent_project_model_fallback_1309.py）的分工：
- 单测：装配函数粒度，锚回退链四条契约
- 本文件：**真实 HTTP 端点**粒度，锚「消费面（chat_stream `/agent/stream` +
  chat_resume `/resume`）经 FastAPI 依赖注入后不再 422」——issue §消费面 点名

真实内存库 + 真实 ProjectService 落项目 `config.model`，只桩 LLM 构建面。

⚠️ 污染防御（实测教训）：所有 patch 经**单个 `ExitStack`** 进出，绝不用
`p.start()` / `p.stop()` 手配对——`get_provider_config` 在 `_llm_resolver` 内是
函数级 import，只能 patch 源模块，手配对会在用例边界泄漏给后续用例
（实测 `test_coverage_backfill_batch3_llm` 全家反噬）。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import inkflow.api.deps as deps_module
from inkflow.api.routers import chat_resume as chat_resume_mod
from inkflow.api.routers import chat_stream
from inkflow.core.database import Base
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

PROJECT_MODEL = "zhipu/glm-4.5"

_FAKE_TOOL = Tool(
    spec=ToolSpec(name="search_characters", description="", input_schema={}),
    func=MagicMock(),
)

# 装配栈里返回空工具表的工厂
_EMPTY_LIST_FACTORIES = (
    "build_setting_write_tools",
    "build_setting_update_tools",
    "build_outline_tools",
    "build_world_rw_tools",
    "build_memory_tools",
    "build_writing_tools",
    "build_agent_chain_tools",
)


def _make_session_factory():
    """模块级 in-memory SQLite 会话工厂（镜像 test_book_deps_assembly.py）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(_setup())


def _seed_project(session_factory, model: str | None = None) -> uuid.UUID:
    """真实 repo 落一个项目，返回 domain `Project.id`（= uuid.UUID(int=rows.id)）.

    ⚠️ `projects.id` 是自增 int，repo 的 `_orm_to_domain` 把它转成
    `uuid.UUID(int=orm.id)` 作为 domain `Project.id`。故必须省掉 `Project.id`
    让 DB 自增——手填 id 会让 PK 错位（`get()` 返 None，端点静默软回退到全局）。
    """
    now = datetime.now(UTC)
    result: dict[str, object] = {}

    async def _seed():
        async with session_factory() as session:
            repo = SQLiteProjectRepository(session)
            result["project"] = await repo.add(
                Project.model_construct(
                    name="回退测试项目",
                    config=ProjectConfig(model=model),
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

    asyncio.run(_seed())
    return result["project"].id  # type: ignore[union-attr]  # domain Project.id


def _client(session_factory) -> TestClient:
    """真实 app（chat_stream + chat_resume 两消费面），DB 走真实 session 工厂."""
    app = FastAPI()
    app.include_router(chat_stream.router)
    app.include_router(chat_resume_mod.router)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[deps_module.get_db] = _override_db
    return TestClient(app)


@contextmanager
def _stubbed_request(session_factory, provider_cfg):
    """单次请求的全部 patch：单个 ExitStack 进出，退出即完全还原.

    - `core.database.async_session_factory` 指向测试库（`get_session` 读模块全局）
    - `inkflow.core.config.config` → 全局默认模型为空（本 issue 触发条件）
    - LLM 构建面 / provider 解析 → 桩，无需真 key 与网络
    """
    import inkflow.core.database as core_db

    async def _gen():
        async with session_factory() as session:
            yield session

    with ExitStack() as stack:
        stack.enter_context(patch.object(core_db, "async_session_factory", session_factory))
        stack.enter_context(patch.object(deps_module, "get_db", _gen))

        m_config = stack.enter_context(patch("inkflow.core.config.config"))
        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_config.llm_reasoning_effort = None

        stack.enter_context(
            patch("inkflow.api.deps.build_reader_tools", MagicMock(return_value=[_FAKE_TOOL]))
        )
        stack.enter_context(
            patch("inkflow.api.deps.build_save_draft_tool", MagicMock(return_value=_FAKE_TOOL))
        )
        for name in _EMPTY_LIST_FACTORIES:
            stack.enter_context(patch(f"inkflow.api.deps.{name}", MagicMock(return_value=[])))
        stack.enter_context(
            patch("inkflow.api.deps.build_deep_agent", MagicMock(return_value=MagicMock()))
        )
        stack.enter_context(
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                provider_cfg,
            )
        )
        yield


def _ok_provider() -> MagicMock:
    """provider 解析成功桩（项目模型有凭据）."""
    return MagicMock(
        return_value=LLMProviderConfig(
            provider="zhipu",
            api_key="test-key",
            base_url="https://example.invalid/v1",
            default_model=PROJECT_MODEL,
            models=["glm-4.5"],
        )
    )


def test_agent_stream_not_422_when_project_model_set() -> None:
    """项目有 model / 全局空 → 端点不得 422（缺陷态：装配期 fail-fast 422）."""
    session_factory = _make_session_factory()
    project_id = _seed_project(session_factory, model=PROJECT_MODEL)
    client = _client(session_factory)

    with _stubbed_request(session_factory, _ok_provider()):
        resp = client.post(
            "/api/v1/chat/agent/stream",
            json={"project_id": str(project_id), "prompt": "你好"},
        )

    assert resp.status_code != 422, (
        f"#1309: 项目 config.model={PROJECT_MODEL} 有值 + 全局空时不得 422；"
        f"实际 {resp.status_code} {resp.text[:300]}"
    )


def test_agent_stream_422_when_both_models_empty() -> None:
    """两者皆空 → 仍 422（保持原语义；反向锚：证明上例非「永不 422」假绿）."""
    session_factory = _make_session_factory()
    project_id = _seed_project(session_factory, model=None)
    client = _client(session_factory)

    provider = MagicMock(side_effect=ValueError("API key not configured for provider"))
    with _stubbed_request(session_factory, provider):
        resp = client.post(
            "/api/v1/chat/agent/stream",
            json={"project_id": str(project_id), "prompt": "你好"},
        )

    assert resp.status_code == 422
    assert "默认模型" in resp.text or "model" in resp.text.lower()


@pytest.mark.parametrize("endpoint", ["/api/v1/chat/agent/stream", "/api/v1/chat/resume"])
def test_consuming_endpoints_resolve_project_model(endpoint: str) -> None:
    """issue §消费面 两条端点均不得因项目模型有值 / 全局空而 422."""
    session_factory = _make_session_factory()
    project_id = _seed_project(session_factory, model=PROJECT_MODEL)
    client = _client(session_factory)

    body = (
        {"conversation_id": str(uuid.uuid4()), "approved": True}
        if endpoint.endswith("resume")
        else {"project_id": str(project_id), "prompt": "你好"}
    )
    with _stubbed_request(session_factory, _ok_provider()):
        resp = client.post(endpoint, json=body)

    assert resp.status_code != 422, f"{endpoint} 不得回退失败：{resp.status_code} {resp.text[:200]}"
