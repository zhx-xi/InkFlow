"""#669 AI 覆盖当前大纲 — replace 模式/确认覆盖 API 契约测试（B 轨 RED，HTTP 层）.

契约: .hermes/plans/contract-669.md §5 REST API + §8 B 轨 B1-B7（B8 既有文件回归由父侧跑）。
镜像: tests/unit/api/routers/test_outline_api.py
（TestClient + @patch("inkflow.api.routers.outlines.get_outline_service")）。

范围:
- B1: POST /api/v1/outlines/generate mode=replace（svc.generate mocked 返回暂存结果）
      → 200 requires_confirmation/saved/outline/point_count
      + 请求对象透传（req.mode / req.target_outline_id）
- B2: mode=replace 缺 target_outline_id → 422「覆盖模式必须指定目标大纲」
- B3-B7: POST /api/v1/outlines/{oid}/replace-confirm（契约 §4.2 返回 dict + §5 错误映射）
  - B3 approved=true → 200 replaced=True；调用形态 confirm_replace(oid, approved=True)
  - B4 approved=false → 200 cancelled=True
  - B5 OutlineServiceError → 422「大纲无待确认的覆盖操作」
  - B6 OutlineNotFoundError → 404「大纲不存在」
  - B7 非 UUID 路径 → 404「大纲不存在」

策略同 test_outline_api.py: @patch("inkflow.api.routers.outlines.get_outline_service")
整体替换 Service 获取函数；每个被路由 await 的服务方法显式赋 AsyncMock。

RED 形态（本文件运行时 #669 实现未合入）:
- /outlines/{oid}/replace-confirm 未注册 → 404（B3-B5 状态断言失败；B6/B7 因 detail 为
  "Not Found" 而 detail 断言失败——注意 B6/B7 的 404 状态本身会通过）。
- OutlineGenerateRequest/OutlineGenerationResult 尚无 mode/target_outline_id/
  requires_confirmation（pydantic 默认忽略未知字段）→ B1 在响应字段（KeyError）或
  请求对象字段（AttributeError）缺失处失败。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.outline import (
    GeneratedArc,
    GeneratedOutline,
    GeneratedPlotPoint,
    Outline,
    OutlineGenerationResult,
    PlotPoint,
    StoryArc,
)
from inkflow.domain.ports.outline_errors import OutlineNotFoundError, OutlineServiceError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _outline(name: str, *, project_id: uuid.UUID = PID) -> Outline:
    """构造测试用大纲实体（固定时间戳，便于断言）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description="主线概述",
        sort_order=0,
        created_at=TS,
        updated_at=TS,
    )


def _point(name: str, *, outline_id: uuid.UUID, position: int = 1) -> PlotPoint:
    """构造测试用情节点实体。"""
    return PlotPoint(
        id=uuid.uuid4(),
        outline_id=outline_id,
        project_id=PID,
        name=name,
        type="开篇",
        description="节点描述",
        position=position,
        created_at=TS,
        updated_at=TS,
    )


def _arc(name: str, *, project_id: uuid.UUID = PID) -> StoryArc:
    """构造测试用故事弧线实体。"""
    return StoryArc(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description="弧线说明",
        created_at=TS,
        updated_at=TS,
    )


