"""#1002 RED: 大纲列表 level 透传 + sort_order 稳定排序 API 契约测试（Mock Service）.

镜像 test_outline_api.py 头部（自包含，与本目录其他测试文件互不共享 fixture）:
- TestClient(app) 全局实例
- PID / _outline / _point 工厂
- @patch(\"inkflow.api.routers.outlines.get_outline_service\") + _mock_svc

契约基准: specs/f11-outline/spec.md §6.3 + §14.1（#1002 行）。
这是 RED 契约测试：当前 router 未定义/未透传 level query，
故含 level 的断言应失败（AL2 / limit=0 为回归护栏，RED 期即 PASS）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.outline import Outline, PlotPoint

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _outline(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    sort_order: int = 0,
    description: str = "主线概述",
) -> Outline:
    """构造测试用大纲实体（固定时间戳，便于断言）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        sort_order=sort_order,
        created_at=TS,
        updated_at=TS,
    )


def _point(
    name: str,
    *,
    outline_id: uuid.UUID,
    arc_id: uuid.UUID | None = None,
    position: int = 1,
) -> PlotPoint:
    """构造测试用情节点实体。"""
    return PlotPoint(
        id=uuid.uuid4(),
        outline_id=outline_id,
        project_id=PID,
        name=name,
        type="开篇",
        description="节点描述",
        position=position,
        arc_id=arc_id,
        created_at=TS,
        updated_at=TS,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock OutlineService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestOutlineListLevel1002:
    """#1002 RED: 大纲列表 level 透传契约（router 层）。"""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_level_overall_transmitted(self, mock_get_svc: MagicMock) -> None:
        """AL1: 显式 level -> svc.list_outlines 收到 level='overall'（含默认参精确断言）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_outlines = AsyncMock(return_value=([], 0))
        svc.list_points = AsyncMock(return_value=[])

        response = client.get(
            f"/api/v1/projects/{PID}/outlines",
            params={
                "level": "overall",
                "sort_by": "sort_order",
                "sort_desc": "false",
                "offset": 0,
                "limit": 10,
            },
        )
        assert response.status_code == 200
        svc.list_outlines.assert_awaited_once_with(
            PID,
            search=None,
            sort_by="sort_order",
            sort_desc=False,
            offset=0,
            limit=10,
            level="overall",
        )

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_no_level_omits_key(self, mock_get_svc: MagicMock) -> None:
        """AL2（RED 期即 PASS 回归护栏）: 不传 level -> kwargs 不含 level 键，其余默认精确。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_outlines = AsyncMock(return_value=([], 0))
        svc.list_points = AsyncMock(return_value=[])

        response = client.get(f"/api/v1/projects/{PID}/outlines")
        assert response.status_code == 200
        svc.list_outlines.assert_awaited_once_with(
            PID,
            search=None,
            sort_by="updated_at",
            sort_desc=True,
            offset=0,
            limit=50,
        )
        assert "level" not in svc.list_outlines.await_args.kwargs

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_unknown_level_passthrough(self, mock_get_svc: MagicMock) -> None:
        """AL3: 未知 level='bogus' 透传不校验 -> 200 空 items + svc 收到 level='bogus'。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_outlines = AsyncMock(return_value=([], 0))
        svc.list_points = AsyncMock(return_value=[])

        response = client.get(
            f"/api/v1/projects/{PID}/outlines", params={"level": "bogus"}
        )
        assert response.status_code == 200
        assert response.json()["items"] == []
        svc.list_outlines.assert_awaited_once_with(
            PID,
            search=None,
            sort_by="updated_at",
            sort_desc=True,
            offset=0,
            limit=50,
            level="bogus",
        )

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_level_search_pagination_full(self, mock_get_svc: MagicMock) -> None:
        """AL4: level+search+分页全参一次透传（含 point_count 聚合形状）。"""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("觉醒卷")
        svc.list_outlines = AsyncMock(return_value=([outline], 1))
        svc.list_points = AsyncMock(return_value=[_point("节点", outline_id=outline.id)])

        response = client.get(
            f"/api/v1/projects/{PID}/outlines",
            params={
                "level": "volume",
                "search": "觉醒",
                "sort_by": "sort_order",
                "sort_desc": "false",
                "offset": 0,
                "limit": 10,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "觉醒卷"
        assert data["items"][0]["point_count"] == 1
        svc.list_outlines.assert_awaited_once_with(
            PID,
            search="觉醒",
            sort_by="sort_order",
            sort_desc=False,
            offset=0,
            limit=10,
            level="volume",
        )

    def test_list_level_with_limit_zero_422(self) -> None:
        """AL-守卫: level 组合同样受 limit=0 -> 422 校验（RED 期即 PASS）。"""
        response = client.get(
            f"/api/v1/projects/{PID}/outlines",
            params={"level": "overall", "limit": 0},
        )
        assert response.status_code == 422
