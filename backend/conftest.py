"""backend 测试根 conftest —— 提供 test_engine（F47 #379 RED 契约：unit 层 DB fixture）。

顶层 tests/conftest.py 的 test_engine 属集成测试 conftest 链（repo_root/tests/），
backend/tests/unit/ 的 conftest 链不加载它；test_agent_trace.py 的 ExecutionStore
用例需要真实 in-memory SQLite，故在此镜像同一 fixture（不修改任何既有测试文件）。

# #735 D1: config.llm_default_model 全局默认已改空（移除内置 deepseek 硬编码）。
# 后台单元/集成测试的历史用例依赖「未指定 model 时回退到 deepseek 默认」的契约，
# 此处统一经环境变量 INKFLOW_LLM_DEFAULT_MODEL（env_prefix INKFLOW_ + 字段名
# llm_default_model）注入该值（「mock config 回退」），使既有用例在新空默认下保持
# 原语义；D1 的空默认契约由 test_model_resolution.py 用 InkFlowConfig.model_fields
# （class 默认，免疫 env）单独断言。
"""

from __future__ import annotations

import os

os.environ.setdefault("INKFLOW_LLM_DEFAULT_MODEL", "deepseek/deepseek-v4-flash")

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