def _replace_staged_result(*, target_id: uuid.UUID) -> OutlineGenerationResult:
    """构造 replace 模式暂存结果（契约 §4.1 _stage_replace 返回形态）。

    RED 期 OutlineGenerationResult 尚无 requires_confirmation/target_outline_id 字段
    （pydantic 忽略未知字段不报错）；GREEN 期字段生效即同文件翻转。
    """
    return OutlineGenerationResult(
        saved=False,
        outline=None,
        plot_points=[],
        arcs=[],
        preview=GeneratedOutline(
            name=None,
            description="覆盖版大纲描述",
            arcs=[GeneratedArc(name="主线")],
            plot_points=[GeneratedPlotPoint(name="新情节点A", arc="主线")],
        ),
        warnings=[],
        model="deepseek/deepseek-chat",
        requires_confirmation=True,
        target_outline_id=target_id,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock OutlineService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestGenerateReplaceAPI:
    """POST /outlines/generate replace 模式（#669 §5 首段 + 契约 B1/B2）。"""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_replace_staged_response(self, mock_get_svc: MagicMock) -> None:
        """mode=replace → 200 暂存语义（requires_confirmation=True，零写入）+ 请求透传。"""
        svc = _mock_svc(mock_get_svc)
        target_id = uuid.uuid4()
        svc.generate = AsyncMock(return_value=_replace_staged_result(target_id=target_id))

        response = client.post(
            "/api/v1/outlines/generate",
            json={
                "project_id": str(PID),
                "name": "第一卷大纲",
                "mode": "replace",
                "target_outline_id": str(target_id),
            },
        )
        assert response.status_code == 200
        data = response.json()
        # RED: 结果模型尚无 requires_confirmation → KeyError（字段缺失即红）
        assert data["requires_confirmation"] is True
        assert data["saved"] is False
        assert data["outline"] is None
        assert data["point_count"] == 0
        req = svc.generate.await_args.args[0]
        # RED: 请求模型尚无 mode/target_outline_id → AttributeError（字段缺失即红）
        assert req.mode == "replace"
        assert req.target_outline_id == target_id

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_generate_replace_missing_target_422(self, mock_get_svc: MagicMock) -> None:
        """mode=replace 缺 target_outline_id → 422 含「覆盖模式必须指定目标大纲」。"""
        svc = _mock_svc(mock_get_svc)
        # svc.generate 需显式 AsyncMock：RED 期 mode 字段尚不存在（pydantic 忽略）→
        # 请求放行到 generate → 200，状态断言失败即红；GREEN 期 model_validator 在路由内拦截。
        svc.generate = AsyncMock(return_value=_replace_staged_result(target_id=uuid.uuid4()))

        response = client.post(
            "/api/v1/outlines/generate",
            json={"project_id": str(PID), "name": "第一卷大纲", "mode": "replace"},
        )
        assert response.status_code == 422
        # FastAPI 422 detail 为 pydantic 错误数组（msg 形如
        # "Value error, 覆盖模式必须指定目标大纲"），字符串化后做子串判定（逐字文案对齐契约 §1.1）。
        detail = json.dumps(response.json()["detail"], ensure_ascii=False)
        assert "覆盖模式必须指定目标大纲" in detail


class TestReplaceConfirmAPI:
    """POST /outlines/{outline_id}/replace-confirm（#669 §5 新端点 + 契约 B3-B7）。"""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_confirm_replace_approved_true_200(self, mock_get_svc: MagicMock) -> None:
        """approved=true → 200 replaced=True；调用形态 confirm_replace(oid, approved=True)。"""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        svc.confirm_replace = AsyncMock(
            return_value={
                "replaced": True,
                "cancelled": False,
                "outline": outline,
                "plot_points": [_point("新情节点A", outline_id=outline.id, position=1)],
                "arcs": [_arc("主线")],
                "warnings": [],
                "model": "deepseek/deepseek-chat",
            }
        )

        response = client.post(
            f"/api/v1/outlines/{outline.id}/replace-confirm", json={"approved": True}
        )
        # RED: 端点未注册 → 404（route not found）→ 状态断言失败即红
        assert response.status_code == 200
        data = response.json()
        assert data["replaced"] is True
        assert data["cancelled"] is False
        assert data["outline"]["name"] == "第一卷大纲"
        assert data["plot_points"][0]["name"] == "新情节点A"
        assert data["arcs"][0]["name"] == "主线"
        assert data["warnings"] == []
        # 契约 §8 B3：位置参 = 解析后 uuid.UUID 对象，关键字 approved
        svc.confirm_replace.assert_awaited_once_with(outline.id, approved=True)

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_confirm_replace_approved_false_200(self, mock_get_svc: MagicMock) -> None:
        """approved=false → 200 cancelled=True（取消覆盖：空 plot_points/arcs）。"""
        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        svc.confirm_replace = AsyncMock(
            return_value={
                "replaced": False,
                "cancelled": True,
                "outline": outline,
                "plot_points": [],
                "arcs": [],
                "warnings": [],
                "model": "deepseek/deepseek-chat",
            }
        )

        response = client.post(
            f"/api/v1/outlines/{outline.id}/replace-confirm", json={"approved": False}
        )
        # RED: 端点未注册 → 404 → 状态断言失败即红
        assert response.status_code == 200
        data = response.json()
        assert data["replaced"] is False
        assert data["cancelled"] is True
        assert data["plot_points"] == []
        svc.confirm_replace.assert_awaited_once_with(outline.id, approved=False)

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_confirm_replace_no_pending_422(self, mock_get_svc: MagicMock) -> None:
        """confirm 时大纲无待确认覆盖（OutlineReplaceError → 422「大纲无待确认的覆盖操作」）。"""
        svc = _mock_svc(mock_get_svc)
        # 契约 §3 OutlineReplaceError 为 OutlineServiceError 子类（GREEN 新增，RED 期不存在）——
        # 以基类 + 契约逐字文案触发同一映射路径（_run_service: OutlineServiceError → 422）。
        svc.confirm_replace = AsyncMock(side_effect=OutlineServiceError("大纲无待确认的覆盖操作"))

        response = client.post(
            f"/api/v1/outlines/{uuid.uuid4()}/replace-confirm", json={"approved": True}
        )
        # RED: 端点未注册 → 404 → 状态断言失败即红
        assert response.status_code == 422
        assert response.json()["detail"] == "大纲无待确认的覆盖操作"

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_confirm_replace_outline_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """confirm 目标大纲不存在（OutlineNotFoundError）→ 404「大纲不存在」。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm_replace = AsyncMock(side_effect=OutlineNotFoundError())

        response = client.post(
            f"/api/v1/outlines/{uuid.uuid4()}/replace-confirm", json={"approved": True}
        )
        assert response.status_code == 404
        # RED: 端点未注册 → 404 detail "Not Found" → detail 断言失败即红
        assert response.json()["detail"] == "大纲不存在"

    def test_confirm_replace_invalid_uuid_404(self) -> None:
        """路径参数非 UUID → 404「大纲不存在」（§5 _parse_id detail）。"""
        response = client.post(
            "/api/v1/outlines/not-a-uuid/replace-confirm", json={"approved": True}
        )
        assert response.status_code == 404
        # RED: 端点未注册 → 404 detail "Not Found" → detail 断言失败即红
        assert response.json()["detail"] == "大纲不存在"


class TestConfirmReplaceHandlerDirect:
    """D1【G｜supp】直接调用 router 函数（非 HTTP 层）：#177 先例盲区——TestClient 在 worker 线程
    跑 handler，function-coverage 采集（主线程 trace）不计；本用例主线程直调补触达。"""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    async def test_confirm_replace_handler_direct_serializes_payload(
        self, mock_get_svc: MagicMock
    ) -> None:
        """直调 confirm_replace_outline：载荷 model_dump 序列化各键 + 透传形态。"""
        from inkflow.api.routers.outlines import ReplaceConfirmBody, confirm_replace_outline

        svc = _mock_svc(mock_get_svc)
        outline = _outline("第一卷大纲")
        point = _point("新情节点A", outline_id=outline.id, position=1)
        arc = _arc("主线")
        svc.confirm_replace = AsyncMock(
            return_value={
                "replaced": True,
                "cancelled": False,
                "outline": outline,
                "plot_points": [point],
                "arcs": [arc],
                "warnings": ["w"],
                "model": "m",
            }
        )
        result = await confirm_replace_outline(
            str(outline.id), ReplaceConfirmBody(approved=True), db=MagicMock()
        )
        assert result["replaced"] is True
        assert result["outline"]["id"] == str(outline.id)
        assert result["plot_points"][0]["name"] == "新情节点A"
        assert result["arcs"][0]["name"] == "主线"
        assert result["warnings"] == ["w"]
        assert result["model"] == "m"
        svc.confirm_replace.assert_awaited_once_with(outline.id, approved=True)
