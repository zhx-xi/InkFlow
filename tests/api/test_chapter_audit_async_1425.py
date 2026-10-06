"""#1425 RED 契约 —— 审计触发异步语义 REST 面（202 + 后台派发 + /status 轮询读口）.

契约（GREEN 实现必须满足，spec §3.1/§3.2/§3.3 v1.5）:
- `POST /api/v1/projects/{pid}/chapters/{cid}/audit` → **202** body `{log_id, status}`；
  service 走 `submit(...)`（**不再直接返回报告**）；`created=True` 时经
  `spawn_background_task(svc.run_audit_job(...), key=str(log_id))` 派发后台任务。
- 幂等复用（`created=False`）→ 202 + `status='completed'`，**不派发**后台任务。
- 404 语义不变（项目/章节不存在、无效 UUID → 受理前失败，不派发）。
- `GET /api/v1/audit-logs/{log_id}/status` → 200 `AuditRunInfo`（无项目段）；
  未命中/非法 log_id → 404「审计记录不存在」。

依据: issue #1425 + specs/f34-chapter-audit/spec.md §3（v1.5）/§7 E19-E22。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.chapter_audit import AuditLog, AuditRunStatus
from inkflow.domain.ports.chapter_audit_errors import AuditLogNotFoundError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
TS = datetime(2026, 10, 7, 10, 0, 0, tzinfo=UTC)


def _log(
    run_status: AuditRunStatus = AuditRunStatus.RUNNING,
    *,
    status: str = "pending",
    error: str = "",
) -> AuditLog:
    """构造审计记录（默认 running，受理面）."""
    return AuditLog(
        id=LOG_ID,
        project_id=PID,
        chapter_id=CID,
        chapter_title="第 3 章 龙的苏醒",
        status=status,  # type: ignore[arg-type]  # 测试构造：仅取合法确认态
        run_status=run_status,
        severity_summary="",
        summary="",
        degraded=False,
        note="",
        created_at=TS,
        confirmed_at=None,
        error=error,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """patch 工厂返回 Mock 服务（同既有 API 测试模式）."""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestTriggerAuditAsync:
    """POST .../audit —— 202 受理语义（spec §3.1 v1.5）."""

    @patch("inkflow.api.routers.chapter_audit.spawn_background_task")
    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_returns_202_with_log_id_and_dispatches(
        self, mock_get_svc: MagicMock, mock_spawn: MagicMock
    ) -> None:
        """新任务 → 202 {log_id, status=running} + 后台任务被派发（key=log_id）."""
        svc = _mock_svc(mock_get_svc)
        svc.submit = AsyncMock(return_value=(_log(AuditRunStatus.RUNNING), True))

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 202
        data = response.json()
        assert data == {"log_id": str(LOG_ID), "status": "running"}
        svc.submit.assert_awaited_once_with(PID, CID, include_static=True)
        mock_spawn.assert_called_once()
        assert mock_spawn.call_args.kwargs["key"] == str(LOG_ID)
        svc.run_audit_job.assert_called_once()

    @patch("inkflow.api.routers.chapter_audit.spawn_background_task")
    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_include_static_false_passthrough(
        self, mock_get_svc: MagicMock, mock_spawn: MagicMock
    ) -> None:
        """include_static=False 透传 submit（spec §2.4）."""
        svc = _mock_svc(mock_get_svc)
        svc.submit = AsyncMock(return_value=(_log(AuditRunStatus.RUNNING), True))

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={"include_static": False}
        )

        assert response.status_code == 202
        svc.submit.assert_awaited_once_with(PID, CID, include_static=False)

    @patch("inkflow.api.routers.chapter_audit.spawn_background_task")
    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_reuse_returns_completed_and_does_not_dispatch(
        self, mock_get_svc: MagicMock, mock_spawn: MagicMock
    ) -> None:
        """幂等复用（created=False）→ 202 status=completed，不派发后台任务（E22）."""
        svc = _mock_svc(mock_get_svc)
        svc.submit = AsyncMock(
            return_value=(_log(AuditRunStatus.COMPLETED, status="pending"), False)
        )

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 202
        assert response.json()["status"] == "completed"
        mock_spawn.assert_not_called()
        svc.run_audit_job.assert_not_called()

    @patch("inkflow.api.routers.chapter_audit.spawn_background_task")
    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_project_not_found_404_no_dispatch(
        self, mock_get_svc: MagicMock, mock_spawn: MagicMock
    ) -> None:
        """项目不存在 → 404「项目不存在」（受理前失败，不派发）."""
        svc = _mock_svc(mock_get_svc)
        svc.submit = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        mock_spawn.assert_not_called()

    @patch("inkflow.api.routers.chapter_audit.spawn_background_task")
    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_chapter_not_found_404_no_dispatch(
        self, mock_get_svc: MagicMock, mock_spawn: MagicMock
    ) -> None:
        """章节不存在 → 404「章节不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.submit = AsyncMock(side_effect=ChapterNotFoundError())

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"
        mock_spawn.assert_not_called()

    @patch("inkflow.api.routers.chapter_audit.spawn_background_task")
    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_invalid_uuid_404_exits_before_service(
        self, mock_get_svc: MagicMock, mock_spawn: MagicMock
    ) -> None:
        """无效 project_id → 404（解析层拦下，service 不被调用）."""
        svc = _mock_svc(mock_get_svc)
        svc.submit = AsyncMock(return_value=(_log(), True))

        response = client.post(f"/api/v1/projects/not-a-uuid/chapters/{CID}/audit", json={})

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        svc.submit.assert_not_awaited()
        mock_spawn.assert_not_called()

    @patch("inkflow.api.routers.chapter_audit.spawn_background_task")
    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_internal_error_500(self, mock_get_svc: MagicMock, mock_spawn: MagicMock) -> None:
        """受理阶段意外异常 → 500「内部错误: ...」（受理前失败面）."""
        svc = _mock_svc(mock_get_svc)
        svc.submit = AsyncMock(side_effect=RuntimeError("内核炸了"))

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 500
        assert response.json()["detail"] == "内部错误: 内核炸了"


