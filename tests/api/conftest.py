"""API 集成测试 fixture — FastAPI app dependency override.

将 get_db 替换为测试 db_session，确保测试与 API 共享同一内存数据库。
"""

import pytest


@pytest.fixture
def override_get_db(db_session):
    """将 FastAPI 的 get_db 替换为测试的 db_session，实现同库访问。"""
    from inkflow.api.deps import get_db

    async def _get_db_override():
        yield db_session

    from inkflow.api.app import app

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()
