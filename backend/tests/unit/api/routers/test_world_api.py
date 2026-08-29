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

依据: specs/f10-world-settings/spec.md §3 + §7 + §9。

F35 追加段（#173 地点层级，spec §3.1/§3.3 契约）:
- create body 新增 parent_id → create_setting 收到 parent_id=<uuid> 关键字参数
- list 新增 ?parent_id=<uuid>（直接子级）/ ?parent_id=none（顶层）→ list_settings
  收到 parent_id=<uuid> / (parent_id=None, top_level_only=True)
- GET /world-settings/{sid}/ancestors|descendants → {"items", "total"}
  （ancestors 自身在前；descendants 层序）；service 返回 None → 404「世界观条目不存在」
- PATCH {"parent_id": null} → update.model_fields_set 含 parent_id（置顶语义，
  spec §2.2 exclude_unset 区分）；未传 parent_id → 不含（不修改父级）
- DELETE ?cascade=true → delete_setting(sid, cascade=True, reparent_to=None)；
  ?reparent_to=<uuid> → reparent_to=<uuid>
- 新错误类（WorldParentNotFoundError / WorldCycleError / WorldChildrenActionRequiredError /
  WorldReparentTargetError，继承 WorldServiceError → 422），detail 文案精确匹配 spec §3.3；
  RED 阶段未实现 → 用例体内惰性 import（ImportError = 预期失败点，不影响既有用例收集）
- RED 预期（追加段）: 新端点用例 404 断言 FAIL；create parent_id / list 过滤 / DELETE
  参数 / PATCH 置顶 / 新错误类用例 FAIL；test_update_setting_without_parent_id 为守护
  用例，RED 阶段即 PASS（既有 exclude_unset 语义已满足）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
PARENT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")  # F35: 父地点
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
    # #641：router create_world_setting 对 body 无 parent_id 先查 get_root_setting——
    # 既有用例不配置该属性会命中 MagicMock 自动子 mock（非 awaitable）→ TypeError。
    # 默认无根（None）使既有创建用例正常走到 create_setting（建根/挂根）；根单例用例显式覆盖。
    svc.get_root_setting = AsyncMock(return_value=None)
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
    def test_update_setting_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """F35 补测: PATCH 条目不存在（update_setting 返回 None）→ 404「世界观条目不存在」
        （world_settings.py L259-260 的 `if setting is None` 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.update_setting = AsyncMock(return_value=None)

        response = client.patch(
            f"/api/v1/world-settings/{uuid.uuid4()}", json={"name": "清河县城·改"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "世界观条目不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_204(self, mock_get_svc: MagicMock) -> None:
        """删除条目返回 204（v1.1 真删，无 force 参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(return_value=True)

        setting_id = uuid.uuid4()
        response = client.delete(f"/api/v1/world-settings/{setting_id}")
        assert response.status_code == 204
        svc.delete_setting.assert_awaited_once_with(setting_id)

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的条目返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/world-settings/{uuid.uuid4()}")
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


# ══════════════════════════════════════════════════════════════════════════
# #177 覆盖率盲区补测: 直接调用 _run_service（不经 TestClient）
# coverage.py 对 TestClient（portal 线程）内异常传播路径的 except 块存在统计
# 盲区——测试执行了分支但 coverage 不记录；直接调用 router 模块函数可正常记录。
# ══════════════════════════════════════════════════════════════════════════


async def _raise(exc: Exception) -> None:
    """辅助: 抛异常（作为 _run_service 的 coro 参数）。"""
    raise exc


class TestRunServiceExceptBranch:
    """直接调用 _run_service 触发 except 分支（#177 补测）。"""

    async def test_run_service_world_not_found_404(self) -> None:
        """WorldNotFoundError → HTTPException 404，detail 透传消息
        （world_settings.py L76）."""
        from fastapi import HTTPException

        from inkflow.api.routers.world_settings import _run_service
        from inkflow.domain.ports.world_errors import WorldNotFoundError

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(WorldNotFoundError("x")))
        assert ei.value.status_code == 404
        assert "x" in ei.value.detail


# ══════════════════════════════════════════════════════════════════════════
# F35 地点层级追加段（#173）: parent_id / ancestors / descendants / PATCH 置顶 /
# DELETE cascade/reparent_to / 列表过滤 / 新错误映射 —— 契约见文件头 docstring
# ══════════════════════════════════════════════════════════════════════════


