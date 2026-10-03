"""#1463 访谈确认链路领域异常 → HTTP 映射契约（router 层，TDD RED 阶段）。

════════════════════════════════════════════════════════════════════
背景
  访谈完成路径（`_complete`）建总纲撞项目内唯一约束时抛
  `OutlineNameConflictError`（`domain/ports/outline_errors.py`：`OutlineServiceError`
  子类，spec 约定 API 层映射 **422，消息即 detail**）。
  但 `POST /api/v1/agent/books/planner/{session_id}/respond` 只捕获 `ValueError`
  → 该领域异常冒泡为 **500「内部错误（无详情）」**（#1463 现象）。

修复方向（issue #1463 §修复方向 2）
  领域业务冲突（OutlineServiceError 家族）→ 4xx + 可读 detail。
  既有先例：`api/routers/extractions.py:104-105` 同样映射 422。

════════════════════════════════════════════════════════════════════
用例分组与预期（RED 阶段；实现者不得改本文件）

【新增契约】当前必须 FAIL：
  R-1 test_outline_name_conflict_maps_to_422_with_detail
      （当前未捕获 → TestClient 直接抛 OutlineNameConflictError）
  R-1b test_outline_hierarchy_error_maps_to_422
  R-1c test_character_name_conflict_maps_to_422
      （`_complete` 的另一半：主角同名冲突，CharacterServiceError 家族同样应 422）

【反例守护】当前即 PASS，修复后必须保持 PASS：
  R-2 test_value_error_not_found_still_404
  R-3 test_value_error_non_confirming_still_422

若某条实际状态与预期不符，**如实报告，不要改断言凑数**。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.books import get_planner_service
from inkflow.domain.ports.character_errors import CharacterNameConflictError
from inkflow.domain.ports.outline_errors import (
    OutlineHierarchyError,
    OutlineNameConflictError,
)

BASE = "/api/v1/agent/books"
client = TestClient(app)


@pytest.fixture
def planner_svc():
    """依赖 override：AsyncMock 版 PlannerService（异常由各用例注入）。"""
    svc = AsyncMock()
    app.dependency_overrides[get_planner_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_planner_service, None)


def test_outline_name_conflict_maps_to_422_with_detail(planner_svc) -> None:
    """【新增契约 R-1】OutlineNameConflictError → 422 + 可读 detail（非 500 无详情）。"""
    planner_svc.respond = AsyncMock(side_effect=OutlineNameConflictError())

    resp = client.post(f"{BASE}/planner/{uuid.uuid4()}/respond", json={"confirm": True})

    assert resp.status_code == 422
    assert "同名大纲已存在" in resp.json()["detail"]


def test_outline_hierarchy_error_maps_to_422(planner_svc) -> None:
    """【新增契约 R-1b】同族领域异常（OutlineHierarchyError）同样映射 422。"""
    planner_svc.respond = AsyncMock(side_effect=OutlineHierarchyError())

    resp = client.post(f"{BASE}/planner/{uuid.uuid4()}/respond", json={"confirm": True})

    assert resp.status_code == 422
    assert "层级约束违反" in resp.json()["detail"]


def test_character_name_conflict_maps_to_422(planner_svc) -> None:
    """【新增契约 R-1c】`_complete` 的第二个确定性 create（主角）冲突同样映射 422。

    `CharacterNameConflictError` 是 F9 的 `CharacterServiceError` 子类（spec §3.5 同为 422）。
    """
    planner_svc.respond = AsyncMock(side_effect=CharacterNameConflictError())

    resp = client.post(f"{BASE}/planner/{uuid.uuid4()}/respond", json={"confirm": True})

    assert resp.status_code == 422
    assert "同名角色已存在" in resp.json()["detail"]


def test_value_error_not_found_still_404(planner_svc) -> None:
    """【反例守护 R-2】既有 ValueError「不存在」语义 → 404 不变。"""
    planner_svc.respond = AsyncMock(side_effect=ValueError("会话不存在"))

    resp = client.post(f"{BASE}/planner/{uuid.uuid4()}/respond", json={})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "会话不存在"


def test_value_error_non_confirming_still_422(planner_svc) -> None:
    """【反例守护 R-3】既有 ValueError（非确认阶段）→ 422 不变。"""
    planner_svc.respond = AsyncMock(side_effect=ValueError("非确认阶段，请先完成必答项"))

    resp = client.post(f"{BASE}/planner/{uuid.uuid4()}/respond", json={"confirm": True})

    assert resp.status_code == 422
    assert "非确认阶段" in resp.json()["detail"]
