"""#486 会话 UI：GET /api/v1/agent/books/planner 列表端点契约（router 层）。

访谈会话（#475 PlannerSession）需在会话页展示列表——books.py 新增列表端点
（同文件 POST /planner 启动 + GET /planner/{session_id} 详情已存在）。

══════════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准）:
- 端点: GET /api/v1/agent/books/planner
  查询参数: project_id（UUID 可空）/ status（str 可空）/ offset（默认 0）/ limit（默认 50）
- 实现: svc = Depends(get_planner_service)；调用 svc.list(project_id=, status=,
  offset=, limit=)；project_id 字符串 → uuid.UUID 解析（非法 → HTTPException 422
  或 404 均可，测试不锁）；返回 {"items": [PlannerSession.model_dump(mode="json")...],
  "total": N, "offset": O, "limit": L}。
- 路由注册顺序: GET /planner 与既有 GET /planner/{session_id} 是不同路径段数，
  无冲突（无需前置注册特殊处理）。
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.books import get_planner_service
from inkflow.domain.models.planner_session import PlannerSession

client = TestClient(app)


def _dt(day: int) -> datetime:
    """构造 2026-01-day 的 UTC 时间（测试固定时间戳）。"""
    return datetime(2026, 1, day, tzinfo=UTC)


def _session(**kw: object) -> PlannerSession:
    """构造 PlannerSession 领域对象（键值覆盖默认值）。"""
    return PlannerSession(
        id=kw.pop("id", uuid.uuid4()),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        project_id=kw.pop("project_id", uuid.uuid4()),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        status=kw.pop("status", "drafting"),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        one_liner=kw.pop("one_liner", "测试一句话"),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        round=kw.pop("round", 2),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        asked_questions=kw.pop("asked_questions", []),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        answers=kw.pop("answers", {}),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        authorized=kw.pop("authorized", []),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        confirmed_items=kw.pop("confirmed_items", []),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        conflicts=kw.pop("conflicts", []),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        confirming=kw.pop("confirming", False),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        writing_plan_id=kw.pop("writing_plan_id", None),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        created_at=kw.pop("created_at", _dt(1)),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
        updated_at=kw.pop("updated_at", _dt(1)),  # type: ignore[misc]  # 测试 helper：kw.pop 键值覆盖返回 object
    )


@pytest.fixture
def fake_svc():
    """Override get_planner_service → mock svc（list 默认返回 1 条）。"""
    svc = AsyncMock()
    svc.list = AsyncMock(return_value=([_session()], 1))
    app.dependency_overrides[get_planner_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_planner_service, None)


class TestPlannerListAPI:
    """GET /api/v1/agent/books/planner 列表端点。"""

    def test_list_planner_sessions_success(self, fake_svc) -> None:
        """200 + {items, total, offset, limit}；items 元素含 one_liner/status。"""
        response = client.get("/api/v1/agent/books/planner")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert data["items"][0]["one_liner"] == "测试一句话"
        assert data["items"][0]["status"] == "drafting"
        fake_svc.list.assert_awaited_once_with(project_id=None, status=None, offset=0, limit=50)

    def test_list_planner_sessions_filters(self, fake_svc) -> None:
        """project_id/status/offset/limit 查询参数透传。"""
        pid = uuid.uuid4()
        response = client.get(
            "/api/v1/agent/books/planner",
            params={
                "project_id": str(pid),
                "status": "completed",
                "offset": 10,
                "limit": 20,
            },
        )
        assert response.status_code == 200
        fake_svc.list.assert_awaited_once_with(
            project_id=pid, status="completed", offset=10, limit=20
        )
