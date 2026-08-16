"""F47 聊天管线 API 契约（spec §3.2）：POST /pipelines/execute 支持 builtin:chat。

镜像 tests/api/test_agent_templates_api.py 的 mock 服务层模式：
模块级 TestClient + 逐用例 @patch("inkflow.api.routers.agent._svc")。

RED 形态：
- chat 模板未注册时，AgentService.execute 抛「管线不存在」→ 422（mock svc 需要
  模拟该行为；模板注册后真实链路 202）。
- GREEN 需在 execute_pipeline 对 pipeline=builtin:chat 且 variables 缺 prompt 返回 422。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app

client = TestClient(app)

PROJECT_ID = str(uuid.uuid4())


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock AgentService（patch 工厂返回它）。"""
    svc = MagicMock()
    svc.execute = AsyncMock(
        return_value={
            "execution_id": "exec-chat-1",
            "pipeline": "builtin:chat",
            "project_id": PROJECT_ID,
            "status": "pending",
            "created_at": "2026-08-16T10:00:00Z",
        }
    )
    mock_get_svc.return_value = svc
    return svc


class TestExecuteChatPipeline:
    """POST /api/v1/agent/pipelines/execute — builtin:chat（spec §3.2）。"""

    @patch("inkflow.api.routers.agent._svc")
    def test_execute_chat_returns_202(self, mock_get_svc: MagicMock) -> None:
        """chat 管线执行 → 202 + execution_id。"""
        _mock_svc(mock_get_svc)
        resp = client.post(
            "/api/v1/agent/pipelines/execute",
            json={
                "project_id": PROJECT_ID,
                "pipeline": "builtin:chat",
                "variables": {"prompt": "帮我写一段打斗场景"},
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["execution_id"] == "exec-chat-1"
        assert body["pipeline"] == "builtin:chat"

    @patch("inkflow.api.routers.agent._svc")
    def test_execute_chat_calls_svc_with_prompt(self, mock_get_svc: MagicMock) -> None:
        """svc.execute 收到 pipeline=builtin:chat + variables.prompt。"""
        svc = _mock_svc(mock_get_svc)
        client.post(
            "/api/v1/agent/pipelines/execute",
            json={
                "project_id": PROJECT_ID,
                "pipeline": "builtin:chat",
                "variables": {"prompt": "解释这个角色的动机"},
            },
        )
        svc.execute.assert_called_once()
        _, kwargs = svc.execute.call_args
        req = kwargs["data"] if "data" in kwargs else svc.execute.call_args[0][0]
        assert req.pipeline == "builtin:chat"
        assert req.variables["prompt"] == "解释这个角色的动机"

    @patch("inkflow.api.routers.agent._svc")
    def test_execute_chat_missing_prompt_returns_422(
        self, mock_get_svc: MagicMock
    ) -> None:
        """chat 管线 variables 缺 prompt → 422（spec §5 错误表）。"""
        _mock_svc(mock_get_svc)
        resp = client.post(
            "/api/v1/agent/pipelines/execute",
            json={
                "project_id": PROJECT_ID,
                "pipeline": "builtin:chat",
                "variables": {},
            },
        )
        assert resp.status_code == 422
