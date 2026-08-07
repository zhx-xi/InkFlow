"""F13 伏笔管理 API 测试 — Mock Service 层（M5 RED→GREEN）。

测试范围 (spec §9 API 测试 + §3.4 异常映射表):
- 8 端点成功路径（201/200/204）
- 404 全路径（项目/伏笔不存在、无效 UUID → 404）
- 422 业务校验（同名冲突、event_id 不存在/跨项目、仓储未配置）
- resolve/reopen 响应（resolved_at 设置与清空）与幂等动作
- 列表 Query 参数透传（search/status/sort_by/sort_desc/offset/limit）

策略: @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
整体替换 Service 获取函数（router 模块级本地引用），每个被路由 await 的
服务方法显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await 会
返回 coroutine 导致 500（F4 4.1 实测陷阱）。

依据: specs/f13-foreshadowing-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingStatus
from inkflow.domain.ports.foreshadowing_errors import (
    EventNotFoundError,
    EventNotInProjectError,
    ForeshadowingNameConflictError,
    ForeshadowingServiceError,
    ProjectNotFoundError,
)

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
RESOLVED_TS = datetime(2026, 8, 10, 3, 0, 0, tzinfo=UTC)


def _foreshadowing(title: str, **overrides: object) -> Foreshadowing:
    """构造测试用伏笔实体（固定时间戳，便于断言）。"""
    kwargs: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "title": title,
        "description": "林晚右肩的胎记与女主母亲的信物相同；预期第 30 章前后揭露。",
        "priority": 80,
        "status": ForeshadowingStatus.OPEN,
        "location": "第 5 章·林晚沐浴场景",
        "event_id": None,
        "resolved_at": None,
        "extra": {},
        "is_deleted": False,
        "created_at": TS,
        "updated_at": TS,
    }
    kwargs.update(overrides)
    return Foreshadowing(**kwargs)  # type: ignore[arg-type]  # kwargs 为动态 dict，无法静态匹配构造器参数签名


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock ForeshadowingService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestForeshadowingAPI:
    """伏笔 API 端点测试."""

    # ── 创建（嵌套项目路径）──────────────────────────────────

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_create_foreshadowing_success(self, mock_get_svc: MagicMock) -> None:
        """创建伏笔返回 201 + Foreshadowing JSON（默认 status=open）。"""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing("林晚的身世")
        svc.create = AsyncMock(return_value=foreshadowing)

        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={
                "title": "林晚的身世",
                "description": "林晚右肩的胎记与女主母亲的信物相同；预期第 30 章前后揭露。",
                "priority": 80,
                "location": "第 5 章·林晚沐浴场景",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "林晚的身世"
        assert data["project_id"] == str(PID)
        assert data["status"] == "open"
        assert data["priority"] == 80
        assert data["event_id"] is None
        assert data["is_deleted"] is False
        svc.create.assert_awaited_once()
        args, _ = svc.create.await_args
        assert args[0].project_id == PID
        assert args[0].title == "林晚的身世"
        assert args[0].event_id is None

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_create_with_event_id_success(self, mock_get_svc: MagicMock) -> None:
        """创建伏笔挂接 F12 事件：event_id 透传到服务层 DTO。"""
        svc = _mock_svc(mock_get_svc)
        event_id = uuid.uuid4()
        svc.create = AsyncMock(return_value=_foreshadowing("林晚的身世", event_id=event_id))

        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "林晚的身世", "event_id": str(event_id)},
        )
        assert response.status_code == 201
        assert response.json()["event_id"] == str(event_id)
        svc.create.assert_awaited_once()
        args, _ = svc.create.await_args
        assert args[0].event_id == event_id

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_create_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """创建伏笔时项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "林晚的身世"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_create_invalid_project_uuid_404(self) -> None:
        """无效项目 UUID 格式返回 404「项目不存在」."""
        response = client.post(
            "/api/v1/projects/not-a-uuid/foreshadowings",
            json={"title": "林晚的身世"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_create_blank_title_422(self) -> None:
        """伏笔名为空白返回 422（Pydantic 校验）."""
        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "   "},
        )
        assert response.status_code == 422
        assert "伏笔名不能为空" in response.text

    def test_create_priority_out_of_range_422(self) -> None:
        """优先级越界（101）返回 422."""
        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "林晚的身世", "priority": 101},
        )
        assert response.status_code == 422
        assert "优先级必须在 0-100 之间" in response.text

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_create_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名活动伏笔返回 422（spec §3.4 逐字文案）."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(side_effect=ForeshadowingNameConflictError())

        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "林晚的身世"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "同名伏笔已存在（伏笔名在项目内必须唯一）"

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_create_event_not_found_422(self, mock_get_svc: MagicMock) -> None:
        """event_id 指向不存在的事件（含已软删）返回 422「事件不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(side_effect=EventNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "林晚的身世", "event_id": str(uuid.uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "事件不存在"

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_create_event_not_in_project_422(self, mock_get_svc: MagicMock) -> None:
        """event_id 指向其他项目的事件返回 422「事件不属于该项目」."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(side_effect=EventNotInProjectError())

        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "林晚的身世", "event_id": str(uuid.uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "事件不属于该项目"

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_create_service_config_error_422(self, mock_get_svc: MagicMock) -> None:
        """仓储未注入等配置错误返回 422（消息即 detail）."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(
            side_effect=ForeshadowingServiceError("时间线仓储未配置，无法校验事件锚点")
        )

        response = client.post(
            f"/api/v1/projects/{PID}/foreshadowings",
            json={"title": "林晚的身世"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "时间线仓储未配置，无法校验事件锚点"

    # ── 列表（嵌套项目路径）──────────────────────────────────

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_list_foreshadowings_success(self, mock_get_svc: MagicMock) -> None:
        """伏笔列表返回 200 + {items, total, offset, limit}（Query 参数透传）."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing("林晚的身世")
        svc.list = AsyncMock(return_value=([foreshadowing], 1))

        response = client.get(
            f"/api/v1/projects/{PID}/foreshadowings",
            params={
                "search": "身世",
                "status": "open",
                "sort_by": "priority",
                "sort_desc": "true",
                "offset": 0,
                "limit": 20,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 20
        assert data["items"][0]["title"] == "林晚的身世"
        svc.list.assert_awaited_once_with(
            PID,
            search="身世",
            status="open",
            sort_by="priority",
            sort_desc=True,
            offset=0,
            limit=20,
        )

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_list_foreshadowings_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """列表时项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.list = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.get(f"/api/v1/projects/{PID}/foreshadowings")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_list_foreshadowings_invalid_pagination_422(self) -> None:
        """分页参数越界（limit=0）返回 422."""
        response = client.get(
            f"/api/v1/projects/{PID}/foreshadowings",
            params={"limit": 0},
        )
        assert response.status_code == 422

    # ── 详情（扁平路径）──────────────────────────────────────

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_get_foreshadowing_success(self, mock_get_svc: MagicMock) -> None:
        """伏笔详情返回 200 + Foreshadowing JSON."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing("林晚的身世")
        svc.get = AsyncMock(return_value=foreshadowing)

        response = client.get(f"/api/v1/foreshadowings/{foreshadowing.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(foreshadowing.id)
        assert data["title"] == "林晚的身世"
        assert data["project_id"] == str(PID)
        svc.get.assert_awaited_once_with(foreshadowing.id)

    def test_get_foreshadowing_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404「伏笔不存在」."""
        response = client.get("/api/v1/foreshadowings/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "伏笔不存在"

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_get_foreshadowing_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """伏笔不存在返回 404「伏笔不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/foreshadowings/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "伏笔不存在"

    # ── 更新（扁平路径）──────────────────────────────────────

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_update_foreshadowing_success(self, mock_get_svc: MagicMock) -> None:
        """更新伏笔返回 200 + Foreshadowing JSON（location "" 清除语义透传）."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing("林晚的身世", priority=90, location="")
        svc.update = AsyncMock(return_value=foreshadowing)

        response = client.patch(
            f"/api/v1/foreshadowings/{foreshadowing.id}",
            json={"priority": 90, "location": ""},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == 90
        assert data["location"] == ""
        svc.update.assert_awaited_once()
        args, _ = svc.update.await_args
        assert args[0] == foreshadowing.id
        assert args[1].priority == 90
        assert args[1].location == ""  # "" 清除语义直接透传，由 service 处理

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_update_clear_event_id_success(self, mock_get_svc: MagicMock) -> None:
        """PATCH event_id "" 表示解除事件挂接（透传 str "" 给 service）."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing("林晚的身世", event_id=None)
        svc.update = AsyncMock(return_value=foreshadowing)

        response = client.patch(
            f"/api/v1/foreshadowings/{foreshadowing.id}",
            json={"event_id": ""},
        )
        assert response.status_code == 200
        assert response.json()["event_id"] is None
        svc.update.assert_awaited_once()
        args, _ = svc.update.await_args
        assert args[1].event_id == ""  # None/"" 双语义直接透传，由 service 处理

    def test_update_clear_event_id_nonempty_string_422(self) -> None:
        """解除事件挂接传非空字符串返回 422（spec §3.4 逐字文案）."""
        response = client.patch(
            f"/api/v1/foreshadowings/{uuid.uuid4()}",
            json={"event_id": "abc"},
        )
        assert response.status_code == 422
        assert "解除事件挂接请传空字符串" in response.text

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_update_foreshadowing_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的伏笔返回 404「伏笔不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.update = AsyncMock(return_value=None)

        response = client.patch(
            f"/api/v1/foreshadowings/{uuid.uuid4()}",
            json={"title": "改名"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "伏笔不存在"

    # ── 删除（扁平路径，force 两态）──────────────────────────

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_delete_foreshadowing_soft_204(self, mock_get_svc: MagicMock) -> None:
        """软删除伏笔返回 204（默认 force=False）."""
        svc = _mock_svc(mock_get_svc)
        svc.soft_delete = AsyncMock(return_value=True)
        svc.hard_delete = AsyncMock(return_value=True)

        foreshadowing_id = uuid.uuid4()
        response = client.delete(f"/api/v1/foreshadowings/{foreshadowing_id}")
        assert response.status_code == 204
        svc.soft_delete.assert_awaited_once_with(foreshadowing_id)
        svc.hard_delete.assert_not_awaited()

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_delete_foreshadowing_force_204(self, mock_get_svc: MagicMock) -> None:
        """硬删除伏笔返回 204（?force=true 透传）."""
        svc = _mock_svc(mock_get_svc)
        svc.soft_delete = AsyncMock(return_value=True)
        svc.hard_delete = AsyncMock(return_value=True)

        foreshadowing_id = uuid.uuid4()
        response = client.delete(f"/api/v1/foreshadowings/{foreshadowing_id}?force=true")
        assert response.status_code == 204
        svc.hard_delete.assert_awaited_once_with(foreshadowing_id)
        svc.soft_delete.assert_not_awaited()

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_delete_foreshadowing_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的伏笔返回 404「伏笔不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.soft_delete = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/foreshadowings/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "伏笔不存在"

    # ── restore / resolve / reopen（状态机动作）──────────────

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_restore_foreshadowing_success(self, mock_get_svc: MagicMock) -> None:
        """恢复伏笔返回 200 + Foreshadowing JSON."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing("林晚的身世")
        svc.restore = AsyncMock(return_value=foreshadowing)

        response = client.post(f"/api/v1/foreshadowings/{foreshadowing.id}/restore")
        assert response.status_code == 200
        assert response.json()["title"] == "林晚的身世"
        svc.restore.assert_awaited_once_with(foreshadowing.id)

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_restore_foreshadowing_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """恢复不存在的伏笔返回 404「伏笔不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.restore = AsyncMock(return_value=None)

        response = client.post(f"/api/v1/foreshadowings/{uuid.uuid4()}/restore")
        assert response.status_code == 404
        assert response.json()["detail"] == "伏笔不存在"

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_resolve_foreshadowing_success(self, mock_get_svc: MagicMock) -> None:
        """resolve 返回 200：status=resolved 且 resolved_at 已设置."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing(
            "林晚的身世",
            status=ForeshadowingStatus.RESOLVED,
            resolved_at=RESOLVED_TS,
        )
        svc.resolve = AsyncMock(return_value=foreshadowing)

        response = client.post(f"/api/v1/foreshadowings/{foreshadowing.id}/resolve")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert data["resolved_at"] == "2026-08-10T03:00:00Z"
        svc.resolve.assert_awaited_once_with(foreshadowing.id)

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_resolve_foreshadowing_idempotent(self, mock_get_svc: MagicMock) -> None:
        """对已 resolved 伏笔再次 resolve 幂等成功（原样返回，resolved_at 不更新）."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing(
            "林晚的身世",
            status=ForeshadowingStatus.RESOLVED,
            resolved_at=RESOLVED_TS,
        )
        svc.resolve = AsyncMock(return_value=foreshadowing)

        response = client.post(f"/api/v1/foreshadowings/{foreshadowing.id}/resolve")
        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
        assert response.json()["resolved_at"] == "2026-08-10T03:00:00Z"

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_resolve_foreshadowing_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """resolve 不存在的伏笔返回 404「伏笔不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.resolve = AsyncMock(return_value=None)

        response = client.post(f"/api/v1/foreshadowings/{uuid.uuid4()}/resolve")
        assert response.status_code == 404
        assert response.json()["detail"] == "伏笔不存在"

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_reopen_foreshadowing_success(self, mock_get_svc: MagicMock) -> None:
        """reopen 返回 200：status=open 且 resolved_at 清空."""
        svc = _mock_svc(mock_get_svc)
        foreshadowing = _foreshadowing("林晚的身世")  # open + resolved_at=None
        svc.reopen = AsyncMock(return_value=foreshadowing)

        response = client.post(f"/api/v1/foreshadowings/{foreshadowing.id}/reopen")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "open"
        assert data["resolved_at"] is None
        svc.reopen.assert_awaited_once_with(foreshadowing.id)

    @patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")
    def test_reopen_foreshadowing_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """reopen 不存在的伏笔返回 404「伏笔不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.reopen = AsyncMock(return_value=None)

        response = client.post(f"/api/v1/foreshadowings/{uuid.uuid4()}/reopen")
        assert response.status_code == 404
        assert response.json()["detail"] == "伏笔不存在"


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

    async def test_run_service_foreshadowing_not_found_404(self) -> None:
        """ForeshadowingNotFoundError → HTTPException 404，detail 透传消息
        （foreshadowings.py L76）."""
        from fastapi import HTTPException

        from inkflow.api.routers.foreshadowings import _run_service
        from inkflow.domain.ports.foreshadowing_errors import ForeshadowingNotFoundError

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(ForeshadowingNotFoundError("x")))
        assert ei.value.status_code == 404
        assert "x" in ei.value.detail
