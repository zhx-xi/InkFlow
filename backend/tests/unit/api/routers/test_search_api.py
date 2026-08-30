"""F22 全文搜索 REST API — HTTP 层契约测试（router search.py）.

形态镜像 tests/unit/api/routers/test_chat_conversation_patch.py：
独立 FastAPI app + include_router + `dependency_overrides[get_db]`；
服务经 `patch("inkflow.api.routers.search._get_svc", return_value=svc)`
注入（_get_svc 为 async 工厂，await MagicMock() 直接解析为 svc）。

契约锁定（spec f22 §3.1-§3.3）：
- GET  /api/v1/search → SearchResponse（total/hits/query/mode/project_ids 回显）；
  项目参数二选一：project_id 单值 / project_ids 逗号分隔多值；
- 错误映射：ProjectNotFoundError → 404（消息即 detail）；project_id 与
  project_ids 都缺省 → 422「project_id or project_ids required」；非法
  UUID / types / mode → 422 Pydantic 风格 detail（list，loc 回显字段）；
  q 空白 → 422（SearchQuery validator）；其余异常 → 500「Internal server
  error」（内部消息不泄漏）；
- POST /api/v1/search/rebuild：全缺省 → svc.rebuild(None)（全部项目）；
  project_id 提供 → svc.rebuild([uuid.int])；404 映射同上。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.deps import get_db
from inkflow.api.routers.search import router
from inkflow.domain.models.search import (
    SearchEntityType,
    SearchHit,
    SearchMode,
    SearchQuery,
    SearchResponse,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError

PROJECT_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
PROJECT_ID_2 = "6ba7b811-9dad-11d1-80b4-00c04fd430c8"


def _client() -> TestClient:
    """独立 app 挂载 search router + get_db override（mock session）。"""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


def _patch_request(svc: MagicMock, method: str, url: str, **kwargs):
    """patch _get_svc（async 工厂）返回 svc 后发请求——patch 在请求期间生效。"""
    with patch("inkflow.api.routers.search._get_svc", return_value=svc):
        return _client().request(method, url, **kwargs)


def _response() -> SearchResponse:
    pid = uuid.UUID(PROJECT_ID)
    return SearchResponse(
        total=1,
        hits=[
            SearchHit(
                entity_type=SearchEntityType.CHAPTER,
                entity_id=uuid.UUID(PROJECT_ID_2),
                project_id=pid,
                title="第一章",
                snippet="林晚……",
                score=0.9,
            )
        ],
        query="林晚",
        types=None,
        mode=SearchMode.KEYWORD,
        project_ids=[pid],
    )


class TestSearchEndpoint:
    """GET /api/v1/search."""

    def test_search_returns_search_response(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_response())
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "林晚", "project_id": PROJECT_ID},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["query"] == "林晚"
        assert body["mode"] == "keyword"
        assert body["project_ids"] == [PROJECT_ID]
        assert body["hits"][0]["title"] == "第一章"
        assert body["hits"][0]["entity_type"] == "chapter"
        svc.search.assert_awaited_once_with(
            SearchQuery(
                q="林晚",
                project_ids=[uuid.UUID(PROJECT_ID)],
                types=None,
                mode=SearchMode.KEYWORD,
                limit=20,
                offset=0,
            )
        )

    def test_search_comma_separated_project_ids(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(
            return_value=SearchResponse(
                total=0,
                hits=[],
                query="x",
                types=None,
                mode=SearchMode.KEYWORD,
                project_ids=[uuid.UUID(PROJECT_ID), uuid.UUID(PROJECT_ID_2)],
            )
        )
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "x", "project_ids": f"{PROJECT_ID},{PROJECT_ID_2}"},
        )

        assert resp.status_code == 200
        assert resp.json()["project_ids"] == [PROJECT_ID, PROJECT_ID_2]
        svc.search.assert_awaited_once_with(
            SearchQuery(
                q="x",
                project_ids=[uuid.UUID(PROJECT_ID), uuid.UUID(PROJECT_ID_2)],
                types=None,
                mode=SearchMode.KEYWORD,
                limit=20,
                offset=0,
            )
        )

    def test_search_missing_project_scope_returns_422(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_response())
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "林晚"},
        )

        assert resp.status_code == 422
        assert resp.json()["detail"] == "project_id or project_ids required"
        svc.search.assert_not_awaited()

    def test_search_invalid_project_id_returns_422(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_response())
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "林晚", "project_id": "not-a-uuid"},
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert detail[0]["loc"] == ["project_ids"]
        assert detail[0]["msg"] == "invalid UUID format"
        svc.search.assert_not_awaited()

    def test_search_invalid_types_returns_422(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_response())
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "林晚", "project_id": PROJECT_ID, "types": "bad"},
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert detail[0]["loc"] == ["types"]
        assert detail[0]["msg"] == "invalid SearchEntityType"
        svc.search.assert_not_awaited()

    def test_search_invalid_mode_returns_422(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_response())
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "林晚", "project_id": PROJECT_ID, "mode": "bad"},
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert detail[0]["loc"] == ["mode"]
        assert detail[0]["msg"] == "invalid SearchMode"
        svc.search.assert_not_awaited()

    def test_search_blank_q_returns_422(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(return_value=_response())
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": " ", "project_id": PROJECT_ID},
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert any("must not be blank" in m["msg"] for m in detail)
        svc.search.assert_not_awaited()

    def test_search_project_not_found_returns_404(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(side_effect=ProjectNotFoundError("项目不存在"))
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "林晚", "project_id": PROJECT_ID},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"

    def test_search_unknown_error_returns_500(self) -> None:
        svc = MagicMock()
        svc.search = AsyncMock(side_effect=RuntimeError("boom"))
        resp = _patch_request(
            svc,
            "GET",
            "/api/v1/search",
            params={"q": "林晚", "project_id": PROJECT_ID},
        )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"


class TestRebuildEndpoint:
    """POST /api/v1/search/rebuild."""

    def test_rebuild_all_projects_when_no_param(self) -> None:
        svc = MagicMock()
        svc.rebuild = AsyncMock(
            return_value={"rebuilt_at": "2026-08-30T00:00:00+00:00", "project_ids": None}
        )
        resp = _patch_request(svc, "POST", "/api/v1/search/rebuild")

        assert resp.status_code == 200
        assert resp.json()["project_ids"] is None
        svc.rebuild.assert_awaited_once_with(None)

    def test_rebuild_single_project(self) -> None:
        svc = MagicMock()
        svc.rebuild = AsyncMock(
            return_value={
                "rebuilt_at": "2026-08-30T00:00:00+00:00",
                "project_ids": [PROJECT_ID],
            }
        )
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/search/rebuild",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 200
        assert resp.json()["project_ids"] == [PROJECT_ID]
        svc.rebuild.assert_awaited_once_with([uuid.UUID(PROJECT_ID).int])

    def test_rebuild_project_not_found_returns_404(self) -> None:
        svc = MagicMock()
        svc.rebuild = AsyncMock(side_effect=ProjectNotFoundError("项目不存在"))
        resp = _patch_request(
            svc,
            "POST",
            "/api/v1/search/rebuild",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"
