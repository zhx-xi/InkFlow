"""#1466 成书页水合：GET /api/v1/agent/books/plans 列表端点契约（router 层）。

缺陷背景（issue #1466 实测）：`GET /api/v1/agent/books/runs?project_id=<uuid>`
→ **405 Method Not Allowed**；books.py 只有单条 `GET /runs/{run_id}`，
writing_plan 同样无列表端点 → GUI 成书页对既有 plan/run 永远不可见。

════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准）
════════════════════════════════════════════════════════════════════
- 端点: GET /api/v1/agent/books/plans
  查询参数: project_id（UUID 可空）/ offset（默认 0, ge=0）/ limit（默认 50, ge=1, le=200）
- 依赖: svc = Depends(get_book_service)；调用
  `svc.list_plans(project_id=..., offset=..., limit=...)`
- 响应信封（镜像既有 GET /planner 列表）：{items, total, offset, limit}；
  items 元素 = WritingPlan.model_dump(mode="json")（plan 自带 status/progress
  = run 状态摘要——run 载体 = WritingPlan.id，plan 与 run 一一对应）
- 只读、无副作用 → GET 语义；空项目 → 200 + items=[]（**非 404**）
- 非法 project_id（非 UUID）→ 422（查询参数类型校验，非 500）
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.books import get_book_service
from inkflow.domain.models.writing_plan import WritingPlan

client = TestClient(app)

PLANS_PATH = "/api/v1/agent/books/plans"


def _plan(**overrides: object) -> WritingPlan:
    """构造 WritingPlan 领域对象（键值覆盖默认值）。"""
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": uuid.UUID(int=1),
        "title": "既有写作计划",
        "status": "running",
        "root_outline_id": None,
        "character_ids": [],
        "limits": {"max_chapters": 3, "max_agent_calls": 6},
        "progress": {"o-c1": "done"},
        "execution_refs": {},
        "thread_id": None,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 2, tzinfo=UTC),
    }
    base.update(overrides)
    return WritingPlan(**base)  # type: ignore[arg-type]  # 测试 helper：overrides 逐键覆盖返回 object


@pytest.fixture
def fake_svc():
    """Override get_book_service → mock svc（list_plans 默认返回 1 条）。"""
    plan = _plan()
    svc = AsyncMock()
    svc.list_plans = AsyncMock(return_value=([plan], 1))
    app.dependency_overrides[get_book_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_book_service, None)


class TestBookPlansListAPI:
    """GET /api/v1/agent/books/plans 列表端点（#1466）。"""

    def test_list_plans_success(self, fake_svc) -> None:
        """200 + {items, total, offset, limit}；items 元素含 id/status/progress（run 摘要）。"""
        pid = uuid.UUID(int=1)
        response = client.get(PLANS_PATH, params={"project_id": str(pid)})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert data["items"][0]["title"] == "既有写作计划"
        assert data["items"][0]["status"] == "running"
        assert data["items"][0]["progress"] == {"o-c1": "done"}
        fake_svc.list_plans.assert_awaited_once_with(project_id=pid, offset=0, limit=50)

    def test_list_plans_empty_project_returns_200_empty(self, fake_svc) -> None:
        """空项目 → 200 + items=[]（**非 404**——成书页据此回落起点表单）。"""
        fake_svc.list_plans = AsyncMock(return_value=([], 0))
        response = client.get(PLANS_PATH, params={"project_id": str(uuid.UUID(int=7))})
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 50}

    def test_list_plans_pagination_passthrough(self, fake_svc) -> None:
        """offset/limit 查询参数透传服务层。"""
        pid = uuid.UUID(int=2)
        response = client.get(
            PLANS_PATH, params={"project_id": str(pid), "offset": 10, "limit": 20}
        )
        assert response.status_code == 200
        fake_svc.list_plans.assert_awaited_once_with(project_id=pid, offset=10, limit=20)

    def test_list_plans_without_project_id(self, fake_svc) -> None:
        """project_id 可省略（None 透传 = 全量列表语义，镜像 GET /planner 列表）。"""
        response = client.get(PLANS_PATH)
        assert response.status_code == 200
        fake_svc.list_plans.assert_awaited_once_with(project_id=None, offset=0, limit=50)

    def test_list_plans_invalid_project_id_422(self, fake_svc) -> None:
        """非法 project_id → 422（查询参数 UUID 校验；不是 500，也不是 405）。"""
        response = client.get(PLANS_PATH, params={"project_id": "not-a-uuid"})
        assert response.status_code == 422
        fake_svc.list_plans.assert_not_awaited()

    def test_list_plans_is_get_not_405(self) -> None:
        """路由方法面回归守护：GET /plans 必须存在（#1466 原报错为 405）。"""
        paths = app.openapi()["paths"]
        assert PLANS_PATH in paths
        assert "get" in paths[PLANS_PATH]
