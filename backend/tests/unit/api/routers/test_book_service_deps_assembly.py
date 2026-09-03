"""RED 契约（#466）：get_book_service 返回实例自身必须装配 writer_factory/draft_service。

缺陷背景（0.10.0-rc5 实证 2026-08-18）：#464 修复只给 BookVolumePipeline 装配了
writer_factory/draft_service，但 `_build_book_service` 构造 BookService 时**漏传**
这两个参数 → `_delegate_chapter`（static 顺序派发模式核心）检查 `self._writer_factory`
永远 None → `ValueError: writer_factory 未装配` → 章全 failed + run completed 静默。

本契约：调 books.get_book_service(db)（真实 deps 装配），断言**返回实例自身**的
_writer_factory 和 _draft_service 均非 None（static 路径可用）。修复后全部 PASS。

⚠️ RED 期形态：当前 BookService 自身 _writer_factory/_draft_service 均 None → FAIL。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from inkflow.api.routers import books
from inkflow.core.database import Base


def db_session():
    """模块级 in-memory SQLite 会话（普通函数——pytest 9 禁直接调 fixture，#466 修正）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(_setup())


def _get_book_service():
    """装配缝契约测试：凭据解析按 #860 同源契约经 resolve_llm_credentials 打桩注入。

    本文件锁的是「writer_factory/draft_service 装配完整」（#464/#466），与凭据值无关；
    #860 修复后 _build_book_service 复用 resolve_llm_credentials（keyless CI 下抛 422），
    故桩住该缝返回固定凭据（契约 fixture 适配，断言零改动，#821 先例）。
    """
    session_factory = db_session()
    with patch(
        "inkflow.api._llm_resolver.resolve_llm_credentials",
        return_value=("deepseek/deepseek-chat", "test-assembly-key", "https://example.test/v1"),
    ):
        return books.get_book_service(db=session_factory())


def test_book_service_own_writer_factory_injected():
    """BookService 自身 _writer_factory 必须非 None（static _delegate_chapter 可用）。"""
    svc = _get_book_service()
    assert svc._writer_factory is not None, "BookService._writer_factory 未装配（#466）"
    assert callable(svc._writer_factory), "writer_factory 必须可调用"


def test_book_service_own_draft_service_injected():
    """BookService 自身 _draft_service 必须非 None（static 草稿回收可用）。"""
    svc = _get_book_service()
    assert svc._draft_service is not None, "BookService._draft_service 未装配（#466）"


def test_book_service_static_delegate_path():
    """static 委托路径装配完整：writer_factory + draft_service 同时非 None。"""
    svc = _get_book_service()
    missing = [
        name for name in ("_writer_factory", "_draft_service") if getattr(svc, name, None) is None
    ]
    assert missing == [], f"BookService 装配缺口: {missing}"
