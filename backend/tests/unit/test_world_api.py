"""F10 世界观管理 API 测试 — Mock Service 层（M5 RED→GREEN）.

测试范围 (spec §9 API 测试 + §3.4 异常映射表):
- 8 端点成功路径（201/200/204）
- 404 全路径（项目/条目不存在、无效 UUID → 404）
- 422 业务校验（同名条目 → 422）
- extract 200 / extract LLM 失败 → 500 / 解析失败 → 500
- categories 汇总端点
- 分页参数校验（limit 越界 → 422）

策略: @patch("inkflow.api.routers.world_settings.get_world_service")
整体替换 Service 获取函数（router 模块级本地引用），每个被路由 await 的
服务方法显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await 会
返回 coroutine 导致 500（F4 4.1 实测陷阱）。

依据: specs/f10-world-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.world import WorldExtractionResult, WorldSetting
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.world_errors import (
    ProjectNotFoundError,
    WorldExtractionError,
    WorldNameConflictError,
)

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(name: str, *, project_id: uuid.UUID = PID) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳，便于断言）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category="设定",
        content="公元 2048 年全球灵气浓度回升。",
        created_at=TS,
        updated_at=TS,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock WorldService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestWorldSettingCRUDAPI:
    """世界观条目 CRUD 端点测试."""

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_setting_success(self, mock_get_svc: MagicMock) -> None:
        """创建条目返回 201 + WorldSetting JSON."""
        svc = _mock_svc(mock_get_svc)
        setting = _setting("灵气复苏")
        svc.create_setting = AsyncMock(return_value=setting)

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={
                "name": "灵气复苏",
                "category": "设定",
                "content": "公元 2048 年全球灵气浓度回升。",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "灵气复苏"
        assert data["category"] == "设定"
        assert data["project_id"] == str(PID)
        assert data["is_deleted"] is False
        svc.create_setting.assert_awaited_once_with(
            PID, "灵气复苏", "设定", "公元 2048 年全球灵气浓度回升。"
        )

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_setting_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名活动条目创建返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_setting = AsyncMock(side_effect=WorldNameConflictError())

        response = client.post(f"/api/v1/projects/{PID}/world-settings", json={"name": "灵气复苏"})
        assert response.status_code == 422
        assert response.json()["detail"] == "同名世界观条目已存在（条目名在项目内必须唯一）"

    def test_create_setting_missing_name_422(self) -> None:
        """缺少必填字段 name 返回 422（Pydantic 校验）."""
        response = client.post(f"/api/v1/projects/{PID}/world-settings", json={"category": "设定"})
        assert response.status_code == 422

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_list_settings_success(self, mock_get_svc: MagicMock) -> None:
        """条目列表返回 200 + {items, total, offset, limit}."""
        svc = _mock_svc(mock_get_svc)
        setting = _setting("灵气复苏")
        svc.list_settings = AsyncMock(return_value=([setting], 1))

        response = client.get(
            f"/api/v1/projects/{PID}/world-settings",
            params={
                "search": "灵气",
                "category": "设定",
                "sort_by": "name",
                "sort_desc": "false",
                "offset": 0,
                "limit": 20,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 20
        assert data["items"][0]["name"] == "灵气复苏"
        svc.list_settings.assert_awaited_once_with(
            PID,
            search="灵气",
            category="设定",
            sort_by="name",
            sort_desc=False,
            offset=0,
            limit=20,
        )

    def test_list_settings_invalid_pagination_422(self) -> None:
        """分页参数越界（limit=0）返回 422."""
        response = client.get(f"/api/v1/projects/{PID}/world-settings", params={"limit": 0})
        assert response.status_code == 422

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_list_categories_success(self, mock_get_svc: MagicMock) -> None:
        """类别汇总返回 200 + {items, total}（count 降序、category 升序）."""
        svc = _mock_svc(mock_get_svc)
        svc.list_categories = AsyncMock(return_value=[("设定", 4), ("规则", 3)])

        response = client.get(f"/api/v1/projects/{PID}/world-settings/categories")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["items"][0] == {"category": "设定", "count": 4}
        assert data["items"][1] == {"category": "规则", "count": 3}
        svc.list_categories.assert_awaited_once_with(PID)

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_get_setting_success(self, mock_get_svc: MagicMock) -> None:
        """条目详情返回 200 + WorldSetting JSON."""
        svc = _mock_svc(mock_get_svc)
        setting = _setting("灵气复苏")
        svc.get_setting = AsyncMock(return_value=setting)

        response = client.get(f"/api/v1/world-settings/{setting.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "灵气复苏"
        assert data["category"] == "设定"
        assert data["project_id"] == str(PID)

    def test_get_setting_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404."""
        response = client.get("/api/v1/world-settings/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "世界观条目不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_get_setting_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """条目不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.get_setting = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/world-settings/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "世界观条目不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_update_setting_success(self, mock_get_svc: MagicMock) -> None:
        """更新条目返回 200 + WorldSetting JSON."""
        svc = _mock_svc(mock_get_svc)
        setting = _setting("灵气复苏")
        updated = setting.model_copy(update={"content": "（修订版内容……）", "category": ""})
        svc.update_setting = AsyncMock(return_value=updated)

        response = client.patch(
            f"/api/v1/world-settings/{setting.id}",
            json={"content": "（修订版内容……）", "category": ""},
        )
        assert response.status_code == 200
        assert response.json()["content"] == "（修订版内容……）"
        assert response.json()["category"] == ""

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_soft_204(self, mock_get_svc: MagicMock) -> None:
        """软删除条目返回 204（默认 force=False）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(return_value=True)

        setting_id = uuid.uuid4()
        response = client.delete(f"/api/v1/world-settings/{setting_id}")
        assert response.status_code == 204
        svc.delete_setting.assert_awaited_once_with(setting_id, force=False)

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_force_204(self, mock_get_svc: MagicMock) -> None:
        """硬删除条目返回 204（?force=true 透传）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(return_value=True)

        response = client.delete(f"/api/v1/world-settings/{uuid.uuid4()}?force=true")
        assert response.status_code == 204
        svc.delete_setting.assert_awaited_once()
        _, kwargs = svc.delete_setting.await_args
        assert kwargs["force"] is True

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的条目返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/world-settings/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "世界观条目不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_restore_setting_success(self, mock_get_svc: MagicMock) -> None:
        """恢复条目返回 200 + WorldSetting JSON."""
        svc = _mock_svc(mock_get_svc)
        setting = _setting("灵气复苏")
        svc.restore_setting = AsyncMock(return_value=setting)

        response = client.post(f"/api/v1/world-settings/{setting.id}/restore")
        assert response.status_code == 200
        assert response.json()["name"] == "灵气复苏"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_restore_setting_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """恢复不存在的条目返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.restore_setting = AsyncMock(return_value=None)

        response = client.post(f"/api/v1/world-settings/{uuid.uuid4()}/restore")
        assert response.status_code == 404
        assert response.json()["detail"] == "世界观条目不存在"


class TestExtractAPI:
    """AI 提取端点测试."""

    def _extract_result(self) -> WorldExtractionResult:
        return WorldExtractionResult(
            created=[_setting("灵气复苏")],
            updated=[],
            warnings=[],
            model="openai/gpt-4o",
        )

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_extract_success(self, mock_get_svc: MagicMock) -> None:
        """AI 提取返回 200 + WorldExtractionResult JSON."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(return_value=self._extract_result())

        response = client.post(
            "/api/v1/world-settings/extract",
            json={"project_id": str(PID), "text": "公元 2048 年灵气复苏，觉醒者出现。"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "openai/gpt-4o"
        assert len(data["created"]) == 1
        assert data["created"][0]["name"] == "灵气复苏"
        assert "warnings" in data

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_extract_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """提取时项目不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            "/api/v1/world-settings/extract",
            json={"project_id": str(PID), "text": "公元 2048 年灵气复苏。"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_extract_llm_failure_500(self, mock_get_svc: MagicMock) -> None:
        """LLM 调用失败返回 500."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=LLMRequestError("LLM 调用失败", retries_exhausted=True))

        response = client.post(
            "/api/v1/world-settings/extract",
            json={"project_id": str(PID), "text": "公元 2048 年灵气复苏。"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "LLM 调用失败，请稍后重试"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_extract_parse_failure_500(self, mock_get_svc: MagicMock) -> None:
        """LLM 输出无法解析（重试后仍失败）返回 500."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=WorldExtractionError())

        response = client.post(
            "/api/v1/world-settings/extract",
            json={"project_id": str(PID), "text": "公元 2048 年灵气复苏。"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "世界观提取失败: LLM 输出无法解析，请重试"
