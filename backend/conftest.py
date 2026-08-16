"""backend 测试根 conftest —— 提供 test_engine（F47 #379 RED 契约：unit 层 DB fixture）。

顶层 tests/conftest.py 的 test_engine 属集成测试 conftest 链（repo_root/tests/），
backend/tests/unit/ 的 conftest 链不加载它；test_agent_trace.py 的 ExecutionStore
用例需要真实 in-memory SQLite，故在此镜像同一 fixture（不修改任何既有测试文件）。
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from inkflow.core.database import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_engine():
    """function-scoped in-memory SQLite engine with tables created per test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
