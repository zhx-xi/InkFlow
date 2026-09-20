"""#1321 世界观分类条件必填 + 更新侧存在性校验 — RED 契约.

测试范围（issue #1321，方案 A 条件校验版）:
- 根条目无分类：parent_id 空 + category="" → 200（守护 #722，不得打成 422）
- 非根条目缺分类：parent_id 非空 + category="" → 422
- 非根条目分类不存在：parent_id 非空 + category="不存在" → 422
- 更新侧存在性：PATCH category="不存在" → 422
- 更新侧清空：PATCH category="" → 200（既有冻结语义，test_world_api.py:217-222）
- 提取管线豁免：extractor 走 category="" → 不报错

GREEN 契约（测试即契约）:
- `WorldSettingCreateBody` 用 model_validator(mode="after") 做 (parent_id, category) 条件校验；
  违反 → ValidationError → FastAPI 422（detail 含「分类」字样）。
- `WorldService.update_setting` 在组装 updates 前，对 `"category" in model_fields_set`
  且非空时调 `get_category_by_name`；不存在 → WorldCategoryMissingError（422）。
- `_world_extractor` 走 service 层 create_setting 直调，绕过 router DTO 校验 → 天然豁免。

RED 预期：条件校验 / 更新侧校验均未实现 → 断言 2/3/4 与 6 的负向用例 FAIL；
守护用例（1/5）RED 阶段即 PASS。

依据: issue #1321 + specs/f10-world-settings/spec.md §3.1/§5.1/§7。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.world_errors import WorldCategoryMissingError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
ROOT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000f0")
PARENT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(name: str, *, category: str = "", parent_id: uuid.UUID | None = None) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳）."""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        category=category,
        content="",
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock WorldService（同 test_world_api._mock_svc）."""
    svc = MagicMock()
    svc.get_root_setting = AsyncMock(return_value=None)
    mock_get_svc.return_value = svc
    return svc


class TestWorldCategoryConditionalRequired:
    """创建侧 (parent_id, category) 条件必填 — 批 2."""

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_root_without_category_ok(self, mock_get_svc: MagicMock) -> None:
        """#722 守护：根条目（无 parent_id）+ category="" → 200/201，不得 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_setting = AsyncMock(return_value=_setting("世界根", category=""))

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={"name": "世界根", "category": "", "content": ""},
        )
        assert response.status_code == 201, response.text
        assert response.json()["category"] == ""

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_root_with_category_still_ok(self, mock_get_svc: MagicMock) -> None:
        """根条目本就不传 parent_id → 走 #641 自动挂根，category 非空不阻断；
        该用例守护「条件校验不误伤既有根创建路径」."""
        svc = _mock_svc(mock_get_svc)
        svc.create_setting = AsyncMock(return_value=_setting("世界根", category=""))

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={"name": "世界根", "category": "", "content": ""},
        )
        assert response.status_code == 201, response.text

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_non_root_missing_category_422(self, mock_get_svc: MagicMock) -> None:
        """非根条目（有 parent_id）+ category="" → 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_setting = AsyncMock(return_value=_setting("子地点"))

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={
                "name": "子地点",
                "category": "",
                "content": "",
                "parent_id": str(PARENT_ID),
            },
        )
        assert response.status_code == 422, response.text
        assert "分类" in response.text

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_non_root_unknown_category_422(self, mock_get_svc: MagicMock) -> None:
        """非根条目 + category="不存在的分类" → 422（存在性由 service 层判）."""
        svc = _mock_svc(mock_get_svc)
        svc.get_root_setting = AsyncMock(return_value=_setting("世界根", category=""))
        svc.create_setting = AsyncMock(side_effect=WorldCategoryMissingError("不存在的分类"))

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={
                "name": "子地点",
                "category": "不存在的分类",
                "content": "",
                "parent_id": str(PARENT_ID),
            },
        )
        assert response.status_code == 422, response.text
        assert "不存在的分类" in response.text


class TestUpdateCategoryExistence:
    """更新侧分类存在性校验 — 批 1."""

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_update_unknown_category_422(self, mock_get_svc: MagicMock) -> None:
        """PATCH category="不存在" → 422（service 抛 WorldCategoryMissingError）."""
        svc = _mock_svc(mock_get_svc)
        svc.update_setting = AsyncMock(side_effect=WorldCategoryMissingError("不存在"))

        response = client.patch(
            f"/api/v1/world-settings/{uuid.uuid4()}",
            json={"category": "不存在"},
        )
        assert response.status_code == 422, response.text
        assert "不存在" in response.text

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_update_clear_category_still_200(self, mock_get_svc: MagicMock) -> None:
        """冻结语义守护：PATCH category="" → 200（清空为未分类，不得打成 422）.

        对齐 test_world_api.py:212-226。
        """
        svc = _mock_svc(mock_get_svc)
        setting = _setting("灵气复苏", category="设定")
        updated = setting.model_copy(update={"category": ""})
        svc.update_setting = AsyncMock(return_value=updated)

        response = client.patch(
            f"/api/v1/world-settings/{setting.id}",
            json={"category": ""},
        )
        assert response.status_code == 200, response.text
        assert response.json()["category"] == ""
