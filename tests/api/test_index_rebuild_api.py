"""
#659 索引重建异步端点 RED 契约（后端 #657 P2 配套：POST /index/rebuild + GET /index/rebuild/status）

⚠️ 本文件 = 契约。GREEN 新建 src/api/routers/index.py（模块级工厂 `_get_svc` 镜像
search.py 模式），必须匹配：

端点:
- POST /api/v1/index/rebuild — body { project_ids: list[str] | null,
  scope: 'fulltext'|'vector'|'both' }
  → 202 { task_id: str, status: 'running' }
  - scope 缺省 → 'both'；project_ids 缺省/null → 全部（service 层逐项目校验）
  - 预校验失败（#659 决策）:
    422: scope 非法枚举 / body 校验失败（Pydantic）
    409: 同 project 范围重建进行中（防重复后台任务）
    422: scope=vector/both 且未配 embedding 模型（force precheck，防启动后必然失败）
    404: 任一 project_id 不存在（ProjectNotFoundError → 404）
- GET /api/v1/index/rebuild/status?task_id=<id>
  → 200 { status: 'running'|'done'|'failed', step: 'fulltext'|'vector',
         progress_done: int, progress_total: int, rebuilt_at: str|null, error: str|null }
  - task_id 未注册 → 404 { detail: 'task not found' }

Mock 形态: patch `inkflow.api.routers.index._get_svc` 注入 mock IndexRebuildService
（AsyncMock）；service.start_rebuild / get_status 为 AsyncMock。镜像 test_search_api.py
`mock_svc` fixture 模式（TestClient + delenv token + real app）。

RED 预期: ./index 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.ports.character_errors import ProjectNotFoundError

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"

PROJECT_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
PROJECT_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    return TestClient(app)


@pytest.fixture
def mock_svc():
    svc = AsyncMock()
    svc.start_rebuild = AsyncMock()
    svc.get_status = AsyncMock()
    with patch("inkflow.api.routers.index._get_svc", return_value=svc):
        yield svc


def _rebuild_body(**overrides):
    body: dict = {"project_ids": [str(PROJECT_A)], "scope": "both"}
    body.update(overrides)
    return body


def _start_arg(svc):
    call = svc.start_rebuild.await_args
    assert call is not None, "service.start_rebuild 未被调用"
    return call.args[0] if call.args else call.kwargs["project_ids"]


# ── POST /api/v1/index/rebuild ──


def test_rebuild_202_running(client, mock_svc):
    """POST /index/rebuild → 202 {task_id, status: running}
    （scope=both 缺省 project_ids 单项目）。"""
    mock_svc.start_rebuild.return_value = {"task_id": "task-1", "status": "running"}
    resp = client.post("/api/v1/index/rebuild", json=_rebuild_body())
    assert resp.status_code == 202
    body = resp.json()
    assert body["task_id"] == "task-1"
    assert body["status"] == "running"


def test_rebuild_defaults_both_and_all_projects(client, mock_svc):
    """body {project_ids: null, scope 缺省} → start_rebuild(None, 'both')。"""
    mock_svc.start_rebuild.return_value = {"task_id": "task-2", "status": "running"}
    resp = client.post("/api/v1/index/rebuild", json={"project_ids": None})
    assert resp.status_code == 202
    arg = _start_arg(mock_svc)
    assert arg is None
    call = mock_svc.start_rebuild.await_args
    # scope 缺省 → 'both'（位置或关键字传参均兼容）
    scope = call.kwargs.get("scope") if call.kwargs else None
    assert scope is None or scope == "both" or call.args[1] == "both"


def test_rebuild_scope_vector_passthrough(client, mock_svc):
    """scope=vector → start_rebuild 收到 vector（缺省 project_ids 单项目透传）。"""
    mock_svc.start_rebuild.return_value = {"task_id": "task-3", "status": "running"}
    resp = client.post("/api/v1/index/rebuild", json=_rebuild_body(scope="vector"))
    assert resp.status_code == 202
    assert _start_arg(mock_svc) == [PROJECT_A]


def test_rebuild_scope_invalid_422(client, mock_svc):
    """scope='banana' → 422（Pydantic 枚举校验）。"""
    resp = client.post("/api/v1/index/rebuild", json=_rebuild_body(scope="banana"))
    assert resp.status_code == 422
    mock_svc.start_rebuild.assert_not_awaited()


def test_rebuild_project_not_found_404(client, mock_svc):
    """project 不存在 → 404（ProjectNotFoundError 消息即 detail）。"""
    mock_svc.start_rebuild.side_effect = ProjectNotFoundError(
        f"Project not found: {PROJECT_B}"
    )
    resp = client.post(
        "/api/v1/index/rebuild", json=_rebuild_body(project_ids=[str(PROJECT_B)])
    )
    assert resp.status_code == 404
    assert "Project not found" in resp.json()["detail"]


def test_rebuild_conflict_409(client, mock_svc):
    """相同范围重建进行中 → 409（防重复后台任务，F44 预校验先例）。"""
    mock_svc.start_rebuild.side_effect = ValueError("索引重建进行中")
    resp = client.post("/api/v1/index/rebuild", json=_rebuild_body())
    assert resp.status_code == 409


def test_rebuild_vector_no_embedding_422(client, mock_svc):
    """scope=vector/both 且未配 embedding → 422（前置校验）。"""
    mock_svc.start_rebuild.side_effect = ValueError("未配置 embedding 模型")
    resp = client.post("/api/v1/index/rebuild", json=_rebuild_body(scope="vector"))
    assert resp.status_code == 422


# ── GET /api/v1/index/rebuild/status ──


def test_status_running(client, mock_svc):
    """GET status?task_id → 200 running（含 step/进度）。"""
    mock_svc.get_status.return_value = {
        "status": "running",
        "step": "fulltext",
        "progress_done": 3,
        "progress_total": 7,
        "rebuilt_at": None,
        "error": None,
    }
    resp = client.get("/api/v1/index/rebuild/status", params={"task_id": "task-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["step"] == "fulltext"
    assert body["progress_done"] == 3
    assert body["progress_total"] == 7
    mock_svc.get_status.assert_awaited_once_with("task-1")


def test_status_done(client, mock_svc):
    """GET status → 200 done（含 rebuilt_at）。"""
    mock_svc.get_status.return_value = {
        "status": "done",
        "step": "vector",
        "progress_done": 7,
        "progress_total": 7,
        "rebuilt_at": "2026-08-25T12:30:00Z",
        "error": None,
    }
    resp = client.get("/api/v1/index/rebuild/status", params={"task_id": "task-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["rebuilt_at"] == "2026-08-25T12:30:00Z"


def test_status_failed(client, mock_svc):
    """GET status → 200 failed（含 error，全文已建/向量失败）。"""
    mock_svc.get_status.return_value = {
        "status": "failed",
        "step": "vector",
        "progress_done": 3,
        "progress_total": 7,
        "rebuilt_at": None,
        "error": "embedding 模型不可用",
    }
    resp = client.get("/api/v1/index/rebuild/status", params={"task_id": "task-1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    assert resp.json()["error"] == "embedding 模型不可用"


def test_status_not_found_404(client, mock_svc):
    """task_id 未注册 → 404。"""
    mock_svc.get_status.return_value = None
    resp = client.get("/api/v1/index/rebuild/status", params={"task_id": "nope"})
    assert resp.status_code == 404


# ── #682 单例化契约（跨请求 task 状态共享）──


@pytest.mark.asyncio
async def test_get_svc_returns_singleton():
    """#682: _get_svc() 每次返回同一进程级单例。

    修复前 deps.get_index_rebuild_service 每请求 new 实例 → is False；
    修复后工厂缓存单例 → is True。
    """
    from inkflow.api.routers import index as idx

    project_repo = AsyncMock()
    project_repo.get = AsyncMock(return_value=AsyncMock())
    with patch(
        "inkflow.api.deps.SQLiteProjectRepository", return_value=project_repo
    ), patch(
        "inkflow.api.deps.get_vector_store_optional", AsyncMock(return_value=None)
    ), patch("inkflow.api.deps.get_search_service", AsyncMock()), patch(
        "inkflow.api.deps.get_extraction_service", AsyncMock()
    ), patch(
        "inkflow.api.routers.index.async_session_factory", return_value=AsyncMock()
    ), patch("inkflow.api.deps._index_rebuild_service_instance", None, create=True):
        svc1 = await idx._get_svc()
        svc2 = await idx._get_svc()
    assert svc1 is svc2


@pytest.mark.asyncio
async def test_rebuild_then_status_not_404():
    """#682: POST 注册 task → GET status 不 404（同一单例共享 _tasks）。

    修复前 GET 落新实例 → _tasks 空 → 404；修复后单例 → 命中。
    """
    from inkflow.api.routers import index as idx
    from inkflow.domain.services import index_rebuild_service as irs

    project_repo = AsyncMock()
    project_repo.get = AsyncMock(return_value=AsyncMock())
    project_repo.list_all = AsyncMock(return_value=([], 0))
    with patch(
        "inkflow.api.deps.SQLiteProjectRepository", return_value=project_repo
    ), patch(
        "inkflow.api.deps.get_vector_store_optional", AsyncMock(return_value=None)
    ), patch("inkflow.api.deps.get_search_service", AsyncMock()), patch(
        "inkflow.api.deps.get_extraction_service", AsyncMock()
    ), patch(
        "inkflow.api.routers.index.async_session_factory", return_value=AsyncMock()
    ), patch.object(irs, "spawn_background_task", AsyncMock()), patch(
        "inkflow.api.deps._index_rebuild_service_instance", None, create=True
    ):
        svc1 = await idx._get_svc()
        task = await svc1.start_rebuild(project_ids=[PROJECT_A], scope="fulltext")
        svc2 = await idx._get_svc()
        status = await svc2.get_status(task["task_id"])
    assert status is not None
    assert status["status"] == "running"
