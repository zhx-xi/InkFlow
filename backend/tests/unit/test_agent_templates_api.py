"""#107 AgentTemplate API 层测试 — Mock Service 层（补齐 API 级测试缺口）.

此前 agent_templates router 无 TestClient 级测试（根因：列表 used_by 缺失与
set_default 数字 id 422 均漏检）。本文件镜像 test_foreshadowing_api.py /
test_world_api.py 形态：模块级 TestClient(app) + @patch(
"inkflow.api.routers.agent_templates._get_service") 整体替换 Service 获取函数；
list/detail 端点另 patch SQLiteAgentTemplateRepository 以 mock
list_projects_by_template 引用查询（router 模块内本地引用）。

覆盖（spec §9.3 API 契约 + §9.5 测试策略「后端单元」）：
- 列表端点：{items, total} 信封不变，每项含 used_by 引用列表
  （被引用项目 [{id, name}] 与未引用 [] 两类）；
- 详情端点：used_by 与列表端点同构；
- PATCH /default：字符串 id → 200 is_default=True；数字 id → 422
  （Pydantic v2 不将 int 强转为 str，SetDefaultRequest.id: str 契约锁定）；
- create / update / delete 快乐路径 + 错误映射（404/422/409）；
- create/update 响应不含 used_by（_to_response 默认行为不被列表修复改变）。

依据: specs/f19-gui/spec.md §9.2/§9.3/§9.5。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.agent_template import AgentTemplate, RoleTemplate
from inkflow.domain.models.project import Genre, Project, ProjectConfig
from inkflow.domain.ports.agent_template_errors import (
    AgentTemplateBuiltinError,
    AgentTemplateNameConflictError,
    AgentTemplateNotFoundError,
)

client = TestClient(app)

TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _template(template_id: int, name: str, **kw) -> AgentTemplate:
    """构造测试用 AgentTemplate 实体（固定时间戳，便于断言）."""
    return AgentTemplate(
        id=template_id,
        name=name,
        created_at=TS,
        updated_at=TS,
        **kw,
    )


def _project(project_id: int, name: str, template_id: str | None) -> Project:
    """构造引用指定模板的项目实体（config.template_id 已设，契约 str 匹配）."""
    return Project(
        id=uuid.UUID(int=project_id),
        name=name,
        genre=Genre.QITA,
        language="zh-CN",
        target_words=0,
        config=ProjectConfig(template_id=template_id),
        created_at=TS,
        updated_at=TS,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock AgentTemplateService（被 await 方法按用例显式赋 AsyncMock）."""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


def _mock_template_repo(mock_repo_cls: MagicMock, refs: list[Project]) -> MagicMock:
    """构造 Mock SQLiteAgentTemplateRepository：list_projects_by_template 按 id 过滤 refs."""
    repo = MagicMock()
    repo.list_projects_by_template = AsyncMock(
        side_effect=lambda tid: [p for p in refs if p.config.template_id == str(tid)]
    )
    mock_repo_cls.return_value = repo
    return repo


class TestAgentTemplateListAPI:
    """模板列表端点（GET /api/v1/agent-templates）— 每项必须含 used_by."""

    @patch("inkflow.api.routers.agent_templates.SQLiteAgentTemplateRepository")
    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_list_includes_used_by(self, mock_get_svc: MagicMock, mock_repo_cls: MagicMock) -> None:
        """列表项携带 used_by 引用列表：被引用项 [{id, name}]、未引用项 []."""
        svc = _mock_svc(mock_get_svc)
        svc.list = AsyncMock(return_value=[_template(1, "经典奇幻"), _template(2, "悬疑推理")])
        refs = [_project(11, "项目甲", "1"), _project(22, "项目乙", "1")]
        _mock_template_repo(mock_repo_cls, refs)

        response = client.get("/api/v1/agent-templates")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["items"][0]["id"] == 1
        assert data["items"][0]["used_by"] == [
            {"id": str(uuid.UUID(int=11)), "name": "项目甲"},
            {"id": str(uuid.UUID(int=22)), "name": "项目乙"},
        ]
        assert data["items"][1]["id"] == 2
        assert data["items"][1]["used_by"] == []
        svc.list.assert_awaited_once()
        assert mock_repo_cls.return_value.list_projects_by_template.await_count == 2

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_list_empty_envelope(self, mock_get_svc: MagicMock) -> None:
        """空列表 → 200 {items: [], total: 0}（信封形状不变）."""
        svc = _mock_svc(mock_get_svc)
        svc.list = AsyncMock(return_value=[])

        response = client.get("/api/v1/agent-templates")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}


