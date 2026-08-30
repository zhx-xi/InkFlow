"""#659 检索索引重建异步端点 — HTTP 层契约测试（router index.py）.

形态镜像 tests/unit/api/routers/test_chat_conversation_patch.py：
独立 FastAPI app + include_router；服务经
`patch("inkflow.api.routers.index._get_svc", return_value=svc)` 注入
（_get_svc 为 async 工厂，await MagicMock() 直接解析为 svc）。
本 router 无 `Depends(get_db)`，无需 override。

契约锁定（tests/api/test_index_rebuild_api.py 语义）：
- POST /api/v1/index/rebuild → 202 {task_id, status: 'running'}；
  body.project_ids 缺省/null → svc 收 None；[] → 收 []（源码 _resolve_project_ids
  原样透传）；scope 缺省 → 'both'；
- 错误映射：scope 非法枚举 → 422（Pydantic list）；ValueError
  「未配置 embedding 模型」→ 422；「索引重建进行中」→ 409；
  ProjectNotFoundError → 404（消息即 detail）；project_ids 含非法 UUID
  → uuid.UUID ValueError 非特判 → 500「Internal server error」；其余未捕获
  异常 → FastAPI 默认 500 处理器「Internal server error」（router 不 catch
  泛 Exception，测试用 raise_server_exceptions=False 观察真实 HTTP 契约）；
- GET /api/v1/index/rebuild/status?task_id= → 200 进度 DTO；未注册 → 404
  「task not found」。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.routers.index import router
from inkflow.domain.ports.character_errors import ProjectNotFoundError

PROJECT_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


def _client() -> TestClient:
    """独立 app 挂载 index router（无 get_db 依赖，无需 override）。"""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _patch_request(svc: MagicMock, method: str, url: str, **kwargs):
    """patch _get_svc（async 工厂）返回 svc 后发请求——patch 在请求期间生效。"""
    with patch("inkflow.api.routers.index._get_svc", return_value=svc):
        return _client().request(method, url, **kwargs)


class TestRebuildEndpoint:
    """POST /api/v1/index/rebuild → 202."""

    def test_rebuild_returns_202_running(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(return_value={"task_id": "task-1", "status": "running"})
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/index/rebuild",
            json={"project_ids": [PROJECT_ID], "scope": "fulltext"},
        )

        assert resp.status_code == 202
        assert resp.json() == {"task_id": "task-1", "status": "running"}
        svc.start_rebuild.assert_awaited_once_with(
            project_ids=[uuid.UUID(PROJECT_ID)],
            scope="fulltext",
        )

    def test_rebuild_default_scope_and_null_project_ids(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(return_value={"task_id": "task-2", "status": "running"})
        resp = _patch_request(svc, "POST", "/api/v1/index/rebuild", json={})

        assert resp.status_code == 202
        assert resp.json()["status"] == "running"
        svc.start_rebuild.assert_awaited_once_with(project_ids=None, scope="both")

    def test_rebuild_empty_project_ids_passes_through(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(return_value={"task_id": "task-3", "status": "running"})
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/index/rebuild",
            json={"project_ids": []},
        )

        assert resp.status_code == 202
        svc.start_rebuild.assert_awaited_once_with(project_ids=[], scope="both")

    def test_rebuild_invalid_scope_returns_422(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(return_value={"task_id": "task-4", "status": "running"})
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/index/rebuild",
            json={"scope": "bad"},
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert any("Input should be" in m["msg"] for m in detail)
        svc.start_rebuild.assert_not_awaited()

    def test_rebuild_no_embedding_returns_422(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(side_effect=ValueError("未配置 embedding 模型"))
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/index/rebuild",
            json={"scope": "vector"},
        )

        assert resp.status_code == 422
        assert resp.json()["detail"] == "未配置 embedding 模型"

    def test_rebuild_already_running_returns_409(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(side_effect=ValueError("索引重建进行中"))
        resp = _patch_request(svc, "POST", "/api/v1/index/rebuild", json={})

        assert resp.status_code == 409
        assert resp.json()["detail"] == "索引重建进行中"

    def test_rebuild_project_not_found_returns_404(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(side_effect=ProjectNotFoundError("项目不存在"))
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/index/rebuild",
            json={"project_ids": [PROJECT_ID]},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"

    def test_rebuild_invalid_project_id_uuid_returns_500(self) -> None:
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(return_value={"task_id": "task-5", "status": "running"})
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/index/rebuild",
            json={"project_ids": ["not-a-uuid"]},
        )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"
        svc.start_rebuild.assert_not_awaited()

    def test_rebuild_unknown_error_returns_500(self) -> None:
        """未捕获异常 → FastAPI 默认 500 处理器（detail 不泄漏内部消息）。

        router 只 catch ProjectNotFoundError/ValueError，RuntimeError 上抛；
        Starlette ServerErrorMiddleware 兜底 → 500 纯文本 "Internal Server
        Error"（非 JSON detail）；TestClient 默认 raise_server_exceptions=True
        会重抛，故本测试用 raise_server_exceptions=False 观察真实 HTTP 契约。
        """
        svc = MagicMock()
        svc.start_rebuild = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("inkflow.api.routers.index._get_svc", return_value=svc):
            app = FastAPI()
            app.include_router(router)
            resp = TestClient(app, raise_server_exceptions=False).post(
                "/api/v1/index/rebuild",
                json={},
            )

        assert resp.status_code == 500
        assert "Internal Server Error" in resp.text


class TestStatusEndpoint:
    """GET /api/v1/index/rebuild/status."""

    def test_status_returns_progress_dto(self) -> None:
        svc = MagicMock()
        svc.get_status = AsyncMock(
            return_value={
                "task_id": "task-1",
                "status": "running",
                "progress": 0.5,
            }
        )
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/index/rebuild/status",
            params={"task_id": "task-1"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "task-1"
        assert body["status"] == "running"
        assert body["progress"] == 0.5
        svc.get_status.assert_awaited_once_with("task-1")

    def test_status_unknown_task_returns_404(self) -> None:
        svc = MagicMock()
        svc.get_status = AsyncMock(return_value=None)
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/index/rebuild/status",
            params={"task_id": "unknown"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "task not found"
