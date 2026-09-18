"""#1282 ``POST /api/v1/agent/books/runs/{run_id}/reset`` 端点契约（方案 B）。

issue #1282：book run 缺「不删正文重跑」出口。本端点清执行态 + plan 退回 ready，
不动正文（语义细节见 domain 层 test_book_reset_1282.py）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.books import get_book_service

client = TestClient(app)
_RUN_ID = "01920000-0000-7000-8000-000000000282"


def test_reset_run_returns_ready_status() -> None:
    """reset 端点 → 200 + {run_id, status: ready}（服务层契约原样透传）。"""
    svc = AsyncMock()
    svc.reset_run = AsyncMock(return_value={"run_id": _RUN_ID, "status": "ready"})
    app.dependency_overrides[get_book_service] = lambda: svc
    try:
        response = client.post(f"/api/v1/agent/books/runs/{_RUN_ID}/reset")
    finally:
        app.dependency_overrides.pop(get_book_service, None)

    assert response.status_code == 200
    assert response.json() == {"run_id": _RUN_ID, "status": "ready"}
    svc.reset_run.assert_awaited_once_with(_RUN_ID)


def test_reset_run_unknown_maps_to_404() -> None:
    """服务层 ValueError("运行不存在…") → 404（对齐 get_status/intervene 错误表）。"""
    svc = AsyncMock()
    svc.reset_run = AsyncMock(side_effect=ValueError("运行不存在"))
    app.dependency_overrides[get_book_service] = lambda: svc
    try:
        response = client.post(f"/api/v1/agent/books/runs/{uuid.uuid4()}/reset")
    finally:
        app.dependency_overrides.pop(get_book_service, None)

    assert response.status_code == 404
    assert response.json()["detail"] == "运行不存在"


def test_reset_run_while_running_maps_to_422() -> None:
    """执行中 reset → 422（非 404 类错误一律 422，对齐 intervene 分支）。"""
    svc = AsyncMock()
    svc.reset_run = AsyncMock(side_effect=ValueError("运行已在进行中，不可重置"))
    app.dependency_overrides[get_book_service] = lambda: svc
    try:
        response = client.post(f"/api/v1/agent/books/runs/{_RUN_ID}/reset")
    finally:
        app.dependency_overrides.pop(get_book_service, None)

    assert response.status_code == 422
    assert "进行中" in response.json()["detail"]
