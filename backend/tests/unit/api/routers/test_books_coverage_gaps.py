"""Coverage backfill: books.py ``POST /runs`` 的 403「未授权」错误映射。

F44 spec §3.2 错误表 + 源码 books.py start_run：ValueError detail 含「未授权」
→ HTTPException(403)。现有契约测试覆盖 404/409/422，缺 403 分支。
通过 TestClient + dependency_overrides(get_book_service) 驱动公开端点。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.books import get_book_service

client = TestClient(app)


def test_start_run_unauthorized_maps_to_403() -> None:
    """prepare_run 抛 ValueError("未授权…") → 403，detail 原样透传。"""
    svc = AsyncMock()
    svc.prepare_run = AsyncMock(side_effect=ValueError("未授权：写作计划不属于当前项目"))
    app.dependency_overrides[get_book_service] = lambda: svc
    try:
        response = client.post(
            "/api/v1/agent/books/runs",
            json={
                "writing_plan_id": str(uuid.uuid4()),
                "mode": "static",
            },
        )
    finally:
        app.dependency_overrides.pop(get_book_service, None)

    assert response.status_code == 403
    assert "未授权" in response.json()["detail"]
