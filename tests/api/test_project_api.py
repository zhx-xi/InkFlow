"""
InkFlow 项目 CRUD API 集成测试 — TDD RED 阶段。

使用 FastAPI TestClient + unittest.mock.patch 模拟路由层的
get_project_service 依赖，验证 API 端点行为。

预期：全部测试因路由模块 (inkflow.api.routers.project) 不存在而 FAIL。
这是 TDD RED 阶段的正常行为 — 路由和端点尚待实现。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.project import Project, ProjectConfig

pytestmark = pytest.mark.asyncio  # 模块内所有 async test 自动获得 asyncio mark

# ── Fixtures ──


@pytest.fixture
def client():
    """FastAPI TestClient 实例。"""
    return TestClient(app)


@pytest.fixture
def mock_project():
    """返回一个完整的 Project 实例，用于模拟 service 返回值。"""
    now = datetime.now(UTC)
    return Project(
        id=uuid.uuid4(),
        name="测试项目",
        genre="玄幻",
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(),
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )


# ── POST /api/v1/projects ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_create_project(mock_get_service, client, mock_project):
    """POST /api/v1/projects — 正常创建返回 201 + 项目 JSON。"""
    mock_service = AsyncMock()
    mock_service.create_project = AsyncMock(return_value=mock_project)
    mock_get_service.return_value = mock_service

    resp = client.post("/api/v1/projects", json={"name": "测试项目", "genre": "玄幻"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "测试项目"
    assert "id" in data


@patch("inkflow.api.routers.project.get_project_service")
async def test_create_project_empty_name(mock_get_service, client):
    """POST /api/v1/projects — 空名称返回 422 (Pydantic 验证失败)。"""
    mock_service = AsyncMock()
    mock_get_service.return_value = mock_service

    resp = client.post("/api/v1/projects", json={"name": "", "genre": "玄幻"})
    assert resp.status_code == 422


# ── GET /api/v1/projects ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_list_projects(mock_get_service, client, mock_project):
    """GET /api/v1/projects — 返回项目列表 200 + items/total。"""
    mock_service = AsyncMock()
    mock_service.list_projects = AsyncMock(return_value=([mock_project], 1))
    mock_get_service.return_value = mock_service

    resp = client.get("/api/v1/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["items"][0]["name"] == "测试项目"


# ── GET /api/v1/projects/{id} ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_get_project(mock_get_service, client, mock_project):
    """GET /api/v1/projects/{id} — 获取单个项目返回 200。"""
    mock_service = AsyncMock()
    mock_service.get = AsyncMock(return_value=mock_project)
    mock_get_service.return_value = mock_service

    resp = client.get(f"/api/v1/projects/{mock_project.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "测试项目"
    assert data["id"] == str(mock_project.id)


@patch("inkflow.api.routers.project.get_project_service")
async def test_get_project_not_found(mock_get_service, client):
    """GET /api/v1/projects/{id} — 不存在的项目返回 404（有效 UUID 但无记录）。"""
    mock_service = AsyncMock()
    mock_service.get = AsyncMock(return_value=None)
    mock_get_service.return_value = mock_service

    nonexistent_id = uuid.uuid4()
    resp = client.get(f"/api/v1/projects/{nonexistent_id}")
    assert resp.status_code == 404
    mock_service.get.assert_awaited_once()


# ── PATCH /api/v1/projects/{id} ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_update_project(mock_get_service, client, mock_project):
    """PATCH /api/v1/projects/{id} — 更新项目名称返回 200 + 更新后的数据。"""
    updated_project = mock_project.model_copy(update={"name": "更新后的名称"})
    mock_service = AsyncMock()
    mock_service.update = AsyncMock(return_value=updated_project)
    mock_get_service.return_value = mock_service

    resp = client.patch(
        f"/api/v1/projects/{mock_project.id}",
        json={"name": "更新后的名称"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "更新后的名称"


@patch("inkflow.api.routers.project.get_project_service")
async def test_update_project_config_default_words(
    mock_get_service, client, mock_project
):
    """PATCH /api/v1/projects/{id} — config.default_words 落库回读契约（🔴-4 方案 A）.

    评审 finding：前端 PATCH config.default_words 被后端静默丢弃（ProjectConfig 无此
    字段，Pydantic extra='ignore'），「默认字数刷新不丢」在真实内核下不可能。
    契约：PATCH config.default_words → 200 响应携带该字段 + GET 回读原样返回。
    """
    updated_project = mock_project.model_copy(
        update={"config": ProjectConfig(default_words=12345)}
    )
    mock_service = AsyncMock()
    mock_service.update = AsyncMock(return_value=updated_project)
    mock_service.get = AsyncMock(return_value=updated_project)
    mock_get_service.return_value = mock_service

    resp = client.patch(
        f"/api/v1/projects/{mock_project.id}",
        json={"config": {"default_words": 12345}},
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["default_words"] == 12345

    # 回读验证：字段真实落库（持久化到 service 返回的 Project），而非仅存在于 PATCH 响应
    readback = client.get(f"/api/v1/projects/{mock_project.id}")
    assert readback.status_code == 200
    assert readback.json()["config"]["default_words"] == 12345


# ── DELETE /api/v1/projects/{id} ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_delete_project(mock_get_service, client, mock_project):
    """DELETE /api/v1/projects/{id} — 软删除返回 204 No Content。"""
    mock_service = AsyncMock()
    mock_service.soft_delete = AsyncMock(return_value=True)
    mock_get_service.return_value = mock_service

    resp = client.delete(f"/api/v1/projects/{mock_project.id}")
    assert resp.status_code == 204


# ── POST /api/v1/projects/{id}/restore ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_restore_project(mock_get_service, client, mock_project):
    """POST /api/v1/projects/{id}/restore — 恢复软删除项目返回 200 + Project JSON。"""
    restored = mock_project.model_copy(update={"is_deleted": False})
    mock_service = AsyncMock()
    mock_service.restore = AsyncMock(return_value=restored)
    mock_get_service.return_value = mock_service

    resp = client.post(f"/api/v1/projects/{mock_project.id}/restore")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "测试项目"
    assert "id" in data


# ── DELETE /api/v1/projects/{id}?force=true (硬删除) ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_hard_delete_project(mock_get_service, client, mock_project):
    """DELETE /api/v1/projects/{id}?force=true — 硬删除返回 204。"""
    mock_service = AsyncMock()
    mock_service.hard_delete = AsyncMock(return_value=True)
    mock_get_service.return_value = mock_service

    resp = client.delete(f"/api/v1/projects/{mock_project.id}?force=true")
    assert resp.status_code == 204
    mock_service.hard_delete.assert_awaited_once()


# ── 404 路径测试 ──


@patch("inkflow.api.routers.project.get_project_service")
async def test_update_project_not_found(mock_get_service, client):
    """PATCH /api/v1/projects/{id} — 不存在的项目返回 404。"""
    mock_service = AsyncMock()
    mock_service.update = AsyncMock(return_value=None)
    mock_get_service.return_value = mock_service

    pid = uuid.uuid4()
    resp = client.patch(f"/api/v1/projects/{pid}", json={"name": "新名称"})
    assert resp.status_code == 404


@patch("inkflow.api.routers.project.get_project_service")
async def test_delete_project_not_found(mock_get_service, client):
    """DELETE /api/v1/projects/{id} — 不存在的项目返回 404。"""
    mock_service = AsyncMock()
    mock_service.soft_delete = AsyncMock(return_value=False)
    mock_get_service.return_value = mock_service

    pid = uuid.uuid4()
    resp = client.delete(f"/api/v1/projects/{pid}")
    assert resp.status_code == 404


@patch("inkflow.api.routers.project.get_project_service")
async def test_restore_project_not_found(mock_get_service, client):
    """POST /api/v1/projects/{id}/restore — 不存在的项目返回 404。"""
    mock_service = AsyncMock()
    mock_service.restore = AsyncMock(return_value=None)
    mock_get_service.return_value = mock_service

    pid = uuid.uuid4()
    resp = client.post(f"/api/v1/projects/{pid}/restore")
    assert resp.status_code == 404


# ── 非法 UUID 格式 ──


async def test_invalid_uuid_returns_404(client):
    """所有含 {project_id} 路径参数的端点 — 非法 UUID 返回 404。"""
    for method, path, body in [
        ("GET", "/api/v1/projects/not-a-uuid", None),
        ("PATCH", "/api/v1/projects/not-a-uuid", {"name": "test"}),
        ("DELETE", "/api/v1/projects/not-a-uuid", None),
        ("POST", "/api/v1/projects/not-a-uuid/restore", None),
    ]:
        resp = client.request(method, path, json=body)
        assert (
            resp.status_code == 404
        ), f"{method} {path} should return 404, got {resp.status_code}"
