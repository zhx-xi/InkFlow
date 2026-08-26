"""F11 大纲管理 API 测试 — Mock Service 层（M5 RED→GREEN）.

测试范围 (spec §9 API 测试 + §3.5 异常映射表):
- 19 端点成功路径（201/200/204）
- 404 全路径（项目/大纲/情节点/弧线不存在、无效 UUID → 404）
- 422 业务校验（同名大纲/同名弧线/弧线跨项目 → 422）
- generate 200（save 两态）/ 项目不存在 → 404 / LLM 失败 → 500 / 解析失败 → 500
- 大纲详情含 plot_points 聚合（arc_name）、弧线详情含 points 聚合（outline_name）、
  列表端点 point_count 聚合（API 层聚合，不入库）
- 分页参数校验（limit 越界 → 422）

策略: @patch("inkflow.api.routers.outlines.get_outline_service")
整体替换 Service 获取函数（router 模块级本地引用），每个被路由 await 的
服务方法显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await 会
返回 coroutine 导致 500（F4 4.1 实测陷阱）。

依据: specs/f11-outline-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.outlines import OutlineCreateBody, PlotPointCreateBody
from inkflow.domain.models.outline import (
    GeneratedArc,
    GeneratedOutline,
    GeneratedPlotPoint,
    Outline,
    OutlineGenerationResult,
    PlotPoint,
    StoryArc,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.outline_errors import (
    ArcNameConflictError,
    ArcNotInProjectError,
    OutlineGenerationError,
    OutlineNameConflictError,
    OutlineNotFoundError,
    PlotPointNotFoundError,
    ProjectNotFoundError,
    StoryArcNotFoundError,
)

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


def _arc(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    description: str = "弧线说明",
) -> StoryArc:
    """构造测试用故事弧线实体。"""
    return StoryArc(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


def _generation_result(*, saved: bool = True) -> OutlineGenerationResult:
    """构造测试用生成结果（save 两态）。"""
    if not saved:
        return OutlineGenerationResult(
            saved=False,
            outline=None,
            preview=GeneratedOutline(
                name=None,
                description="预览描述",
                arcs=[GeneratedArc(name="主角成长线")],
                plot_points=[GeneratedPlotPoint(name="主角登场", arc="主角成长线")],
            ),
            warnings=[],
            model="deepseek/deepseek-chat",
        )
    return OutlineGenerationResult(
        saved=True,
        outline=_outline("第一卷大纲"),
        plot_points=[_point("主角登场", outline_id=uuid.uuid4())],
        arcs=[_arc("主角成长线")],
        warnings=["情节点名称为空已跳过"],
        model="deepseek/deepseek-chat",
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock OutlineService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestOutlineCRUDAPI:
    """大纲 CRUD 端点测试."""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_create_outline_success(self, mock_get_svc: MagicMock) -> None:
        """创建大纲返回 201 + Outline JSON."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲", sort_order=1, description="主角觉醒")
        svc.create_outline = AsyncMock(return_value=outline)

        response = client.post(
            f"/api/v1/projects/{PID}/outlines",
            json={"name": "第一卷大纲", "description": "主角觉醒", "sort_order": 1},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "第一卷大纲"
        assert data["description"] == "主角觉醒"
        assert data["project_id"] == str(PID)
        svc.create_outline.assert_awaited_once_with(
            PID, "第一卷大纲", "主角觉醒", 1, level="chapter", parent_id=None, chapter_id=None
        )

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_create_outline_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名活动大纲创建返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_outline = AsyncMock(side_effect=OutlineNameConflictError())

        response = client.post(f"/api/v1/projects/{PID}/outlines", json={"name": "第一卷大纲"})
        assert response.status_code == 422
        assert response.json()["detail"] == "同名大纲已存在（大纲名在项目内必须唯一）"

    def test_create_outline_missing_name_422(self) -> None:
        """缺少必填字段 name 返回 422（Pydantic 校验）."""
        response = client.post(f"/api/v1/projects/{PID}/outlines", json={"description": "x"})
        assert response.status_code == 422

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_outlines_success(self, mock_get_svc: MagicMock) -> None:
        """大纲列表返回 200 + {items, total, offset, limit}（含 point_count 聚合）."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        svc.list_outlines = AsyncMock(return_value=([outline], 1))
        svc.list_points = AsyncMock(return_value=[_point("主角登场", outline_id=outline.id)])

        response = client.get(
            f"/api/v1/projects/{PID}/outlines",
            params={
                "search": "第一卷",
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
        assert data["items"][0]["name"] == "第一卷大纲"
        assert data["items"][0]["point_count"] == 1
        svc.list_outlines.assert_awaited_once_with(
            PID,
            search="第一卷",
            sort_by="name",
            sort_desc=False,
            offset=0,
            limit=20,
        )

    def test_list_outlines_invalid_pagination_422(self) -> None:
        """分页参数越界（limit=0）返回 422."""
        response = client.get(f"/api/v1/projects/{PID}/outlines", params={"limit": 0})
        assert response.status_code == 422

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_outline_success(self, mock_get_svc: MagicMock) -> None:
        """大纲详情返回 200 + Outline JSON（含 plot_points 聚合与 arc_name）."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        arc = _arc("主角成长线")
        p1 = _point("主角登场", outline_id=outline.id, position=1)
        p2 = _point("金手指觉醒", outline_id=outline.id, position=2, arc_id=arc.id)
        svc.get_outline = AsyncMock(return_value=outline)
        svc.list_points = AsyncMock(return_value=[p1, p2])
        svc.get_arc = AsyncMock(return_value=arc)

        response = client.get(f"/api/v1/outlines/{outline.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "第一卷大纲"
        points = data["plot_points"]
        assert len(points) == 2
        assert points[0]["name"] == "主角登场"
        assert points[0]["arc_id"] is None
        assert points[0]["arc_name"] is None
        assert points[1]["name"] == "金手指觉醒"
        assert points[1]["arc_id"] == str(arc.id)
        assert points[1]["arc_name"] == "主角成长线"

    def test_get_outline_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404."""
        response = client.get("/api/v1/outlines/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "大纲不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_outline_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """大纲不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.get_outline = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/outlines/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "大纲不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_update_outline_success(self, mock_get_svc: MagicMock) -> None:
        """更新大纲返回 200 + Outline JSON."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        updated = outline.model_copy(update={"description": "（修订版）"})
        svc.update_outline = AsyncMock(return_value=updated)

        response = client.patch(
            f"/api/v1/outlines/{outline.id}", json={"description": "（修订版）"}
        )
        assert response.status_code == 200
        assert response.json()["description"] == "（修订版）"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_delete_outline_204(self, mock_get_svc: MagicMock) -> None:
        """删除大纲返回 204（v1.1 真删，无 force 参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_outline = AsyncMock(return_value=True)

        outline_id = uuid.uuid4()
        response = client.delete(f"/api/v1/outlines/{outline_id}")
        assert response.status_code == 204
        svc.delete_outline.assert_awaited_once_with(outline_id)

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_delete_outline_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的大纲返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_outline = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/outlines/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "大纲不存在"


class TestPlotPointAPI:
    """情节点端点测试."""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_create_point_success(self, mock_get_svc: MagicMock) -> None:
        """创建情节点返回 201 + PlotPoint JSON（position 自动分配）。"""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        point = _point("主角登场", outline_id=outline.id, position=1)
        svc.create_point = AsyncMock(return_value=point)

        response = client.post(
            f"/api/v1/outlines/{outline.id}/plot-points",
            json={"name": "主角登场", "type": "开篇", "description": "测试", "arc_id": None},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "主角登场"
        assert data["position"] == 1
        svc.create_point.assert_awaited_once_with(
            outline.id, "主角登场", "开篇", "测试", None, None
        )

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_create_point_outline_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """大纲不存在创建情节点返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.create_point = AsyncMock(side_effect=OutlineNotFoundError())

        response = client.post(
            f"/api/v1/outlines/{uuid.uuid4()}/plot-points", json={"name": "主角登场"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "大纲不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_create_point_arc_not_in_project_422(self, mock_get_svc: MagicMock) -> None:
        """情节点挂不存在/跨项目弧线返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_point = AsyncMock(side_effect=ArcNotInProjectError())

        response = client.post(
            f"/api/v1/outlines/{uuid.uuid4()}/plot-points",
            json={"name": "主角登场", "arc_id": str(uuid.uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "弧线不存在于该项目"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_points_success(self, mock_get_svc: MagicMock) -> None:
        """情节点列表返回 200 + {items, total}（含 arc_name 聚合）."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        arc = _arc("主角成长线")
        point = _point("主角登场", outline_id=outline.id, arc_id=arc.id)
        svc.list_points = AsyncMock(return_value=[point])
        svc.get_arc = AsyncMock(return_value=arc)

        response = client.get(f"/api/v1/outlines/{outline.id}/plot-points")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "主角登场"
        assert data["items"][0]["arc_name"] == "主角成长线"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_point_success(self, mock_get_svc: MagicMock) -> None:
        """情节点详情返回 200 + PlotPoint JSON（含 arc_name）。"""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        arc = _arc("主角成长线")
        point = _point("主角登场", outline_id=outline.id, arc_id=arc.id)
        svc.get_point = AsyncMock(return_value=point)
        svc.get_arc = AsyncMock(return_value=arc)

        response = client.get(f"/api/v1/plot-points/{point.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "主角登场"
        assert data["arc_id"] == str(arc.id)
        assert data["arc_name"] == "主角成长线"

    def test_get_point_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404."""
        response = client.get("/api/v1/plot-points/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "情节点不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_point_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """情节点不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.get_point = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/plot-points/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "情节点不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_update_point_success(self, mock_get_svc: MagicMock) -> None:
        """更新情节点返回 200（arc_id \"\" 清除语义透传 DTO）。"""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        point = _point("主角登场", outline_id=outline.id)
        updated = point.model_copy(update={"type": "发展", "arc_id": None})
        svc.update_point = AsyncMock(return_value=updated)

        response = client.patch(
            f"/api/v1/plot-points/{point.id}", json={"type": "发展", "arc_id": ""}
        )
        assert response.status_code == 200
        assert response.json()["type"] == "发展"
        assert response.json()["arc_id"] is None
        upd = svc.update_point.await_args.args[1]
        assert upd.arc_id == ""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_delete_point_204(self, mock_get_svc: MagicMock) -> None:
        """删除情节点返回 204（v1.1 真删，无 force 参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_point = AsyncMock(return_value=True)

        point_id = uuid.uuid4()
        response = client.delete(f"/api/v1/plot-points/{point_id}")
        assert response.status_code == 204
        svc.delete_point.assert_awaited_once_with(point_id)

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_delete_point_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的情节点返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_point = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/plot-points/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "情节点不存在"


class TestStoryArcAPI:
    """故事弧线端点测试."""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_create_arc_success(self, mock_get_svc: MagicMock) -> None:
        """创建弧线返回 201 + StoryArc JSON."""
        svc = _mock_svc(mock_get_svc)
        arc = _arc("主角成长线")
        svc.create_arc = AsyncMock(return_value=arc)

        response = client.post(
            f"/api/v1/projects/{PID}/story-arcs",
            json={"name": "主角成长线", "description": "蜕变轨迹"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "主角成长线"
        assert data["project_id"] == str(PID)
        svc.create_arc.assert_awaited_once_with(PID, "主角成长线", "蜕变轨迹")

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_create_arc_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名活动弧线创建返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_arc = AsyncMock(side_effect=ArcNameConflictError())

        response = client.post(f"/api/v1/projects/{PID}/story-arcs", json={"name": "主角成长线"})
        assert response.status_code == 422
        assert response.json()["detail"] == "同名故事弧线已存在（弧线名在项目内必须唯一）"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_arcs_success(self, mock_get_svc: MagicMock) -> None:
        """弧线列表返回 200 + {items, total}（含 point_count 聚合）."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        arc = _arc("主角成长线")
        point = _point("金手指觉醒", outline_id=outline.id, arc_id=arc.id)
        svc.list_arcs = AsyncMock(return_value=[arc])
        svc.list_outlines = AsyncMock(return_value=([outline], 1))
        svc.list_points = AsyncMock(return_value=[point])

        response = client.get(f"/api/v1/projects/{PID}/story-arcs")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "主角成长线"
        assert data["items"][0]["point_count"] == 1

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_arc_success(self, mock_get_svc: MagicMock) -> None:
        """弧线详情返回 200 + StoryArc JSON（含 points 聚合与 outline_name）."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        arc = _arc("主角成长线")
        point = _point("金手指觉醒", outline_id=outline.id, arc_id=arc.id)
        svc.get_arc = AsyncMock(return_value=arc)
        svc.list_outlines = AsyncMock(return_value=([outline], 1))
        svc.list_points = AsyncMock(return_value=[point])

        response = client.get(f"/api/v1/story-arcs/{arc.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "主角成长线"
        points = data["points"]
        assert len(points) == 1
        assert points[0]["name"] == "金手指觉醒"
        assert points[0]["outline_id"] == str(outline.id)
        assert points[0]["outline_name"] == "第一卷大纲"

    def test_get_arc_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404."""
        response = client.get("/api/v1/story-arcs/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "弧线不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_arc_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """弧线不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.get_arc = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/story-arcs/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "弧线不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_update_arc_success(self, mock_get_svc: MagicMock) -> None:
        """更新弧线返回 200 + StoryArc JSON."""
        svc = _mock_svc(mock_get_svc)
        arc = _arc("主角成长线")
        updated = arc.model_copy(update={"description": "（修订版）"})
        svc.update_arc = AsyncMock(return_value=updated)

        response = client.patch(f"/api/v1/story-arcs/{arc.id}", json={"description": "（修订版）"})
        assert response.status_code == 200
        assert response.json()["description"] == "（修订版）"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_delete_arc_204(self, mock_get_svc: MagicMock) -> None:
        """删除弧线返回 204（v1.1 真删，无 force 参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_arc = AsyncMock(return_value=True)

        arc_id = uuid.uuid4()
        response = client.delete(f"/api/v1/story-arcs/{arc_id}")
        assert response.status_code == 204
        svc.delete_arc.assert_awaited_once_with(arc_id)

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_delete_arc_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的弧线返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_arc = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/story-arcs/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "弧线不存在"


class TestGenerateAPI:
    """AI 生成大纲端点测试."""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_success_saved(self, mock_get_svc: MagicMock) -> None:
        """生成并落库返回 200 + OutlineGenerationResult JSON（save=true 默认）。"""
        svc = _mock_svc(mock_get_svc)
        result = _generation_result(saved=True)
        svc.generate = AsyncMock(return_value=result)

        response = client.post(
            "/api/v1/outlines/generate",
            json={
                "project_id": str(PID),
                "name": "第一卷大纲",
                "prompt": "废柴逆袭，风格偏爽文",
                "num_chapters": 30,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["saved"] is True
        assert data["outline"]["name"] == "第一卷大纲"
        assert len(data["plot_points"]) == 1
        assert len(data["arcs"]) == 1
        assert data["warnings"] == ["情节点名称为空已跳过"]
        assert data["model"] == "deepseek/deepseek-chat"
        req = svc.generate.await_args.args[0]
        assert req.project_id == PID
        assert req.num_chapters == 30

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_success_includes_point_count(self, mock_get_svc: MagicMock) -> None:
        """生成响应聚合 point_count（#677：前端凭 point_count 判定章节是否有子节点）。"""
        svc = _mock_svc(mock_get_svc)
        result = _generation_result(saved=True)
        svc.generate = AsyncMock(return_value=result)

        response = client.post(
            "/api/v1/outlines/generate",
            json={"project_id": str(PID), "name": "第一卷大纲"},
        )
        assert response.status_code == 200
        data = response.json()
        # point_count = plot_points.length 聚合（API 层聚合，不入库）
        assert data["point_count"] == len(data["plot_points"])
        assert data["point_count"] == 1

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_success_preview(self, mock_get_svc: MagicMock) -> None:
        """仅预览返回 200（save=false：outline 为 null，preview 非空）。"""
        svc = _mock_svc(mock_get_svc)
        result = _generation_result(saved=False)
        svc.generate = AsyncMock(return_value=result)

        response = client.post(
            "/api/v1/outlines/generate", json={"project_id": str(PID), "save": False}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["saved"] is False
        assert data["outline"] is None
        assert data["preview"]["plot_points"][0]["name"] == "主角登场"
        req = svc.generate.await_args.args[0]
        assert req.save is False

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """生成时项目不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.generate = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post("/api/v1/outlines/generate", json={"project_id": str(PID)})
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_llm_failure_500(self, mock_get_svc: MagicMock) -> None:
        """LLM 调用失败返回 500."""
        svc = _mock_svc(mock_get_svc)
        svc.generate = AsyncMock(
            side_effect=LLMRequestError("LLM 调用失败", retries_exhausted=True)
        )

        response = client.post("/api/v1/outlines/generate", json={"project_id": str(PID)})
        assert response.status_code == 500
        assert response.json()["detail"] == "LLM 调用失败，请稍后重试"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_parse_failure_500(self, mock_get_svc: MagicMock) -> None:
        """LLM 输出无法解析（重试后仍失败）返回 500."""
        svc = _mock_svc(mock_get_svc)
        svc.generate = AsyncMock(side_effect=OutlineGenerationError())

        response = client.post("/api/v1/outlines/generate", json={"project_id": str(PID)})
        assert response.status_code == 500
        assert response.json()["detail"] == "大纲生成失败: LLM 输出无法解析，请重试"


class TestOutlineCoverageGaps:
    """F11 覆盖率补齐：异常映射分支 / None 防御 / 聚合过滤分支 / validator 直接调用."""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_arc_story_arc_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """StoryArcNotFoundError（服务层主动抛出）→ 404（消息即 detail）."""
        svc = _mock_svc(mock_get_svc)
        svc.get_arc = AsyncMock(side_effect=StoryArcNotFoundError())

        response = client.get(f"/api/v1/story-arcs/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "故事弧线不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_point_not_found_error_404(self, mock_get_svc: MagicMock) -> None:
        """PlotPointNotFoundError（服务层主动抛出）→ 404（消息即 detail）."""
        svc = _mock_svc(mock_get_svc)
        svc.get_point = AsyncMock(side_effect=PlotPointNotFoundError())

        response = client.get(f"/api/v1/plot-points/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "情节点不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_get_arc_points_filters_other_arc(self, mock_get_svc: MagicMock) -> None:
        """弧线详情 points 聚合只保留属于该弧线的成员（arc_id 不匹配的点被过滤）."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        arc = _arc("主角成长线")
        other_arc = _arc("配角支线")
        member = _point("金手指觉醒", outline_id=outline.id, arc_id=arc.id)
        foreign = _point("配角登场", outline_id=outline.id, arc_id=other_arc.id)
        svc.get_arc = AsyncMock(return_value=arc)
        svc.list_outlines = AsyncMock(return_value=([outline], 1))
        svc.list_points = AsyncMock(return_value=[member, foreign])

        response = client.get(f"/api/v1/story-arcs/{arc.id}")
        assert response.status_code == 200
        points = response.json()["points"]
        assert [p["name"] for p in points] == ["金手指觉醒"]

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_list_arcs_point_count_filters_other_arc(self, mock_get_svc: MagicMock) -> None:
        """弧线列表 point_count 只统计属于该弧线的点（跨弧线点不计入）."""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        arc = _arc("主角成长线")
        other_arc = _arc("配角支线")
        member = _point("金手指觉醒", outline_id=outline.id, arc_id=arc.id)
        foreign = _point("配角登场", outline_id=outline.id, arc_id=other_arc.id)
        svc.list_arcs = AsyncMock(return_value=[arc])
        svc.list_outlines = AsyncMock(return_value=([outline], 1))
        svc.list_points = AsyncMock(return_value=[member, foreign])

        response = client.get(f"/api/v1/projects/{PID}/story-arcs")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["point_count"] == 1

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_update_outline_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的大纲返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.update_outline = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/outlines/{uuid.uuid4()}", json={"name": "改名"})
        assert response.status_code == 404
        assert response.json()["detail"] == "大纲不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_update_point_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的情节点返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.update_point = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/plot-points/{uuid.uuid4()}", json={"name": "改名"})
        assert response.status_code == 404
        assert response.json()["detail"] == "情节点不存在"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_update_arc_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的弧线返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.update_arc = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/story-arcs/{uuid.uuid4()}", json={"name": "改名"})
        assert response.status_code == 404
        assert response.json()["detail"] == "弧线不存在"

    def test_validate_sort_order_negative(self) -> None:
        """OutlineCreateBody 排序权重为负数 → ValueError（直接调用，规避 pydantic-core 盲区）."""
        with pytest.raises(ValueError, match="排序权重不能为负数"):
            OutlineCreateBody.validate_sort_order(-1)
        assert OutlineCreateBody.validate_sort_order(0) == 0

    def test_validate_position_negative(self) -> None:
        """PlotPointCreateBody 排序位置为负数 → ValueError（直接调用）."""
        with pytest.raises(ValueError, match="排序位置不能为负数"):
            PlotPointCreateBody.validate_position(-1)
        assert PlotPointCreateBody.validate_position(None) is None
        assert PlotPointCreateBody.validate_position(2) == 2
