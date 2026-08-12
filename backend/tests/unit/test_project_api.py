"""#143 项目 API 层测试 — Mock Service 层（补齐 API 级测试缺口）。

此前 project router 无 TestClient 级测试（根因：#143 模板创建 E2E 抓出
前端顶层 template_id 被后端静默丢弃——ProjectCreate 无该字段，Pydantic
extra='ignore' → config.template_id 恒 None，「创建即引用」契约断裂）。
本文件镜像 test_agent_templates_api.py 形态：模块级 TestClient(app) +
@patch("inkflow.api.routers.project._get_svc") 整体替换 Service 获取函数。

覆盖（spec §9.2.5「创建即引用」契约 + #143）：
- POST /api/v1/projects body 带顶层 template_id → service.create_project
  收到 config.template_id == str(template_id)（config JSON 存 str，#107 契约）；
- 不带 template_id → config.template_id 保持 None（默认模板语义）；
- 创建快乐路径 201 + 响应形状。

F42 #269 追加（spec §2.3/§3）：PATCH /api/v1/projects/{id} agent_order
语义校验映射——service 层校验抛 ValueError → router 转 422（detail 中文）；
Pydantic 结构校验（长度 >10/跨层重复）→ FastAPI 默认 422。

依据: specs/f19-gui/spec.md §9.2.5 + specs/f42-agent-chain-config/spec.md §2.3/§3。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.project import Genre, Project, ProjectConfig

client = TestClient(app)

TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _project(project_id: int, name: str, config: ProjectConfig | None = None) -> Project:
    """构造测试用 Project 实体（固定时间戳，便于断言）."""
    return Project(
        id=uuid.UUID(int=project_id),
        name=name,
        genre=Genre.QITA,
        language="zh-CN",
        target_words=0,
        config=config or ProjectConfig(),
        created_at=TS,
        updated_at=TS,
    )


class TestProjectCreateTemplateAPI:
    """创建项目带模板引用（spec §9.2.5「创建即引用」）— 顶层 template_id 必须落入 config."""

    @patch("inkflow.api.routers.project._get_svc")
    def test_create_with_template_id_merges_into_config(self, mock_get_svc: MagicMock) -> None:
        """POST body 顶层 template_id=7 → service 收到 config.template_id == '7'（str 契约）."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.create_project = AsyncMock(
            return_value=_project(1, "模板项目", ProjectConfig(template_id="7"))
        )

        response = client.post(
            "/api/v1/projects",
            json={
                "name": "模板项目",
                "genre": "玄幻",
                "language": "zh-CN",
                "target_words": 800000,
                "template_id": 7,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["config"]["template_id"] == "7"
        # service 收到的 config 必须携带 template_id（路由 merge 契约）
        _, kwargs = svc.create_project.call_args
        assert kwargs["config"].template_id == "7"

    @patch("inkflow.api.routers.project._get_svc")
    def test_create_without_template_id_keeps_none(self, mock_get_svc: MagicMock) -> None:
        """不带 template_id → config.template_id 保持 None（默认模板语义）."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.create_project = AsyncMock(return_value=_project(2, "默认项目"))

        response = client.post(
            "/api/v1/projects",
            json={"name": "默认项目", "genre": "玄幻", "language": "zh-CN", "target_words": 800000},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["config"]["template_id"] is None
        _, kwargs = svc.create_project.call_args
        assert kwargs["config"].template_id is None


class TestPatchAgentOrderValidation:
    """F42 #269 PATCH /api/v1/projects/{id} agent_order 语义校验映射（spec §2.3/§3）：
    service 层校验抛 ValueError → router 转 422（detail 中文）；Pydantic 结构校验
    （长度 >10/跨层重复）→ FastAPI 默认 422。

    RED 形态（规则 1e 追加段）：router 现无 ValueError catch → svc.update 抛
    ValueError 被 TestClient re-raise（ERROR）；Pydantic 结构非法用例当前
    extra='ignore' 静默丢弃 → 200（断言 422 FAIL）。
    """

    @patch("inkflow.api.routers.project._get_svc")
    def test_patch_missing_enabled_role_returns_422(self, mock_get_svc: MagicMock) -> None:
        """svc.update 抛 ValueError（校验失败）→ 422 + detail 中文消息。"""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.update = AsyncMock(
            side_effect=ValueError("agent_order 必须包含全部启用角色: agent_writer")
        )

        response = client.patch(
            f"/api/v1/projects/{uuid.UUID(int=1)}",
            json={"config": {"agent_order": [["agent_architect"]]}},
        )

        assert response.status_code == 422
        assert "agent_order 必须包含全部启用角色" in response.json()["detail"]

    @patch("inkflow.api.routers.project._get_svc")
    def test_patch_valid_agent_order_returns_200(self, mock_get_svc: MagicMock) -> None:
        """合法 agent_order → 200 + config.agent_order 回显（service 收到合并 config）。"""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        order = [["agent_architect"], ["agent_writer"], ["agent_auditor"], ["agent_reviser"]]
        svc.update = AsyncMock(
            return_value=_project(1, "排序项目", ProjectConfig(agent_order=order))
        )

        response = client.patch(
            f"/api/v1/projects/{uuid.UUID(int=1)}",
            json={"config": {"agent_order": order}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["config"]["agent_order"] == order
        # service 收到的 DTO config 含 agent_order（路由透传契约；kwargs/位置双形态宽松取参）
        call = svc.update.call_args
        dto = call.kwargs.get("data") or call.args[1]
        assert dto.config.agent_order == order

    @patch("inkflow.api.routers.project._get_svc")
    def test_patch_too_many_layers_returns_422(self, mock_get_svc: MagicMock) -> None:
        """agent_order 长度 >10（Pydantic 结构校验）→ 422（service 不被调用）。"""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.update = AsyncMock(return_value=_project(1, "x"))

        bad_order = [[f"agent_{i}"] for i in range(11)]
        response = client.patch(
            f"/api/v1/projects/{uuid.UUID(int=1)}",
            json={"config": {"agent_order": bad_order}},
        )

        assert response.status_code == 422
        svc.update.assert_not_awaited()

    @patch("inkflow.api.routers.project._get_svc")
    def test_patch_duplicate_role_returns_422(self, mock_get_svc: MagicMock) -> None:
        """agent_order 跨层重复（Pydantic 结构校验）→ 422。"""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.update = AsyncMock(return_value=_project(1, "x"))

        response = client.patch(
            f"/api/v1/projects/{uuid.UUID(int=1)}",
            json={"config": {"agent_order": [["agent_writer"], ["agent_writer"]]}},
        )

        assert response.status_code == 422
        svc.update.assert_not_awaited()
