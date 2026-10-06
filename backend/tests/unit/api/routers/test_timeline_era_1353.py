"""#1353/#1410 时间线纪元 — API 契约（f12 spec v1.4 §3.2 请求体 + §3.4 422 + §7，ADR-065）。

【契约（钉住三件事）】
1. POST 请求体带 ``era`` / ``era_value`` → 透传为 ``create_event`` 的 kwargs；
   响应 JSON **顶层**回读 ``era`` / ``era_value`` / ``era_scale``（v1.4 正式列），
   ``extra`` 保持 ``{}``
2. **向后兼容**：请求体不带纪元 → **不传** era/era_value kwargs
   （``extra`` 仍是 ``{}``，既有 exact-kwargs 用例零改动 —— 与 spec v1.2 行为一致）
3. 校验：``era`` > 50 字符 / ``era_value`` 非数值字符串 → 422

【RED 预期（v1.4）】响应仍走 ``extra`` → 顶层 ``era`` / ``era_scale`` 断言 FAIL；
零 SyntaxError / TypeError。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.timeline import TimelineEvent

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 10, 6, 10, 0, 0)
CREATE_URL = f"/api/v1/projects/{PID}/timeline/events"


def _event(title: str, **overrides: object) -> TimelineEvent:
    """构造测试用事件实体（固定时间戳，便于断言）。"""
    kwargs: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "title": title,
        "description": "",
        "time_value": None,
        "time_unit": "",
        "time_display": "",
        "narrative_position": 3,
        "timeline_flag": "",
        "era": "",
        "era_value": None,
        "era_scale": 1.0,
        "extra": {},
        "created_at": TS,
        "updated_at": TS,
    }
    kwargs.update(overrides)
    return TimelineEvent(**kwargs)  # type: ignore[arg-type]  # kwargs 为动态 dict


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestCreateEventEraAPI:
    """POST /projects/{pid}/timeline/events —— era 透传 + 正式列回读 + 422。"""

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_create_with_era_passes_kwargs_and_returns_columns(
        self, mock_get_svc: MagicMock
    ) -> None:
        svc = _mock_svc(mock_get_svc)
        svc.create_event = AsyncMock(
            return_value=_event("事件甲", era="示例历", era_value=317.5, era_scale=1.0)
        )

        response = client.post(
            CREATE_URL,
            json={
                "title": "事件甲",
                "time_display": "示例历 317 年秋",
                "era": "示例历",
                "era_value": 317.5,
            },
        )

        assert response.status_code == 201
        body = response.json()
        # 读回一致：响应顶层三字段即正式列（GUI/CLI 的轴族派生数据面）
        assert body["era"] == "示例历"
        assert body["era_value"] == 317.5
        assert body["era_scale"] == 1.0
        assert body["extra"] == {}
        svc.create_event.assert_awaited_once_with(
            PID,
            "事件甲",
            description="",
            time_value=None,
            time_unit="",
            time_display="示例历 317 年秋",
            narrative_position=None,
            timeline_flag="",
            era="示例历",
            era_value=317.5,
        )

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_create_without_era_omits_kwargs(self, mock_get_svc: MagicMock) -> None:
        """向后兼容：不带纪元 → 不出现 era/era_value kwargs（spec v1.2 行为零变化）。"""
        svc = _mock_svc(mock_get_svc)
        svc.create_event = AsyncMock(return_value=_event("事件甲"))

        response = client.post(CREATE_URL, json={"title": "事件甲"})

        assert response.status_code == 201
        body = response.json()
        assert body["era"] == ""
        assert body["era_scale"] == 1.0
        assert body["extra"] == {}
        svc.create_event.assert_awaited_once_with(
            PID,
            "事件甲",
            description="",
            time_value=None,
            time_unit="",
            time_display="",
            narrative_position=None,
            timeline_flag="",
        )

    def test_create_era_too_long_422(self) -> None:
        response = client.post(CREATE_URL, json={"title": "事件甲", "era": "轴" * 51})

        assert response.status_code == 422

    def test_create_era_value_non_numeric_422(self) -> None:
        response = client.post(
            CREATE_URL, json={"title": "事件甲", "era": "示例历", "era_value": "abc"}
        )

        assert response.status_code == 422

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_create_with_era_scale_passes_kwargs(self, mock_get_svc: MagicMock) -> None:
        """v1.5（#1411 §2.8 E11）：显式非默认 era_scale → 透传 + 顶层回读。"""
        svc = _mock_svc(mock_get_svc)
        svc.create_event = AsyncMock(
            return_value=_event("事件甲", era="示例历", era_value=1.0, era_scale=2.0)
        )

        response = client.post(
            CREATE_URL,
            json={"title": "事件甲", "era": "示例历", "era_value": 1.0, "era_scale": 2.0},
        )

        assert response.status_code == 201
        assert response.json()["era_scale"] == 2.0
        assert svc.create_event.await_args.kwargs["era_scale"] == 2.0

    def test_create_era_scale_non_positive_422(self) -> None:
        """流速比须为正数（§2.8 E11）。"""
        response = client.post(CREATE_URL, json={"title": "事件甲", "era_scale": 0.0})

        assert response.status_code == 422


class TestUpdateEventEraAPI:
    """PATCH /timeline/events/{id} —— 清除语义透传 + 正式列回读 + 422。"""

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_patch_era_empty_clears_through_dto(self, mock_get_svc: MagicMock) -> None:
        svc = _mock_svc(mock_get_svc)
        event_id = uuid.uuid4()
        svc.update_event = AsyncMock(return_value=_event("事件甲"))

        response = client.patch(f"/api/v1/timeline/events/{event_id}", json={"era": ""})

        assert response.status_code == 200
        passed = svc.update_event.await_args.args[1]
        assert passed.era == ""
        assert passed.era_value is None
        body = response.json()
        assert body["era"] == ""
        assert body["extra"] == {}

    @patch("inkflow.api.routers.timeline.get_timeline_service")
    def test_patch_era_returns_column_roundtrip(self, mock_get_svc: MagicMock) -> None:
        svc = _mock_svc(mock_get_svc)
        event_id = uuid.uuid4()
        svc.update_event = AsyncMock(
            return_value=_event("事件甲", era="示例仙历", era_value=1024.0)
        )

        response = client.patch(
            f"/api/v1/timeline/events/{event_id}",
            json={"era": "示例仙历", "era_value": 1024.0},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["era"] == "示例仙历"
        assert body["era_value"] == 1024.0

    def test_patch_era_value_non_numeric_422(self) -> None:
        response = client.patch(
            f"/api/v1/timeline/events/{uuid.uuid4()}",
            json={"era_value": "abc"},
        )

        assert response.status_code == 422
