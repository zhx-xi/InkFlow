"""F15 一致性审计 API 测试 — Mock AuditService（M6 RED→GREEN）。

测试范围 (spec §9 API 测试 + §3.3 异常映射表):
- GET /api/v1/projects/{project_id}/audit 成功路径（200 + AuditReport 信封序列化）
- 响应结构完整性（project_id / generated_at / summary / findings / timeline_check）
- 404 项目不存在（ProjectNotFoundError → 404「项目不存在」）
- 无效 UUID 格式 → 404（统一 _parse_id 处理，同 F9-F14）
- 500 透传（任一档案仓储读取失败 / 委托 F12 失败 → 500「内部错误: ...」）
- 幂等性（同一数据两次 GET 响应体逐字段相等，spec §6.4）

策略: @patch("inkflow.api.routers.audit.get_audit_service")
整体替换 Service 获取函数（router 模块级本地引用），被路由 await 的
run_audit 显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await
会返回 coroutine 导致 500（F4 4.1 实测陷阱）。

依据: specs/f15-audit-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.audit import (
    AuditDimension,
    AuditFinding,
    AuditReport,
    AuditSeverity,
    AuditSummary,
    DimensionSummary,
)
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineConflict,
    TimelineEventRef,
)
from inkflow.domain.ports.audit_errors import ProjectNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)


def _finding(**overrides: object) -> AuditFinding:
    """构造测试用 AuditFinding（默认 error 级关系悬空引用）。"""
    kwargs: dict[str, object] = {
        "id": "character.relation_ref:7a4f2c91-0000-4000-8000-000000000001",
        "rule_id": "character.relation_ref",
        "dimension": AuditDimension.CHARACTER,
        "severity": AuditSeverity.ERROR,
        "message": "关系 林晚→?? 的 to 端指向不存在的角色（悬空引用，请删除该关系或恢复目标角色）",
        "entity_type": "relation",
        "entity_id": uuid.UUID("7a4f2c91-0000-4000-8000-000000000001"),
        "entity_name": "林晚→??",
        "ref_type": "character",
        "ref_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "data": {
            "relation_type": "敌对",
            "from_character_id": "9b1c2d3e-0000-4000-8000-000000000001",
        },
    }
    kwargs.update(overrides)
    return AuditFinding(**kwargs)  # type: ignore[arg-type]


def _timeline_check() -> ConsistencyReport:
    """构造 F12 ConsistencyReport 嵌套报告（1 条 order_conflict，spec §5.3 透传）。"""
    return ConsistencyReport(
        project_id=PID,
        checked=6,
        skipped=0,
        consistent=False,
        conflicts=[
            TimelineConflict(
                conflict_type="order_conflict",
                prev=TimelineEventRef(
                    id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
                    title="林晚入宫",
                    time_value=5.0,
                    time_display="",
                    narrative_position=1,
                    timeline_flag="",
                ),
                next=TimelineEventRef(
                    id=uuid.UUID("4a5b6c7d-0000-4000-8000-000000000001"),
                    title="外门往事",
                    time_value=3.0,
                    time_display="",
                    narrative_position=2,
                    timeline_flag="",
                ),
                message=(
                    "叙事顺序中「林晚入宫」之后是「外门往事」，但世界内时间 5.0 > 3.0"
                    "——时间倒流（未声明倒叙）"
                ),
            )
        ],
        flashbacks=[],
        event_timeline=[],
        narrative_order=[],
    )


def _report(**overrides: object) -> AuditReport:
    """构造不一致 AuditReport（1 error / 1 warning / 2 info + 嵌套时间线报告）。"""
    findings = [
        _finding(),
        _finding(
            id="foreshadowing.event_anchor:1a2b3c4d-0000-4000-8000-000000000001",
            rule_id="foreshadowing.event_anchor",
            dimension=AuditDimension.FORESHADOWING,
            severity=AuditSeverity.WARNING,
            message=(
                "伏笔「铜镜的秘密」锚点事件已软删（锚点保留但事件不在时间线视图中，"
                "请确认是否需解除挂接）"
            ),
            entity_type="foreshadowing",
            entity_id=uuid.UUID("1a2b3c4d-0000-4000-8000-000000000001"),
            entity_name="铜镜的秘密",
            ref_type="event",
            ref_id=uuid.UUID("8e9f0a1b-0000-4000-8000-000000000001"),
            data={},
        ),
        _finding(
            id="world.archive_gap:3f2e1d4a-0000-4000-8000-000000000001",
            rule_id="world.archive_gap",
            dimension=AuditDimension.WORLD,
            severity=AuditSeverity.INFO,
            message=(
                "项目已有 3 个章节但尚未建立世界观档案"
                "（可运行 inkflow extract run --type setting 提取）"
            ),
            entity_type="project",
            entity_id=None,
            entity_name="测试项目",
            ref_type=None,
            ref_id=None,
            data={},
        ),
        _finding(
            id="extraction.run_gap:5a6b7c8d-0000-4000-8000-000000000001",
            rule_id="extraction.run_gap",
            dimension=AuditDimension.CROSS,
            severity=AuditSeverity.INFO,
            message="章节「第一章」从未执行过提取",
            entity_type="chapter",
            entity_id=uuid.UUID("5a6b7c8d-0000-4000-8000-000000000001"),
            entity_name="第一章",
            ref_type=None,
            ref_id=None,
            data={},
        ),
    ]
    summary = AuditSummary(
        consistent=False,
        total=4,
        by_dimension={
            AuditDimension.CHARACTER: DimensionSummary(error=1, warning=0, info=0),
            AuditDimension.TIMELINE: DimensionSummary(error=0, warning=0, info=0),
            AuditDimension.WORLD: DimensionSummary(error=0, warning=0, info=1),
            AuditDimension.FORESHADOWING: DimensionSummary(error=0, warning=1, info=0),
            AuditDimension.CROSS: DimensionSummary(error=0, warning=0, info=1),
        },
        counts={
            "characters": 3,
            "relations": 2,
            "groups": 1,
            "world_settings": 4,
            "events": 6,
            "foreshadowings": 2,
            "chapters": 3,
            "extraction_runs": 5,
        },
    )
    kwargs: dict[str, object] = {
        "project_id": PID,
        "generated_at": TS,
        "summary": summary,
        "findings": findings,
        "timeline_check": _timeline_check(),
    }
    kwargs.update(overrides)
    return AuditReport(**kwargs)  # type: ignore[arg-type]


def _consistent_report() -> AuditReport:
    """构造完全一致 AuditReport（consistent=true、findings 空、嵌套空时间线报告）。"""
    return AuditReport(
        project_id=PID,
        generated_at=TS,
        summary=AuditSummary(
            consistent=True,
            total=0,
            by_dimension={
                AuditDimension.CHARACTER: DimensionSummary(),
                AuditDimension.TIMELINE: DimensionSummary(),
                AuditDimension.WORLD: DimensionSummary(),
                AuditDimension.FORESHADOWING: DimensionSummary(),
                AuditDimension.CROSS: DimensionSummary(),
            },
            counts={
                "characters": 0,
                "relations": 0,
                "groups": 0,
                "world_settings": 0,
                "events": 0,
                "foreshadowings": 0,
                "chapters": 0,
                "extraction_runs": 0,
            },
        ),
        findings=[],
        timeline_check=ConsistencyReport(
            project_id=PID,
            checked=0,
            skipped=0,
            consistent=True,
            conflicts=[],
            flashbacks=[],
            event_timeline=[],
            narrative_order=[],
        ),
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock AuditService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestAuditAPI:
    """GET /api/v1/projects/{project_id}/audit 端点测试."""

    @patch("inkflow.api.routers.audit.get_audit_service")
    def test_audit_success_200(self, mock_get_svc: MagicMock) -> None:
        """审计成功返回 200 + 完整 AuditReport JSON（信封序列化）。"""
        svc = _mock_svc(mock_get_svc)
        svc.run_audit = AsyncMock(return_value=_report())

        response = client.get(f"/api/v1/projects/{PID}/audit")
        assert response.status_code == 200
        data = response.json()
        # 顶层字段
        assert data["project_id"] == str(PID)
        assert data["generated_at"] == "2026-08-02T12:00:00Z"
        # summary 汇总
        assert data["summary"]["consistent"] is False
        assert data["summary"]["total"] == 4
        assert data["summary"]["by_dimension"]["character"]["error"] == 1
        assert data["summary"]["by_dimension"]["foreshadowing"]["warning"] == 1
        assert data["summary"]["by_dimension"]["world"]["info"] == 1
        assert data["summary"]["counts"]["events"] == 6
        assert data["summary"]["counts"]["extraction_runs"] == 5
        # findings 全字段
        assert len(data["findings"]) == 4
        finding = data["findings"][0]
        assert finding["id"] == "character.relation_ref:7a4f2c91-0000-4000-8000-000000000001"
        assert finding["rule_id"] == "character.relation_ref"
        assert finding["dimension"] == "character"
        assert finding["severity"] == "error"
        assert "悬空引用" in finding["message"]
        assert finding["entity_type"] == "relation"
        assert finding["entity_id"] == "7a4f2c91-0000-4000-8000-000000000001"
        assert finding["entity_name"] == "林晚→??"
        assert finding["ref_type"] == "character"
        assert finding["ref_id"] == "11111111-1111-1111-1111-111111111111"
        assert finding["data"]["relation_type"] == "敌对"
        # timeline_check 嵌套原始报告
        assert data["timeline_check"]["checked"] == 6
        assert data["timeline_check"]["consistent"] is False
        assert data["timeline_check"]["conflicts"][0]["conflict_type"] == "order_conflict"
        svc.run_audit.assert_awaited_once_with(PID)

    @patch("inkflow.api.routers.audit.get_audit_service")
    def test_audit_consistent_report_structure(self, mock_get_svc: MagicMock) -> None:
        """完全一致的项目 → 200 + consistent=true、findings 空、5 维度键齐全。"""
        svc = _mock_svc(mock_get_svc)
        svc.run_audit = AsyncMock(return_value=_consistent_report())

        response = client.get(f"/api/v1/projects/{PID}/audit")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["consistent"] is True
        assert data["summary"]["total"] == 0
        assert data["findings"] == []
        assert data["timeline_check"]["checked"] == 0
        assert data["timeline_check"]["consistent"] is True
        assert set(data["summary"]["by_dimension"].keys()) == {
            "character",
            "timeline",
            "world",
            "foreshadowing",
            "cross",
        }

    @patch("inkflow.api.routers.audit.get_audit_service")
    def test_audit_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在返回 404「项目不存在」（spec §7）。"""
        svc = _mock_svc(mock_get_svc)
        svc.run_audit = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.get(f"/api/v1/projects/{PID}/audit")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.audit.get_audit_service")
    def test_audit_invalid_project_uuid_404(self, mock_get_svc: MagicMock) -> None:
        """无效项目 UUID 格式返回 404「项目不存在」（不进入服务层，spec §3.3）。"""
        svc = _mock_svc(mock_get_svc)
        svc.run_audit = AsyncMock()
        response = client.get("/api/v1/projects/not-a-uuid/audit")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        svc.run_audit.assert_not_awaited()

    @patch("inkflow.api.routers.audit.get_audit_service")
    def test_audit_db_error_500(self, mock_get_svc: MagicMock) -> None:
        """任一档案仓储读取失败 → 500「内部错误: ...」透传（spec §3.3/§7）。"""
        svc = _mock_svc(mock_get_svc)
        svc.run_audit = AsyncMock(side_effect=RuntimeError("数据库读取失败"))

        response = client.get(f"/api/v1/projects/{PID}/audit")
        assert response.status_code == 500
        assert "内部错误" in response.json()["detail"]

    @patch("inkflow.api.routers.audit.get_audit_service")
    def test_audit_idempotent(self, mock_get_svc: MagicMock) -> None:
        """同一数据两次审计 → 响应体逐字段相等（严格幂等，spec §6.4）。"""
        svc = _mock_svc(mock_get_svc)
        svc.run_audit = AsyncMock(return_value=_report())

        first = client.get(f"/api/v1/projects/{PID}/audit")
        second = client.get(f"/api/v1/projects/{PID}/audit")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert svc.run_audit.await_count == 2
