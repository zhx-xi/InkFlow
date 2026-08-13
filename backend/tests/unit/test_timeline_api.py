"""F12 时间线管理 API 测试 — Mock Service 层（M5 RED→GREEN）。

测试范围 (spec §9 API 测试 + §3.4 异常映射表):
- 8 端点成功路径（201/200/204）
- 404 全路径（项目/事件不存在、无效 UUID → 404）
- 422 字段校验（标题空/超长、time_value 非有限/越界、清除传非空字符串）
- 双线总览 200 / 一致性检查 200（include_flashbacks 两态）
- 删除真删（delete_event，无 force 参数）

策略: @patch("inkflow.api.routers.timeline.get_timeline_service")
整体替换 Service 获取函数（router 模块级本地引用），每个被路由 await 的
服务方法显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await 会
返回 coroutine 导致 500（F4 4.1 实测陷阱）。

依据: specs/f12-timeline-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.timeline import TimelineEventCreateBody
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineConflict,
    TimelineEvent,
    TimelineEventRef,
    TimelineView,
)
from inkflow.domain.ports.timeline_errors import (
    ProjectNotFoundError,
    TimelineNotFoundError,
    TimelineServiceError,
)

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _event(title: str, **overrides: object) -> TimelineEvent:
    """构造测试用时间线事件实体（固定时间戳，便于断言）。"""
    kwargs: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "title": title,
        "description": "外门考核夜，林尘丹田中的古鼎第一次亮起。",
        "time_value": 317.5,
        "time_unit": "年",
        "time_display": "青元历 317 年秋",
        "narrative_position": 3,
        "timeline_flag": "",
        "created_at": TS,
        "updated_at": TS,
    }
    kwargs.update(overrides)
    return TimelineEvent(**kwargs)  # type: ignore[arg-type]  # kwargs 为动态 dict，无法静态匹配构造器参数签名


def _view() -> TimelineView:
    """构造双线总览实体（事件时间线 + 叙事时间线）。"""
    return TimelineView(
        project_id=PID,
        total=2,
        event_timeline=[
            _event("林尘拜入青云宗", time_value=315.0, narrative_position=1),
            _event("林尘觉醒金手指", time_value=317.5, narrative_position=2),
        ],
        narrative_order=[
            _event("林尘觉醒金手指", time_value=317.5, narrative_position=2),
            _event("宗门大比夺冠", time_value=319.0, narrative_position=3),
        ],
    )


def _report(*, include_flashbacks: bool = True) -> ConsistencyReport:
    """构造一致性检查报告实体（1 条未标记冲突 + 可选 1 条已声明倒叙）。"""
    conflicts = [
        TimelineConflict(
            conflict_type="order_conflict",
            prev=TimelineEventRef(
                id=uuid.uuid4(),
                title="林尘觉醒金手指",
                time_value=317.5,
                time_display="青元历 317 年秋",
                narrative_position=2,
                timeline_flag="",
            ),
            next=TimelineEventRef(
                id=uuid.uuid4(),
                title="外门往事",
                time_value=312.0,
                time_display="青元历 312 年",
                narrative_position=3,
                timeline_flag="",
            ),
            message="叙事顺序与世界内时间矛盾。",
        )
    ]
    flashbacks = (
        [
            TimelineConflict(
                conflict_type="flashback",
                prev=TimelineEventRef(
                    id=uuid.uuid4(),
                    title="宗门大比夺冠",
                    time_value=319.0,
                    time_display="青元历 319 年夏",
                    narrative_position=4,
                    timeline_flag="",
                ),
                next=TimelineEventRef(
                    id=uuid.uuid4(),
                    title="外门往事",
                    time_value=312.0,
                    time_display="青元历 312 年",
                    narrative_position=5,
                    timeline_flag="flashback",
                ),
                message="已标记，判定合法。",
            )
        ]
        if include_flashbacks
        else []
    )
    return ConsistencyReport(
        project_id=PID,
        checked=4,
        skipped=1,
        consistent=False,
        conflicts=conflicts,
        flashbacks=flashbacks,
        event_timeline=_view().event_timeline,
        narrative_order=_view().narrative_order,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock TimelineService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestTimelineEventCRUDAPI:
    """事件 CRUD 端点测试."""

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_create_event_success(self, mock_get_svc: MagicMock) -> None:
        """创建事件返回 201 + TimelineEvent JSON."""
        svc = _mock_svc(mock_get_svc)
        event = _event("林尘觉醒金手指")
        svc.create_event = AsyncMock(return_value=event)

        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events",
            json={
                "title": "林尘觉醒金手指",
                "description": "外门考核夜，林尘丹田中的古鼎第一次亮起。",
                "time_value": 317.5,
                "time_unit": "年",
                "time_display": "青元历 317 年秋",
                "timeline_flag": "",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "林尘觉醒金手指"
        assert data["project_id"] == str(PID)
        assert data["time_value"] == 317.5
        assert data["narrative_position"] == 3
        svc.create_event.assert_awaited_once_with(
            PID,
            "林尘觉醒金手指",
            description="外门考核夜，林尘丹田中的古鼎第一次亮起。",
            time_value=317.5,
            time_unit="年",
            time_display="青元历 317 年秋",
            narrative_position=None,
            timeline_flag="",
        )

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_create_event_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """创建事件时项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.create_event = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events",
            json={"title": "林尘觉醒金手指"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_create_event_invalid_project_uuid_404(self) -> None:
        """无效项目 UUID 格式返回 404「项目不存在」."""
        response = client.post(
            "/api/v1/projects/not-a-uuid/timeline/events",
            json={"title": "林尘觉醒金手指"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_create_event_blank_title_422(self) -> None:
        """标题为空白返回 422（Pydantic 校验）."""
        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events",
            json={"title": "   "},
        )
        assert response.status_code == 422
        assert "事件标题不能为空" in response.text

    def test_create_event_title_too_long_422(self) -> None:
        """标题超过 100 字符返回 422."""
        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events",
            json={"title": "长" * 101},
        )
        assert response.status_code == 422
        assert "事件标题不能超过 100 个字符" in response.text

    def test_create_event_time_value_nan_422(self) -> None:
        """time_value 为 NaN 返回 422（字符串形式，Pydantic 解析为 NaN 后校验拒绝）."""
        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events",
            json={"title": "林尘觉醒金手指", "time_value": "nan"},
        )
        assert response.status_code == 422
        assert "世界内时间必须是有限数值" in response.text

    def test_create_event_time_value_out_of_range_422(self) -> None:
        """time_value 超出 [-10^12, 10^12] 返回 422."""
        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events",
            json={"title": "林尘觉醒金手指", "time_value": 1e13},
        )
        assert response.status_code == 422
        assert "世界内时间超出允许范围" in response.text

    def test_create_event_negative_position_422(self) -> None:
        """narrative_position 为负数返回 422."""
        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events",
            json={"title": "林尘觉醒金手指", "narrative_position": -1},
        )
        assert response.status_code == 422
        assert "叙事位置不能为负数" in response.text

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_list_events_success(self, mock_get_svc: MagicMock) -> None:
        """事件列表返回 200 + {items, total, offset, limit}."""
        svc = _mock_svc(mock_get_svc)
        event = _event("林尘觉醒金手指")
        svc.list_events = AsyncMock(return_value=([event], 1))

        response = client.get(
            f"/api/v1/projects/{PID}/timeline/events",
            params={
                "search": "金手指",
                "sort_by": "time_value",
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
        assert data["items"][0]["title"] == "林尘觉醒金手指"
        svc.list_events.assert_awaited_once_with(
            PID,
            search="金手指",
            sort_by="time_value",
            sort_desc=False,
            offset=0,
            limit=20,
        )

    def test_list_events_invalid_pagination_422(self) -> None:
        """分页参数越界（limit=0）返回 422."""
        response = client.get(
            f"/api/v1/projects/{PID}/timeline/events",
            params={"limit": 0},
        )
        assert response.status_code == 422

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_get_timeline_view_success(self, mock_get_svc: MagicMock) -> None:
        """双线总览返回 200 + TimelineView JSON."""
        svc = _mock_svc(mock_get_svc)
        svc.get_timeline_view = AsyncMock(return_value=_view())

        response = client.get(f"/api/v1/projects/{PID}/timeline")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == str(PID)
        assert data["total"] == 2
        assert data["event_timeline"][0]["title"] == "林尘拜入青云宗"
        assert data["narrative_order"][0]["title"] == "林尘觉醒金手指"
        svc.get_timeline_view.assert_awaited_once_with(PID)

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_get_timeline_view_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """双线总览时项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get_timeline_view = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.get(f"/api/v1/projects/{PID}/timeline")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_check_consistency_success(self, mock_get_svc: MagicMock) -> None:
        """一致性检查返回 200 + ConsistencyReport JSON（默认 include_flashbacks=true）."""
        svc = _mock_svc(mock_get_svc)
        svc.check_consistency = AsyncMock(return_value=_report())

        response = client.get(f"/api/v1/projects/{PID}/timeline/check")
        assert response.status_code == 200
        data = response.json()
        assert data["checked"] == 4
        assert data["skipped"] == 1
        assert data["consistent"] is False
        assert data["conflicts"][0]["conflict_type"] == "order_conflict"
        assert data["flashbacks"][0]["conflict_type"] == "flashback"
        svc.check_consistency.assert_awaited_once_with(PID, include_flashbacks=True)

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_check_consistency_exclude_flashbacks(self, mock_get_svc: MagicMock) -> None:
        """include_flashbacks=false 时 flashbacks 为空列表（透传参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.check_consistency = AsyncMock(return_value=_report(include_flashbacks=False))

        response = client.get(
            f"/api/v1/projects/{PID}/timeline/check",
            params={"include_flashbacks": "false"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["flashbacks"] == []
        assert data["conflicts"][0]["conflict_type"] == "order_conflict"
        svc.check_consistency.assert_awaited_once_with(PID, include_flashbacks=False)

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_check_consistency_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """一致性检查时项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.check_consistency = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.get(f"/api/v1/projects/{PID}/timeline/check")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_get_event_success(self, mock_get_svc: MagicMock) -> None:
        """事件详情返回 200 + TimelineEvent JSON."""
        svc = _mock_svc(mock_get_svc)
        event = _event("林尘觉醒金手指")
        svc.get_event = AsyncMock(return_value=event)

        response = client.get(f"/api/v1/timeline/events/{event.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(event.id)
        assert data["title"] == "林尘觉醒金手指"
        assert data["project_id"] == str(PID)
        svc.get_event.assert_awaited_once_with(event.id)

    def test_get_event_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404「事件不存在」."""
        response = client.get("/api/v1/timeline/events/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "事件不存在"

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_get_event_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """事件不存在返回 404「事件不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get_event = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/timeline/events/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "事件不存在"

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_update_event_success(self, mock_get_svc: MagicMock) -> None:
        """更新事件返回 200 + TimelineEvent JSON（time_value \"\" 清除语义透传）."""
        svc = _mock_svc(mock_get_svc)
        event = _event("林尘觉醒金手指", time_value=None, timeline_flag="flashback")
        svc.update_event = AsyncMock(return_value=event)

        response = client.patch(
            f"/api/v1/timeline/events/{event.id}",
            json={"time_value": "", "timeline_flag": "flashback"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["time_value"] is None
        assert data["timeline_flag"] == "flashback"
        svc.update_event.assert_awaited_once()
        args, _ = svc.update_event.await_args
        assert args[0] == event.id
        assert args[1].time_value == ""  # None/"" 双语义直接透传，由 service 处理
        assert args[1].timeline_flag == "flashback"

    def test_update_event_clear_time_value_nonempty_string_422(self) -> None:
        """清除世界内时间传非空字符串返回 422."""
        response = client.patch(
            f"/api/v1/timeline/events/{uuid.uuid4()}",
            json={"time_value": "abc"},
        )
        assert response.status_code == 422
        assert "清除世界内时间请传空字符串" in response.text

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_update_event_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的事件返回 404「事件不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.update_event = AsyncMock(return_value=None)

        response = client.patch(
            f"/api/v1/timeline/events/{uuid.uuid4()}",
            json={"title": "改名"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "事件不存在"

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_delete_event_204(self, mock_get_svc: MagicMock) -> None:
        """删除事件返回 204（v1.1 真删，无 force 参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_event = AsyncMock(return_value=True)

        event_id = uuid.uuid4()
        response = client.delete(f"/api/v1/timeline/events/{event_id}")
        assert response.status_code == 204
        svc.delete_event.assert_awaited_once_with(event_id)

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_delete_event_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的事件返回 404「事件不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_event = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/timeline/events/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "事件不存在"


class TestTimelineCoverageGaps:
    """F12 覆盖率补齐：异常映射分支 / None 防御 / validator 直接调用."""

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_create_event_service_error_422(self, mock_get_svc: MagicMock) -> None:
        """TimelineServiceError（业务校验）→ 422（消息即 detail）."""
        svc = _mock_svc(mock_get_svc)
        svc.create_event = AsyncMock(side_effect=TimelineServiceError("时间线配置错误"))

        response = client.post(
            f"/api/v1/projects/{PID}/timeline/events", json={"title": "林尘觉醒金手指"}
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "时间线配置错误"

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_get_event_not_found_error_404(self, mock_get_svc: MagicMock) -> None:
        """TimelineNotFoundError（服务层主动抛出）→ 404（消息即 detail）."""
        svc = _mock_svc(mock_get_svc)
        svc.get_event = AsyncMock(side_effect=TimelineNotFoundError())

        response = client.get(f"/api/v1/timeline/events/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "事件不存在"

    def test_validate_narrative_position(self) -> None:
        """TimelineEventCreateBody 叙事位置校验：None/非负放行、负数 ValueError（直接调用）."""
        assert TimelineEventCreateBody.validate_narrative_position(None) is None
        assert TimelineEventCreateBody.validate_narrative_position(5) == 5
        with pytest.raises(ValueError, match="叙事位置不能为负数"):
            TimelineEventCreateBody.validate_narrative_position(-1)

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_get_timeline_view_none_404(self, mock_get_svc: MagicMock) -> None:
        """双线总览：项目不存在（服务返回 None）→ 404."""
        svc = _mock_svc(mock_get_svc)
        svc.get_timeline_view = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/projects/{PID}/timeline")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_check_consistency_none_404(self, mock_get_svc: MagicMock) -> None:
        """一致性检查：项目不存在（服务返回 None）→ 404."""
        svc = _mock_svc(mock_get_svc)
        svc.check_consistency = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/projects/{PID}/timeline/check")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
