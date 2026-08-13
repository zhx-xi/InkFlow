"""F29 Supervisor API 契约 — execute mode 透传 + HITL confirm 端点（spec §3）。

被测（MODIFY 既有 api/routers/agent.py）：
1. POST /api/v1/agent/pipelines/execute body 含 mode=supervisor + supervisor 配置
   → 202 + mode 透传（既有 _svc().execute 收到 PipelineExecuteRequest(mode=supervisor)）
2. POST /api/v1/agent/pipelines/executions/{id}/confirm（新端点）
   - body {approved: bool} → 200（确认成功，svc.confirm_execution 被调）
   - 执行记录非 waiting_hitl → 422「执行记录不在等待确认状态」
   - 执行记录不存在 → 404「执行记录不存在」
3. GET /api/v1/agent/pipelines/executions/{id} status=waiting_hitl → 响应含 hitl_pending

RED 预期：
- execute mode=supervisor：Pydantic 拒 extra → 422（与既有 422 断言可区分——用 detail 断言）
- confirm 端点未注册 → 404「Not Found」（FastAPI 默认），detail 断言 FAIL
  （追加段规则 1e：新用例 FAIL + 既有用例 PASS）
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app

client = TestClient(app)


def _execution_id() -> str:
    return str(uuid.uuid4())


class TestExecuteModeTransparent:
    """execute 端点 mode 透传契约（spec §3）。"""

    @patch("inkflow.api.routers.agent._svc")
    def test_execute_mode_supervisor_202(self, mock_svc: MagicMock) -> None:
        """mode=supervisor + supervisor 配置 → 202 + mode 透传。"""
        svc = mock_svc.return_value
        svc.execute = AsyncMock(
            return_value={
                "execution_id": _execution_id(),
                "pipeline": "builtin:write_chapter",
                "project_id": "1",
                "status": "pending",
                "created_at": "",
                "mode": "supervisor",
            }
        )

        response = client.post(
            "/api/v1/agent/pipelines/execute",
            json={
                "project_id": "00000000-0000-0000-0000-000000000001",
                "pipeline": "builtin:write_chapter",
                "mode": "supervisor",
                "supervisor": {"max_steps": 10, "hitl_roles": ["reviser"]},
            },
        )
        assert response.status_code == 202
        data = response.json()
        assert data["mode"] == "supervisor"

    @patch("inkflow.api.routers.agent._svc")
    def test_execute_mode_supervisor_missing_config_422(self, mock_svc: MagicMock) -> None:
        """mode=supervisor 但 supervisor 配置缺失 → 422（detail 断言）。"""
        svc = mock_svc.return_value
        from inkflow.domain.services.agent_service import AgentServiceError

        svc.execute = AsyncMock(
            side_effect=AgentServiceError("supervisor 模式需要 supervisor 配置")
        )

        response = client.post(
            "/api/v1/agent/pipelines/execute",
            json={
                "project_id": "00000000-0000-0000-0000-000000000001",
                "mode": "supervisor",
                "supervisor": None,
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "supervisor 模式需要 supervisor 配置"


class TestConfirmEndpoint:
    """HITL 确认端点契约（spec §3，新端点）。"""

    @patch("inkflow.api.routers.agent._svc")
    def test_confirm_success(self, mock_svc: MagicMock) -> None:
        """waiting_hitl 执行记录 confirm approved → 200。"""
        svc = mock_svc.return_value
        svc.confirm_execution = AsyncMock(
            return_value={
                "execution_id": _execution_id(),
                "status": "completed",
                "final_output": "定稿",
            }
        )
        exec_id = _execution_id()

        response = client.post(
            f"/api/v1/agent/pipelines/executions/{exec_id}/confirm",
            json={"approved": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        svc.confirm_execution.assert_awaited_once()

    @patch("inkflow.api.routers.agent._svc")
    def test_confirm_non_hitl_422(self, mock_svc: MagicMock) -> None:
        """非 waiting_hitl → 422「执行记录不在等待确认状态」。"""
        svc = mock_svc.return_value
        from inkflow.domain.services.agent_service import AgentServiceError

        svc.confirm_execution = AsyncMock(side_effect=AgentServiceError("执行记录不在等待确认状态"))
        exec_id = _execution_id()

        response = client.post(
            f"/api/v1/agent/pipelines/executions/{exec_id}/confirm",
            json={"approved": True},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "执行记录不在等待确认状态"

    @patch("inkflow.api.routers.agent._svc")
    def test_confirm_not_found_404(self, mock_svc: MagicMock) -> None:
        """执行记录不存在 → 404「执行记录不存在」。"""
        svc = mock_svc.return_value
        from inkflow.domain.services.agent_service import AgentServiceError

        svc.confirm_execution = AsyncMock(side_effect=AgentServiceError("执行记录不存在"))
        exec_id = _execution_id()

        response = client.post(
            f"/api/v1/agent/pipelines/executions/{exec_id}/confirm",
            json={"approved": True},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "执行记录不存在"

    @patch("inkflow.api.routers.agent._svc")
    def test_confirm_endpoint_registered(self, mock_svc: MagicMock) -> None:
        """confirm 端点已注册（RED：未注册 → 404 Not Found，detail 断言区分）。"""
        svc = mock_svc.return_value
        svc.confirm_execution = AsyncMock(return_value={"status": "completed"})
        exec_id = _execution_id()

        response = client.post(
            f"/api/v1/agent/pipelines/executions/{exec_id}/confirm",
            json={"approved": True},
        )
        # RED 阶段：端点未注册 → 404 + detail="Not Found"（FastAPI 默认）
        # GREEN 后：200 + status=completed
        assert response.status_code == 200
        assert response.json()["status"] == "completed"


class TestGetStatusHitlPending:
    """GET 执行状态含 hitl_pending 契约（spec §3）。"""

    @patch("inkflow.api.routers.agent._svc")
    def test_status_waiting_hitl_contains_payload(self, mock_svc: MagicMock) -> None:
        """status=waiting_hitl → 响应含 hitl_pending 详情。"""
        svc = mock_svc.return_value
        exec_id = _execution_id()
        svc.get_status = AsyncMock(
            return_value={
                "execution_id": exec_id,
                "pipeline": "builtin:write_chapter",
                "project_id": "1",
                "status": "waiting_hitl",
                "stages": [],
                "final_output": "",
                "total_duration_ms": 0,
                "error": "",
                "hitl_pending": {
                    "role": "reviser",
                    "question": "确认执行角色 reviser（修订）？",
                },
            }
        )

        response = client.get(f"/api/v1/agent/pipelines/executions/{exec_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "waiting_hitl"
        assert data["hitl_pending"]["role"] == "reviser"
