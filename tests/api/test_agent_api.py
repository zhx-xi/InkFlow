"""Agent API 集成测试 — Mock AgentService（不触发真实 LLM/DB 调用）。"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    """ASGI 测试客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_agent_service():
    """Mock AgentService — 各方法返回固定预设值。"""
    svc = AsyncMock()
    svc.execute.return_value = {
        "execution_id": "abc-123",
        "pipeline": "builtin:write_chapter",
        "project_id": "3f2e1d4a-0000-0000-0000-000000000001",
        "status": "pending",
        "created_at": "2026-07-31T10:00:00Z",
    }
    svc.get_status.return_value = {
        "execution_id": "abc-123",
        "status": "completed",
        "stages": [],
        "final_output": "test",
        "total_duration_ms": 100,
        "error": "",
    }
    svc.list_executions.return_value = {"items": [], "total": 0}
    # validate_pipeline / list_templates 是同步方法 — 用 MagicMock 而非 AsyncMock
    svc.validate_pipeline = MagicMock(return_value={"valid": True, "errors": []})
    svc.list_templates = MagicMock(
        return_value={
            "items": [{"id": "builtin:write_chapter", "name": "章节写作 (4 阶段)"}]
        }
    )
    return svc


@pytest.fixture
def patch_svc(mock_agent_service):
    """将 agent 路由的 _svc 替换为返回 mock service。"""
    with patch("inkflow.api.routers.agent._svc", return_value=mock_agent_service):
        yield mock_agent_service


class TestAgentAPI:
    async def test_execute_pipeline(self, client, patch_svc):
        """POST /api/v1/agent/pipelines/execute → 202 + execution_id。"""
        resp = await client.post(
            "/api/v1/agent/pipelines/execute",
            json={"project_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["execution_id"] == "abc-123"
        assert data["status"] == "pending"

    async def test_execute_missing_project_id(self, client):
        """缺 project_id → 422（Pydantic 验证）。"""
        resp = await client.post("/api/v1/agent/pipelines/execute", json={})
        assert resp.status_code == 422

    async def test_get_execution_status(self, client, patch_svc):
        """GET /api/v1/agent/pipelines/executions/{id} → 200 + status。"""
        resp = await client.get("/api/v1/agent/pipelines/executions/abc-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["final_output"] == "test"

    async def test_get_execution_not_found(self, client, patch_svc, mock_agent_service):
        """GET 不存在 execution → 404。"""
        mock_agent_service.get_status.return_value = None
        resp = await client.get("/api/v1/agent/pipelines/executions/nonexistent-1")
        assert resp.status_code == 404

    async def test_list_executions(self, client, patch_svc):
        """GET /api/v1/agent/pipelines/executions?project_id=xxx → 200 + items。"""
        resp = await client.get(
            "/api/v1/agent/pipelines/executions",
            params={"project_id": "3f2e1d4a-0000-0000-0000-000000000001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"items": [], "total": 0}

    async def test_validate_pipeline(self, client, patch_svc):
        """POST /api/v1/agent/pipelines/validate → 200 + valid/errors。"""
        body = {
            "name": "测试管线",
            "description": "API 校验测试",
            "stages": [
                {
                    "id": "writer",
                    "name": "写手",
                    "agent": {
                        "id": "writer",
                        "name": "写手",
                        "system_prompt": "你是一位小说写手",
                    },
                    "input_from": [],
                    "output_to": [],
                }
            ],
        }
        resp = await client.post("/api/v1/agent/pipelines/validate", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["errors"] == []

    async def test_list_templates(self, client, patch_svc):
        """GET /api/v1/agent/pipelines/templates → 200 + builtin:write_chapter。"""
        resp = await client.get("/api/v1/agent/pipelines/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["id"] == "builtin:write_chapter"
