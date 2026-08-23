"""InkFlow 集成测试共享 fixture — 异步数据库 + 项目样本。

供 tests/integration/, tests/api/, tests/cli/ 使用。
"""

import asyncio
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.project import ProjectCreate
from inkflow.infrastructure.database.models.project import ProjectORM

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_engine():
    """function-scoped in-memory SQLite engine with tables created per test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """function-scoped async session bound to test_engine."""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest.fixture
def sample_project_data() -> ProjectCreate:
    """返回 ProjectCreate 实例，用于创建项目测试。"""
    return ProjectCreate(
        name="测试小说",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
    )


@pytest_asyncio.fixture
async def sample_project(db_session) -> ProjectORM:
    """创建并持久化一个 ProjectORM 实例（用于需要真实数据库记录的测试）。"""
    from inkflow.infrastructure.database.models.project import ProjectORM

    project = ProjectORM(
        name="测试小说",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
def sample_project_data2() -> ProjectCreate:
    """第二个项目数据，用于列表测试。"""
    return ProjectCreate(
        name="科幻新作",
        tags=["科幻"],
        language="zh-CN",
        target_words=80000,
    )


@pytest.fixture
def temp_keys_dir():
    """临时密钥存储目录，测试后自动清理。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
