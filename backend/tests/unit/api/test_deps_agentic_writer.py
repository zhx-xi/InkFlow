"""F59-M4 (#965) deps_agentic_writer 契约（惰性 db 代理 + re-export 同一性）。

契约（镜像 deps_chat_agent.py 先例）：
- `_get_db` 在**调用期**经 `inkflow.api.deps.get_db` 惰性解析（规避 deps ↔ 本模块
  模块级循环 import——deps.py 在 import 本模块时尚未定义 get_db），并原样透传其
  yield 的 session。
- deps.py 的 re-export 必须是**同一函数对象**（writing.py 与单测从
  `inkflow.api.deps` 导入的命名空间契约）。

存在理由：func-coverage 门禁要求新函数被测试执行≥1 次；本文件同时锁定上述两条
架构契约，防未来改回模块级直取（循环 import）或复制函数体（命名空间漂移）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_get_db_lazy_proxy_forwards_sessions(monkeypatch) -> None:
    """_get_db 调用期解析 deps.get_db 并透传 session（循环 import 规避契约）。"""
    import inkflow.api.deps as deps_module
    from inkflow.api.deps_agentic_writer import _get_db

    sentinel = object()

    async def _fake_get_db():
        yield sentinel

    monkeypatch.setattr(deps_module, "get_db", _fake_get_db)

    collected = [session async for session in _get_db()]

    assert collected == [sentinel], "惰性代理必须透传 deps.get_db 的 session"


def test_get_agentic_writer_service_reexported_identity() -> None:
    """deps.py 的 re-export 是同一函数对象（writing.py/单测命名空间契约）。"""
    import inkflow.api.deps as deps_module
    import inkflow.api.deps_agentic_writer as module

    assert deps_module.get_agentic_writer_service is module.get_agentic_writer_service, (
        "deps.py 必须 re-export deps_agentic_writer 的同一函数（非复制体）"
    )


def test_style_and_requirements_getters_are_wired() -> None:
    """#1231/#1232 装配缝：两个 getter 必须注入且可调用（func-coverage 门禁 + 防回退）。

    桩住凭据缝（keyless CI 下 resolve_llm_credentials 抛 422，镜像
    test_book_deps_assembly.py 先例），断言 service 持有两个非 None 回调。
    """
    import asyncio
    from unittest.mock import patch

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from inkflow.api.deps_agentic_writer import get_agentic_writer_service
    from inkflow.core.database import Base

    async def _setup():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False), engine

    factory, engine = asyncio.run(_setup())
    try:
        with patch(
            "inkflow.api._llm_resolver.resolve_llm_credentials",
            return_value=("deepseek/deepseek-chat", "test-key", "https://example.test/v1"),
        ):
            svc = get_agentic_writer_service(db=factory())
    finally:
        asyncio.run(engine.dispose())

    assert callable(svc._project_config_getter), (
        "project_config_getter 未装配（#1231 风格回退必须可用）"
    )
    assert callable(svc._chapter_requirements_getter), (
        "chapter_requirements_getter 未装配（#1232 列值必须可用）"
    )


async def test_wired_getters_delegate_to_real_services(monkeypatch) -> None:
    """#1231/#1232 装配缝执行：getter 委派 `deps_module` 服务的真实取值路径.

    覆盖 getter 函数体（func-coverage 门禁），并锁委派语义：
    - `_chapter_requirements_getter` → `get_chapter_service(db).get_chapter(cid)` → 列值
    - `_project_config_getter`      → `get_project_service(db).get(pid)` → `.config`
    异常路径：服务抛错 → 返回 None（降级不炸编排）。
    """
    from unittest.mock import AsyncMock, patch

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import inkflow.api.deps as deps_module
    from inkflow.api.deps_agentic_writer import get_agentic_writer_service
    from inkflow.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    chapter_svc = AsyncMock()
    chapter_svc.get_chapter.return_value = SimpleNamespace(writing_requirements="列值探针")
    project_svc = AsyncMock()
    project_svc.get.return_value = SimpleNamespace(config=SimpleNamespace(writing_style="风格探针"))

    monkeypatch.setattr(deps_module, "get_chapter_service", lambda db: chapter_svc)
    monkeypatch.setattr(deps_module, "get_project_service", lambda db: project_svc)

    session = factory()
    with patch(
        "inkflow.api._llm_resolver.resolve_llm_credentials",
        return_value=("deepseek/deepseek-chat", "test-key", "https://example.test/v1"),
    ):
        svc = get_agentic_writer_service(db=session)

    assert await svc._chapter_requirements_getter(uuid.UUID(int=55502)) == "列值探针"
    config = await svc._project_config_getter(uuid.UUID(int=55501))
    assert config is not None and config.writing_style == "风格探针"

    # 降级：服务抛错 → None（不炸编排）
    chapter_svc.get_chapter.side_effect = RuntimeError("列不可达")
    project_svc.get.side_effect = RuntimeError("项目不可达")
    assert await svc._chapter_requirements_getter(uuid.UUID(int=55502)) is None
    assert await svc._project_config_getter(uuid.UUID(int=55501)) is None

    # 空列 / 项目不存在 → None（回退语义）
    chapter_svc.get_chapter.side_effect = None
    chapter_svc.get_chapter.return_value = None
    project_svc.get.side_effect = None
    project_svc.get.return_value = None
    assert await svc._chapter_requirements_getter(uuid.UUID(int=55502)) is None
    assert await svc._project_config_getter(uuid.UUID(int=55501)) is None

    await session.close()
    await engine.dispose()