class TestWorldLocationTreeAPI:
    """F35 世界观地点层级 API 契约（spec §3.1/§3.3，追加段）。"""

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_setting_with_parent_id(self, mock_get_svc: MagicMock) -> None:
        """F35: create body 带 parent_id → 201 + create_setting 收到 parent_id 关键字.

        RED 预期: 当前 router 调 create_setting(pid, name, category, content)
        无 parent_id 关键字 → assert_awaited_once_with 断言失败。
        """
        svc = _mock_svc(mock_get_svc)
        setting = _setting("清河县城")
        svc.create_setting = AsyncMock(return_value=setting)

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={
                "name": "清河县城",
                "category": "地理",
                "content": "青州辖下县城。",
                "parent_id": str(PARENT_ID),
            },
        )
        assert response.status_code == 201
        assert response.json()["name"] == "清河县城"
        svc.create_setting.assert_awaited_once_with(
            PID, "清河县城", "地理", "青州辖下县城。", parent_id=PARENT_ID
        )

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_list_settings_parent_id_filter(self, mock_get_svc: MagicMock) -> None:
        """F35: GET ?parent_id=<uuid> → list_settings 收到 parent_id=<uuid>（直接子级，spec §7 #16）
        ."""
        svc = _mock_svc(mock_get_svc)
        svc.list_settings = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/world-settings", params={"parent_id": str(PARENT_ID)}
        )
        assert response.status_code == 200
        svc.list_settings.assert_awaited_once_with(
            PID,
            search=None,
            category=None,
            sort_by="updated_at",
            sort_desc=True,
            offset=0,
            limit=50,
            parent_id=PARENT_ID,
        )

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_list_settings_top_level_only(self, mock_get_svc: MagicMock) -> None:
        """F35: GET ?parent_id=none → list_settings 收到 top_level_only=True +
        parent_id=None（顶层）."""
        svc = _mock_svc(mock_get_svc)
        svc.list_settings = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/world-settings", params={"parent_id": "none"}
        )
        assert response.status_code == 200
        svc.list_settings.assert_awaited_once_with(
            PID,
            search=None,
            category=None,
            sort_by="updated_at",
            sort_desc=True,
            offset=0,
            limit=50,
            parent_id=None,
            top_level_only=True,
        )

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_get_ancestors_success(self, mock_get_svc: MagicMock) -> None:
        """F35: GET /world-settings/{sid}/ancestors → 200 {items, total}（自身在前，spec §3.1）.

        RED 预期: 路由未注册 → 404 → status_code 断言失败。
        """
        svc = _mock_svc(mock_get_svc)
        child = _setting("清河县城")
        parent = _setting("青州")
        svc.list_ancestors = AsyncMock(return_value=[child, parent])

        response = client.get(f"/api/v1/world-settings/{child.id}/ancestors")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["items"][0]["name"] == "清河县城"
        assert data["items"][1]["name"] == "青州"
        svc.list_ancestors.assert_awaited_once_with(child.id)

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_get_ancestors_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """F35: list_ancestors 返回 None → 404「世界观条目不存在」.

        RED 预期: 路由未注册 → 404 但 detail 为 FastAPI 默认 "Not Found"
        → detail 断言失败（证明路由缺失，非 404 语义错误）。
        """
        svc = _mock_svc(mock_get_svc)
        svc.list_ancestors = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/world-settings/{uuid.uuid4()}/ancestors")
        assert response.status_code == 404
        assert response.json()["detail"] == "世界观条目不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_get_descendants_success(self, mock_get_svc: MagicMock) -> None:
        """F35: GET /world-settings/{sid}/descendants → 200 {items, total}（层序，spec §3.1）.

        RED 预期: 路由未注册 → 404 → status_code 断言失败。
        """
        svc = _mock_svc(mock_get_svc)
        child = _setting("清河县城")
        parent = _setting("青州")
        svc.list_descendants = AsyncMock(return_value=[parent, child])

        response = client.get(f"/api/v1/world-settings/{parent.id}/descendants")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["items"][0]["name"] == "青州"
        assert data["items"][1]["name"] == "清河县城"
        svc.list_descendants.assert_awaited_once_with(parent.id)

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_get_descendants_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """F35: list_descendants 返回 None → 404「世界观条目不存在」.

        RED 预期: 路由未注册 → detail 为 "Not Found" → detail 断言失败。
        """
        svc = _mock_svc(mock_get_svc)
        svc.list_descendants = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/world-settings/{uuid.uuid4()}/descendants")
        assert response.status_code == 404
        assert response.json()["detail"] == "世界观条目不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_update_setting_parent_id_null_promotes(self, mock_get_svc: MagicMock) -> None:
        """F35: PATCH {"parent_id": null} → update 收到 WorldUpdate 且 model_fields_set 含
        parent_id（置顶）.

        RED 预期: 当前 WorldUpdate 无 parent_id 字段（extra 忽略）→ fields_set 为空
        → "parent_id" in fields_set 断言失败。
        """
        svc = _mock_svc(mock_get_svc)
        setting = _setting("清河县城")
        svc.update_setting = AsyncMock(return_value=setting)

        response = client.patch(f"/api/v1/world-settings/{setting.id}", json={"parent_id": None})
        assert response.status_code == 200
        svc.update_setting.assert_awaited_once()
        args, kwargs = svc.update_setting.await_args
        update = args[1] if len(args) > 1 else kwargs["update"]
        assert "parent_id" in update.model_fields_set
        assert update.parent_id is None

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_update_setting_without_parent_id(self, mock_get_svc: MagicMock) -> None:
        """F35 守护: PATCH 未传 parent_id → model_fields_set 不含 parent_id（不修改父级）.

        RED 阶段即 PASS（既有 exclude_unset 语义已满足）——防 GREEN 误加字段的守护契约。
        """
        svc = _mock_svc(mock_get_svc)
        setting = _setting("清河县城")
        svc.update_setting = AsyncMock(return_value=setting)

        response = client.patch(
            f"/api/v1/world-settings/{setting.id}", json={"name": "清河县城·改"}
        )
        assert response.status_code == 200
        args, kwargs = svc.update_setting.await_args
        update = args[1] if len(args) > 1 else kwargs["update"]
        assert "parent_id" not in update.model_fields_set

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_cascade_param(self, mock_get_svc: MagicMock) -> None:
        """F35: DELETE ?cascade=true → delete_setting 收到 (sid, cascade=True, reparent_to=None)."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(return_value=True)

        setting_id = uuid.uuid4()
        response = client.delete(f"/api/v1/world-settings/{setting_id}?cascade=true")
        assert response.status_code == 204
        svc.delete_setting.assert_awaited_once_with(setting_id, cascade=True, reparent_to=None)

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_reparent_to_param(self, mock_get_svc: MagicMock) -> None:
        """F35: DELETE ?reparent_to=<uuid> → delete_setting 收到 reparent_to=<uuid>."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(return_value=True)

        setting_id = uuid.uuid4()
        response = client.delete(f"/api/v1/world-settings/{setting_id}?reparent_to={PARENT_ID}")
        assert response.status_code == 204
        svc.delete_setting.assert_awaited_once_with(
            setting_id, cascade=False, reparent_to=PARENT_ID
        )

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_setting_children_action_required_422(self, mock_get_svc: MagicMock) -> None:
        """F35: 有子地点 DELETE 无参数 → 422 + detail 精确匹配（spec §3.2 示例文案）.

        惰性 import: WorldChildrenActionRequiredError 尚未实现，RED 阶段
        ImportError = 预期失败点（不影响既有用例收集）。
        """
        from inkflow.domain.ports.world_errors import WorldChildrenActionRequiredError

        svc = _mock_svc(mock_get_svc)
        svc.delete_setting = AsyncMock(side_effect=WorldChildrenActionRequiredError())

        detail = (
            "该地点存在子地点，必须指定 cascade=true（级联删除）或 "
            "reparent_to=<id>（子地点改挂新父）"
        )
        response = client.delete(f"/api/v1/world-settings/{uuid.uuid4()}")
        assert response.status_code == 422
        assert response.json()["detail"] == detail

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_f35_new_error_mapping_422(self, mock_get_svc: MagicMock) -> None:
        """F35 新错误类 → 422 + detail 精确匹配 spec §3.3（父不存在/循环/reparent 目标非法）.

        惰性 import: 三错误类尚未实现，RED 阶段 ImportError = 预期失败点。
        """
        from inkflow.domain.ports.world_errors import (
            WorldCycleError,
            WorldParentNotFoundError,
            WorldReparentTargetError,
        )

        svc = _mock_svc(mock_get_svc)
        svc.create_setting = AsyncMock(side_effect=[WorldParentNotFoundError(), WorldCycleError()])
        svc.delete_setting = AsyncMock(side_effect=WorldReparentTargetError())

        resp1 = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={"name": "清河县城", "parent_id": str(PARENT_ID)},
        )
        assert resp1.status_code == 422
        assert resp1.json()["detail"] == "父地点不存在或不在同一项目"

        resp2 = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={"name": "清河县城", "parent_id": str(PARENT_ID)},
        )
        assert resp2.status_code == 422
        assert resp2.json()["detail"] == "不能将地点挂接到自身或其子孙下"

        resp3 = client.delete(f"/api/v1/world-settings/{uuid.uuid4()}?reparent_to={PARENT_ID}")
        assert resp3.status_code == 422
        assert resp3.json()["detail"] == "reparent 目标地点不存在/不在同一项目/是自身子树"