class TestAgentTemplateGetAPI:
    """模板详情端点（GET /api/v1/agent-templates/{template_id}）— 含 used_by."""

    @patch("inkflow.api.routers.agent_templates.SQLiteAgentTemplateRepository")
    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_get_includes_used_by(self, mock_get_svc: MagicMock, mock_repo_cls: MagicMock) -> None:
        """详情返回 used_by 引用列表（镜像 list 端点契约）."""
        svc = _mock_svc(mock_get_svc)
        svc.get = AsyncMock(return_value=_template(1, "经典奇幻"))
        _mock_template_repo(mock_repo_cls, [_project(11, "项目甲", "1")])

        response = client.get("/api/v1/agent-templates/1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["used_by"] == [{"id": str(uuid.UUID(int=11)), "name": "项目甲"}]
        svc.get.assert_awaited_once_with(1)
        mock_repo_cls.return_value.list_projects_by_template.assert_awaited_once_with(1)

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_get_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """模板不存在 → 404「模板不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get = AsyncMock(side_effect=AgentTemplateNotFoundError())

        response = client.get("/api/v1/agent-templates/999")
        assert response.status_code == 404
        assert response.json()["detail"] == "模板不存在"

    def test_get_invalid_id_404(self) -> None:
        """非整数 id → 404「模板不存在」（_parse_id 语义，非 422）."""
        response = client.get("/api/v1/agent-templates/not-a-number")
        assert response.status_code == 404
        assert response.json()["detail"] == "模板不存在"


class TestSetDefaultAPI:
    """PATCH /api/v1/agent-templates/default — id 契约 str（数字 id → 422）."""

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_set_default_string_id_success(self, mock_get_svc: MagicMock) -> None:
        """字符串 id → 200 + is_default=True；_parse_id 转 int 后透传 service."""
        svc = _mock_svc(mock_get_svc)
        template = _template(12, "经典奇幻", is_default=True)
        svc.set_default = AsyncMock(return_value=template)

        response = client.patch("/api/v1/agent-templates/default", json={"id": "12"})
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 12
        assert data["is_default"] is True
        svc.set_default.assert_awaited_once_with(12)

    def test_set_default_numeric_id_422(self) -> None:
        """数字 id → 422（Pydantic v2 不将 int 强转为 str，契约锁定）."""
        response = client.patch("/api/v1/agent-templates/default", json={"id": 12})
        assert response.status_code == 422

    def test_set_default_blank_id_422(self) -> None:
        """空白 id → 422（field_validator 拒绝空串）."""
        response = client.patch("/api/v1/agent-templates/default", json={"id": "  "})
        assert response.status_code == 422


class TestAgentTemplateCreateAPI:
    """创建模板端点（POST /api/v1/agent-templates）— 201 + 完整响应."""

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_create_success(self, mock_get_svc: MagicMock) -> None:
        """创建成功：roles 缺省键补齐 + model 回填内置默认；响应不含 used_by."""
        svc = _mock_svc(mock_get_svc)
        template = _template(
            1,
            "我的模板",
            description="desc",
            main_model="openai/gpt-4o",
            default_temperature=0.8,
            roles={"writer": RoleTemplate(model="m/w", temperature=0.6)},
            default_words=50000,
        )
        svc.create = AsyncMock(return_value=template)

        response = client.post(
            "/api/v1/agent-templates",
            json={
                "name": "我的模板",
                "description": "desc",
                "main_model": "openai/gpt-4o",
                "default_temperature": 0.8,
                "roles": {"writer": {"model": "m/w", "temperature": 0.6, "enabled": True}},
                "default_words": 50000,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "我的模板"
        assert data["roles"]["writer"]["model"] == "m/w"
        assert data["roles"]["architect"]["model"] == "openai/gpt-4o"  # 缺省角色回填
        assert data["roles"]["architect"]["enabled"] is True
        assert "used_by" not in data  # create 响应不附加 used_by（默认行为不变）
        svc.create.assert_awaited_once()
        args, _ = svc.create.await_args
        assert args[0].name == "我的模板"
        assert args[0].roles["writer"].model == "m/w"

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_create_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名模板 → 422，detail 即业务文案."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(side_effect=AgentTemplateNameConflictError())

        response = client.post("/api/v1/agent-templates", json={"name": "我的模板"})
        assert response.status_code == 422
        assert response.json()["detail"] == "同名模板已存在（模板名称必须唯一）"


class TestAgentTemplateUpdateAPI:
    """更新模板端点（PATCH /api/v1/agent-templates/{template_id}）."""

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_update_success(self, mock_get_svc: MagicMock) -> None:
        """部分更新 → 200 + 更新后实体；响应不含 used_by."""
        svc = _mock_svc(mock_get_svc)
        template = _template(7, "改名", main_model="m/new")
        svc.update = AsyncMock(return_value=template)

        response = client.patch(
            "/api/v1/agent-templates/7", json={"name": "改名", "main_model": "m/new"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "改名"
        assert data["main_model"] == "m/new"
        assert "used_by" not in data
        svc.update.assert_awaited_once()
        args, _ = svc.update.await_args
        assert args[0] == 7
        assert args[1].name == "改名"
        assert args[1].main_model == "m/new"

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_update_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """模板不存在 → 404「模板不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.update = AsyncMock(side_effect=AgentTemplateNotFoundError())

        response = client.patch("/api/v1/agent-templates/999", json={"name": "x"})
        assert response.status_code == 404
        assert response.json()["detail"] == "模板不存在"


class TestAgentTemplateDeleteAPI:
    """删除模板端点（DELETE /api/v1/agent-templates/{template_id}）."""

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_delete_success(self, mock_get_svc: MagicMock) -> None:
        """删除成功 → 204 空响应体."""
        svc = _mock_svc(mock_get_svc)
        svc.delete = AsyncMock(return_value=None)

        response = client.delete("/api/v1/agent-templates/3")
        assert response.status_code == 204
        assert response.content == b""
        svc.delete.assert_awaited_once_with(3)

    @patch("inkflow.api.routers.agent_templates._get_service")
    def test_delete_default_template_409(self, mock_get_svc: MagicMock) -> None:
        """默认/内置模板删除 → 409「默认模板不可删除」."""
        svc = _mock_svc(mock_get_svc)
        svc.delete = AsyncMock(side_effect=AgentTemplateBuiltinError())

        response = client.delete("/api/v1/agent-templates/1")
        assert response.status_code == 409
        assert response.json()["detail"] == "默认模板不可删除"
