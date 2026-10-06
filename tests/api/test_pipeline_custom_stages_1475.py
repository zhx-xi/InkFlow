"""#1475 自定义管线 API 契约（spec f42 §3 / §5.8.1 / §13 M10）。

`POST /api/v1/agent/pipelines/execute` body 增 `stages` / `pipeline_config`（互斥可选）：
- 通过 → 202（服务层收全字段）；
- DTO 层约束（互斥 / 非 static / 空序列）→ **422**（FastAPI/Pydantic 请求校验，不经服务层）；
- 服务层约束（未知 role_key / 拓扑非法）→ **422**（`AgentServiceError` → router 映射）；
- 内置请求（不带两字段）→ 202 且两字段为 None（**零回归**）。

镜像 tests/api/test_pipeline_execute_chat.py 的模块级 TestClient + patch `_svc` 模式。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.services.agent_service import AgentServiceError

client = TestClient(app)

PROJECT_ID = str(uuid.uuid4())


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    svc = MagicMock()
    svc.execute = AsyncMock(
        return_value={
            "execution_id": "exec-1475",
            "pipeline": "custom",
            "project_id": PROJECT_ID,
            "status": "pending",
            "created_at": "2026-10-07T10:00:00Z",
        }
    )
    mock_get_svc.return_value = svc
    return svc


def _request_body(mock_get_svc: MagicMock):
    """取服务层收到的 PipelineExecuteRequest。"""
    return mock_get_svc.return_value.execute.call_args[0][0]


YAML_CONFIG = {
    "name": "世界观润色链",
    "source": "yaml",
    "stages": [
        {
            "id": "worldview",
            "name": "世界观校验",
            "agent": {"id": "worldview", "name": "世界观顾问", "system_prompt": "校验设定"},
        },
        {
            "id": "polisher",
            "name": "文笔润色",
            "agent": {"id": "polisher", "name": "润色师", "system_prompt": "润色文笔"},
        },
    ],
}


class TestCustomStagesExecute:
    """两形态透传（202）+ 零回归。"""

    @patch("inkflow.api.routers.agent._svc")
    def test_stages_form_returns_202_and_reaches_service(self, mock_get_svc: MagicMock) -> None:
        _mock_svc(mock_get_svc)
        resp = client.post(
            "/api/v1/agent/pipelines/execute",
            json={
                "project_id": PROJECT_ID,
                "pipeline": "worldview,polisher",
                "stages": ["worldview", "polisher"],
            },
        )

        assert resp.status_code == 202
        assert resp.json()["execution_id"] == "exec-1475"
        request = _request_body(mock_get_svc)
        assert request.stages == ["worldview", "polisher"]
        assert request.pipeline_config is None

    @patch("inkflow.api.routers.agent._svc")
    def test_pipeline_config_form_returns_202(self, mock_get_svc: MagicMock) -> None:
        _mock_svc(mock_get_svc)
        resp = client.post(
            "/api/v1/agent/pipelines/execute",
            json={
                "project_id": PROJECT_ID,
                "pipeline": "chain.yaml",
                "pipeline_config": YAML_CONFIG,
            },
        )

        assert resp.status_code == 202
        request = _request_body(mock_get_svc)
        assert request.stages is None
        assert request.pipeline_config is not None
        assert [s.id for s in request.pipeline_config.stages] == ["worldview", "polisher"]

    @patch("inkflow.api.routers.agent._svc")
    def test_builtin_request_zero_regression(self, mock_get_svc: MagicMock) -> None:
        _mock_svc(mock_get_svc)
        resp = client.post(
            "/api/v1/agent/pipelines/execute",
            json={"project_id": PROJECT_ID, "pipeline": "builtin:write_auto"},
        )

        assert resp.status_code == 202
        request = _request_body(mock_get_svc)
        assert request.stages is None
        assert request.pipeline_config is None


_INVALID_PAYLOADS: list[tuple[str, dict, str]] = [
    (
        "mutually_exclusive",
        {"stages": ["writer"], "pipeline_config": YAML_CONFIG},
        "stages 与 pipeline_config 互斥",
    ),
    ("empty_stages", {"stages": []}, "stages 不能为空"),
    (
        "supervisor_mode",
        {"stages": ["worldview"], "mode": "supervisor"},
        "自定义 stage 仅支持 static 模式",
    ),
]


class TestCustomPipelineRequestValidation:
    """DTO 层 422（不经服务层）。"""

    @patch("inkflow.api.routers.agent._svc")
    def test_invalid_payload_returns_422(self, mock_get_svc: MagicMock) -> None:
        svc = _mock_svc(mock_get_svc)
        for name, extra, expected in _INVALID_PAYLOADS:
            resp = client.post(
                "/api/v1/agent/pipelines/execute",
                json={"project_id": PROJECT_ID, "pipeline": "x", **extra},
            )
            assert resp.status_code == 422, f"{name} 应 422"
            assert expected in resp.text, f"{name} detail 应含 {expected!r}"
            svc.execute.assert_not_awaited()


class TestCustomPipelineServiceErrors:
    """服务层 422（未知 role_key / 拓扑非法）。"""

    @patch("inkflow.api.routers.agent._svc")
    def test_unknown_role_key_maps_to_422(self, mock_get_svc: MagicMock) -> None:
        svc = _mock_svc(mock_get_svc)
        svc.execute = AsyncMock(side_effect=AgentServiceError("未知 stage 角色: ghost"))

        resp = client.post(
            "/api/v1/agent/pipelines/execute",
            json={"project_id": PROJECT_ID, "pipeline": "ghost", "stages": ["ghost"]},
        )

        assert resp.status_code == 422
        assert "未知 stage 角色: ghost" in resp.json()["detail"]

    @patch("inkflow.api.routers.agent._svc")
    def test_invalid_topology_maps_to_422(self, mock_get_svc: MagicMock) -> None:
        svc = _mock_svc(mock_get_svc)
        svc.execute = AsyncMock(
            side_effect=AgentServiceError("自定义管线配置无效: 管线存在循环依赖")
        )

        resp = client.post(
            "/api/v1/agent/pipelines/execute",
            json={"project_id": PROJECT_ID, "pipeline": "bad.yaml", "pipeline_config": YAML_CONFIG},
        )

        assert resp.status_code == 422
        assert "自定义管线配置无效" in resp.json()["detail"]
