"""F28 agent memory REST API — HTTP 层契约测试（router memory.py）.

形态镜像 tests/unit/api/routers/test_chat_conversation_patch.py：
独立 FastAPI app + include_router + `dependency_overrides[get_memory_service]`
注入 mock service（服务方法为 AsyncMock）。

契约锁定（spec f28 §3）：
- GET  /api/v1/agent/preferences、/user-preferences → {"items", "total"}，
  category 过滤透传为 PreferenceCategory 枚举；
- DELETE/PATCH 路径 preference_id 为字符串 id，不存在 → 404「偏好不存在」；
- POST /preferences、/user-preferences → 201 flat dict（model_dump 全字段透传）；
- PATCH body 全空 → 422「至少提供一个编辑字段」（Pydantic model_validator）；
- GET  /memory/stats、/memory/summaries、POST /memory/summarize、
  DELETE /memory/summaries → 直返服务 dict；summarize 失败 → 502「语义总结失败」；
  summaries 删除项目不存在 → 404「项目不存在」。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.deps import get_memory_service
from inkflow.api.routers.memory import router
from inkflow.domain.models.preference import PreferenceCategory
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.semantic_summary_errors import SemanticSummaryError
from inkflow.domain.services.memory_service import PreferenceNotFoundError

PROJECT_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


def _client(svc: MagicMock) -> TestClient:
    """独立 app 挂载 memory router + get_memory_service override（mock service）。"""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_memory_service] = lambda: svc
    return TestClient(app)


class TestListPreferences:
    """GET /api/v1/agent/preferences."""

    def test_list_preferences_with_category_filter(self) -> None:
        svc = MagicMock()
        svc.list_preferences = AsyncMock(
            return_value=(
                [{"id": "p1", "project_id": PROJECT_ID, "category": "addressing"}],
                1,
            )
        )
        resp = _client(svc).get(
            "/api/v1/agent/preferences",
            params={"project_id": PROJECT_ID, "category": "addressing"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == "p1"
        svc.list_preferences.assert_awaited_once_with(
            project_id=uuid.UUID(PROJECT_ID),
            category=PreferenceCategory.ADDRESSING,
        )

    def test_list_preferences_without_category(self) -> None:
        svc = MagicMock()
        svc.list_preferences = AsyncMock(return_value=([], 0))
        resp = _client(svc).get(
            "/api/v1/agent/preferences",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}
        svc.list_preferences.assert_awaited_once_with(
            project_id=uuid.UUID(PROJECT_ID),
            category=None,
        )


class TestRemovePreference:
    """DELETE /api/v1/agent/preferences/{preference_id}."""

    def test_delete_preference_returns_deleted(self) -> None:
        svc = MagicMock()
        svc.remove_preference = AsyncMock(return_value=None)
        resp = _client(svc).delete("/api/v1/agent/preferences/pref-1")

        assert resp.status_code == 200
        assert resp.json() == {"preference_id": "pref-1", "deleted": True}
        svc.remove_preference.assert_awaited_once_with("pref-1")

    def test_delete_missing_preference_returns_404(self) -> None:
        svc = MagicMock()
        svc.remove_preference = AsyncMock(side_effect=PreferenceNotFoundError())
        resp = _client(svc).delete("/api/v1/agent/preferences/missing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "偏好不存在"


class TestListUserPreferences:
    """GET /api/v1/agent/user-preferences."""

    def test_list_user_preferences(self) -> None:
        svc = MagicMock()
        svc.list_user_preferences = AsyncMock(
            return_value=([{"id": "up-1", "category": "style_word"}], 1)
        )
        resp = _client(svc).get("/api/v1/agent/user-preferences")

        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == "up-1"
        svc.list_user_preferences.assert_awaited_once_with(category=None)


class TestRemoveUserPreference:
    """DELETE /api/v1/agent/user-preferences/{preference_id}."""

    def test_delete_user_preference_returns_deleted(self) -> None:
        svc = MagicMock()
        svc.remove_user_preference = AsyncMock(return_value=None)
        resp = _client(svc).delete("/api/v1/agent/user-preferences/up-1")

        assert resp.status_code == 200
        assert resp.json() == {"preference_id": "up-1", "deleted": True}
        svc.remove_user_preference.assert_awaited_once_with("up-1")

    def test_delete_missing_user_preference_returns_404(self) -> None:
        svc = MagicMock()
        svc.remove_user_preference = AsyncMock(side_effect=PreferenceNotFoundError())
        resp = _client(svc).delete("/api/v1/agent/user-preferences/missing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "偏好不存在"


class TestCreatePreference:
    """POST /api/v1/agent/preferences → 201."""

    def test_create_preference_returns_201(self) -> None:
        svc = MagicMock()
        svc.create_preference = AsyncMock(return_value={"id": "p-new"})
        resp = _client(svc).post(
            "/api/v1/agent/preferences",
            json={
                "project_id": PROJECT_ID,
                "category": "addressing",
                "pattern": "她",
                "value": "林晚",
                "confidence": 0.5,
                "count": 2,
            },
        )

        assert resp.status_code == 201
        assert resp.json() == {"id": "p-new"}
        svc.create_preference.assert_awaited_once_with(
            project_id=uuid.UUID(PROJECT_ID),
            category=PreferenceCategory.ADDRESSING,
            pattern="她",
            value="林晚",
            confidence=0.5,
            count=2,
        )

    def test_create_preference_missing_value_returns_422(self) -> None:
        svc = MagicMock()
        svc.create_preference = AsyncMock(return_value={})
        resp = _client(svc).post(
            "/api/v1/agent/preferences",
            json={"project_id": PROJECT_ID, "category": "addressing", "pattern": "她"},
        )

        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)
        svc.create_preference.assert_not_awaited()


class TestCreateUserPreference:
    """POST /api/v1/agent/user-preferences → 201."""

    def test_create_user_preference_returns_201(self) -> None:
        svc = MagicMock()
        svc.create_user_preference = AsyncMock(return_value={"id": "up-new"})
        resp = _client(svc).post(
            "/api/v1/agent/user-preferences",
            json={
                "category": "style_word",
                "pattern": "说",
                "value": "低声道",
                "confidence": 0.8,
                "count": 3,
            },
        )

        assert resp.status_code == 201
        assert resp.json() == {"id": "up-new"}
        svc.create_user_preference.assert_awaited_once_with(
            category=PreferenceCategory.STYLE_WORD,
            pattern="说",
            value="低声道",
            confidence=0.8,
            count=3,
        )


class TestUpdatePreference:
    """PATCH /api/v1/agent/preferences/{preference_id}."""

    def test_update_preference_returns_updated(self) -> None:
        svc = MagicMock()
        svc.update_preference = AsyncMock(
            return_value={"id": "p1", "value": "新值", "category": "addressing"}
        )
        resp = _client(svc).patch(
            "/api/v1/agent/preferences/p1",
            json={"value": "新值"},
        )

        assert resp.status_code == 200
        assert resp.json()["value"] == "新值"
        svc.update_preference.assert_awaited_once_with("p1", value="新值")

    def test_update_missing_preference_returns_404(self) -> None:
        svc = MagicMock()
        svc.update_preference = AsyncMock(side_effect=PreferenceNotFoundError())
        resp = _client(svc).patch(
            "/api/v1/agent/preferences/missing",
            json={"value": "新值"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "偏好不存在"

    def test_update_empty_body_returns_422(self) -> None:
        svc = MagicMock()
        svc.update_preference = AsyncMock(return_value={})
        resp = _client(svc).patch("/api/v1/agent/preferences/p1", json={})

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert any("至少提供一个编辑字段" in m["msg"] for m in detail)
        svc.update_preference.assert_not_awaited()


class TestUpdateUserPreference:
    """PATCH /api/v1/agent/user-preferences/{preference_id}."""

    def test_update_user_preference_returns_updated(self) -> None:
        svc = MagicMock()
        svc.update_user_preference = AsyncMock(return_value={"id": "up-1", "pattern": "新模式"})
        resp = _client(svc).patch(
            "/api/v1/agent/user-preferences/up-1",
            json={"pattern": "新模式"},
        )

        assert resp.status_code == 200
        assert resp.json()["pattern"] == "新模式"
        svc.update_user_preference.assert_awaited_once_with("up-1", pattern="新模式")

    def test_update_missing_user_preference_returns_404(self) -> None:
        svc = MagicMock()
        svc.update_user_preference = AsyncMock(side_effect=PreferenceNotFoundError())
        resp = _client(svc).patch(
            "/api/v1/agent/user-preferences/missing",
            json={"pattern": "新模式"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "偏好不存在"


class TestMemoryStats:
    """GET /api/v1/agent/memory/stats."""

    def test_stats_returns_service_dict(self) -> None:
        svc = MagicMock()
        svc.stats = AsyncMock(return_value={"preferences_total": 3, "modified_rate": 0.1})
        resp = _client(svc).get(
            "/api/v1/agent/memory/stats",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 200
        assert resp.json() == {"preferences_total": 3, "modified_rate": 0.1}
        svc.stats.assert_awaited_once_with(project_id=uuid.UUID(PROJECT_ID))

    def test_stats_missing_project_id_returns_422(self) -> None:
        svc = MagicMock()
        svc.stats = AsyncMock(return_value={})
        resp = _client(svc).get("/api/v1/agent/memory/stats")

        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)
        svc.stats.assert_not_awaited()

    def test_stats_invalid_project_id_returns_422(self) -> None:
        svc = MagicMock()
        svc.stats = AsyncMock(return_value={})
        resp = _client(svc).get(
            "/api/v1/agent/memory/stats",
            params={"project_id": "not-a-uuid"},
        )

        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)
        svc.stats.assert_not_awaited()


class TestMemorySummaries:
    """GET /api/v1/agent/memory/summaries."""

    def test_summaries_returns_service_dict(self) -> None:
        svc = MagicMock()
        svc.get_summaries = AsyncMock(
            return_value={
                "project_id": PROJECT_ID,
                "project": {"summary": "…"},
                "user": None,
            }
        )
        resp = _client(svc).get(
            "/api/v1/agent/memory/summaries",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 200
        assert resp.json()["project"]["summary"] == "…"
        svc.get_summaries.assert_awaited_once_with(project_id=uuid.UUID(PROJECT_ID))


class TestMemorySummarize:
    """POST /api/v1/agent/memory/summarize."""

    def test_summarize_returns_service_dict(self) -> None:
        svc = MagicMock()
        svc.summarize = AsyncMock(return_value={"summary": "新总结"})
        resp = _client(svc).post(
            "/api/v1/agent/memory/summarize",
            params={"project_id": PROJECT_ID, "force": "true"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"summary": "新总结"}
        svc.summarize.assert_awaited_once_with(
            project_id=uuid.UUID(PROJECT_ID),
            force=True,
        )

    def test_summarize_semantic_error_returns_502(self) -> None:
        svc = MagicMock()
        svc.summarize = AsyncMock(side_effect=SemanticSummaryError())
        resp = _client(svc).post(
            "/api/v1/agent/memory/summarize",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 502
        assert resp.json()["detail"] == "语义总结失败"


class TestRemoveMemorySummaries:
    """DELETE /api/v1/agent/memory/summaries."""

    def test_remove_summaries_returns_service_dict(self) -> None:
        svc = MagicMock()
        svc.remove_summaries = AsyncMock(return_value={"deleted": True})
        resp = _client(svc).delete(
            "/api/v1/agent/memory/summaries",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 200
        assert resp.json() == {"deleted": True}
        svc.remove_summaries.assert_awaited_once_with(project_id=uuid.UUID(PROJECT_ID))

    def test_remove_summaries_project_not_found_returns_404(self) -> None:
        svc = MagicMock()
        svc.remove_summaries = AsyncMock(side_effect=ProjectNotFoundError())
        resp = _client(svc).delete(
            "/api/v1/agent/memory/summaries",
            params={"project_id": PROJECT_ID},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"