class TestWorldRootSingletonAPI:
    """#641 世界观根条目单例 + 自动挂根（方案 1 后端），复写 #567（一项目一根）。

    契约（实现者以本文件为准）:
    - 服务新增方法: get_root_setting(project_id: uuid.UUID) -> WorldSetting | None
      （repo.list top_level_only=True limit=1 取根；无根返回 None）——上游已存在
      has_root_setting（保留）。
    - create_world_setting 内（body 未传 parent_id，即 parent_id=None）:
      * 已有根 → get_root_setting(pid) 返回根实体 → create_setting(pid, name, category,
        content, parent_id=根.id) → 201（自动挂到根下，不再 422「该项目已存在世界观根条目」）
      * 无根 → get_root_setting(pid) 返回 None → create_setting(pid, name, category,
        content) → 201（创建根）
    - body 带 parent_id（显式子节点）不受单例限制 → create_setting 带 parent_id → 201。

    RED 预期: 当前 router 对 parent_id 为空走 has_root_setting → 根存在时 422 →
    test_create_with_root_auto_attach_201 断言失败；get_root_setting 未在 mock 上
    配置时 MagicMock 自动建子 mock（truthy）会误判有根——本类用例均显式配置。
    """

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_with_root_auto_attach_201(self, mock_get_svc: MagicMock) -> None:
        """已有根条目时建「分类下条目」（body 无 parent_id）→ 201 + 自动挂根（parent_id=根.id）。

        RED 预期: 当前 router 对无 parent_id 走 has_root_setting → 根存在 → 422 →
        status_code 断言失败。
        """
        svc = _mock_svc(mock_get_svc)
        root = _setting("世界观", project_id=PID)
        new_setting = _setting("清河县城", project_id=PID)
        svc.get_root_setting = AsyncMock(return_value=root)
        svc.create_setting = AsyncMock(return_value=new_setting)

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={"name": "清河县城", "category": "门派"},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "清河县城"
        svc.get_root_setting.assert_awaited_once_with(PID)
        svc.create_setting.assert_awaited_once_with(PID, "清河县城", "门派", "", parent_id=root.id)

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_root_when_no_root_201(self, mock_get_svc: MagicMock) -> None:
        """无根条目时建根（body 无 parent_id）→ 201（get_root_setting 返回 None）。"""
        svc = _mock_svc(mock_get_svc)
        setting = _setting("世界观")
        svc.get_root_setting = AsyncMock(return_value=None)
        svc.create_setting = AsyncMock(return_value=setting)

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={"name": "世界观"},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "世界观"
        svc.get_root_setting.assert_awaited_once_with(PID)
        svc.create_setting.assert_awaited_once_with(PID, "世界观", "", "")

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_child_when_root_exists_201(self, mock_get_svc: MagicMock) -> None:
        """已有根条目时建显式子节点（body 带 parent_id）→ 201 不受单例限制。"""
        svc = _mock_svc(mock_get_svc)
        setting = _setting("清河县城")
        svc.get_root_setting = AsyncMock(return_value=_setting("世界观", project_id=PID))
        svc.create_setting = AsyncMock(return_value=setting)

        response = client.post(
            f"/api/v1/projects/{PID}/world-settings",
            json={"name": "清河县城", "parent_id": str(PARENT_ID)},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "清河县城"
        svc.get_root_setting.assert_not_awaited()
        svc.create_setting.assert_awaited_once_with(PID, "清河县城", "", "", parent_id=PARENT_ID)
