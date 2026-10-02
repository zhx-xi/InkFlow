"""#1333 段 2 —— 重复启动同计划 → 409（N25）。

``POST /api/v1/agent/books/runs`` 对「同一计划重复启动」必须显式拒绝（409），
前端只透错、不静默新建 run（§3.5-7 拍板）。

现状：``prepare_run`` 抛的 ``ValueError("运行已在进行中")`` 落到端点通用
``except ValueError`` → 422（语义是「参数非法」，与「资源冲突」不符）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.books import get_book_service
from inkflow.domain.services.book_service import RunAlreadyActiveError

client = TestClient(app)
_PLAN_ID = "01920000-0000-7000-8000-000000001333"


def test_duplicate_start_maps_to_409() -> None:
    """服务层 RunAlreadyActiveError → 409（前端只透错，不新建 run）。"""
    svc = AsyncMock()
    svc.prepare_run = AsyncMock(side_effect=RunAlreadyActiveError("运行已在进行中"))
    app.dependency_overrides[get_book_service] = lambda: svc
    try:
        response = client.post(
            "/api/v1/agent/books/runs", json={"writing_plan_id": _PLAN_ID, "mode": "static"}
        )
    finally:
        app.dependency_overrides.pop(get_book_service, None)

    assert response.status_code == 409
    assert response.json()["detail"] == "运行已在进行中"


def test_other_value_error_still_maps_to_422() -> None:
    """反例守护：非冲突类 ValueError 仍 422（不得被 409 分支吞掉）。"""
    svc = AsyncMock()
    svc.prepare_run = AsyncMock(side_effect=ValueError("上限配置非法"))
    app.dependency_overrides[get_book_service] = lambda: svc
    try:
        response = client.post(
            "/api/v1/agent/books/runs", json={"writing_plan_id": str(uuid.uuid4())}
        )
    finally:
        app.dependency_overrides.pop(get_book_service, None)

    assert response.status_code == 422
