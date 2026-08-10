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

依据: specs/f19-gui/spec.md §9.2.5。
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