class TestAuditStatusEndpoint:
    """GET /audit-logs/{log_id}/status —— 轻量轮询读口（spec §3.1 v1.5）."""

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_status_200_completed(self, mock_get_svc: MagicMock) -> None:
        """命中 → 200 AuditRunInfo（run_status/error/created_at 等）."""
        svc = _mock_svc(mock_get_svc)
        svc.get_status = AsyncMock(return_value=_log(AuditRunStatus.COMPLETED))

        response = client.get(f"/api/v1/audit-logs/{LOG_ID}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["log_id"] == str(LOG_ID)
        assert data["run_status"] == "completed"
        assert data["status"] == "pending"
        assert data["error"] == ""
        assert data["chapter_id"] == str(CID)
        assert data["chapter_title"] == "第 3 章 龙的苏醒"
        assert data["created_at"].startswith("2026-10-07T10:00:00")
        svc.get_status.assert_awaited_once_with(LOG_ID)

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_status_200_failed_surfaces_error(self, mock_get_svc: MagicMock) -> None:
        """失败终态 → 200 + run_status=failed + error 透出（HTTP 不报错）."""
        svc = _mock_svc(mock_get_svc)
        svc.get_status = AsyncMock(
            return_value=_log(AuditRunStatus.FAILED, error="审计任务失败: boom")
        )

        response = client.get(f"/api/v1/audit-logs/{LOG_ID}/status")

        assert response.status_code == 200
        assert response.json()["run_status"] == "failed"
        assert response.json()["error"] == "审计任务失败: boom"

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_status_404_when_missing(self, mock_get_svc: MagicMock) -> None:
        """记录不存在 → 404「审计记录不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get_status = AsyncMock(side_effect=AuditLogNotFoundError())

        response = client.get(f"/api/v1/audit-logs/{LOG_ID}/status")

        assert response.status_code == 404
        assert response.json()["detail"] == "审计记录不存在"

    def test_status_404_invalid_log_id(self) -> None:
        """非法 log_id → 404（解析层即拦，service 不被调用）."""
        response = client.get("/api/v1/audit-logs/not-a-uuid/status")

        assert response.status_code == 404
        assert response.json()["detail"] == "审计记录不存在"
