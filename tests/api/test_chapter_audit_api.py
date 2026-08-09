"""F34 章节审计 REST API 测试契约 — TDD RED 阶段（Issue #208，spec v1.1）。

覆盖（specs/f34-chapter-audit/spec.md §3 端点总览 / §3.2 请求响应示例 /
§3.3 异常映射表 / §7 E1/E9/E15 / §9.1 API 层 / §9.2 关键场景 8）:

- POST /api/v1/projects/{project_id}/chapters/{chapter_id}/audit
  - 200: ChapterAuditReport 全字段（chapter_id/chapter_title/status/findings
    结构/summary/degraded/created_at/confirmed_at=null，spec §3.2 示例）
  - include_static=False 请求体透传（spec §2.4 AuditTriggerRequest）
  - 404: ProjectNotFoundError →「项目不存在」/ ChapterNotFoundError →「章节不存在」
  - 404: 无效 project_id / chapter_id（spec §3.3 无效 UUID → 404 语义）
  - 500: 其余异常 →「内部错误: ...」（spec §3.3）
- POST /api/v1/projects/{project_id}/chapters/{chapter_id}/audit/confirm
  - 200: {"status": "accepted", "confirmed_at": ...}（AuditLog 映射，spec §3.2）
  - 422: NoPendingAuditError →「该章无待确认审计」（spec §3.3 / E9）
  - 422: action 非法 / action 缺失（Pydantic DTO 校验，spec §2.4）
  - 404: 无效 project_id / chapter_id（路径两段独立解析）
- GET  /api/v1/projects/{project_id}/audit-logs
  - 200: {"total": int, "logs": [AuditLog...]}（spec §3.2，Q1=C 可追溯入口）
  - 422: limit > 100 / limit < 1 / offset < 0（spec §7 E15 分页越界）
  - 404: 无效 project_id / 项目不存在

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】镜像 tests/api/test_chapter_api.py 的 mock 服务层模式：
   模块级 `client = TestClient(app)` + 逐用例
   `@patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")`
   ——patch 目标为 router 模块命名空间中的服务工厂（GREEN 时 router 的
   `_get_svc(db)` 经该名字取服务，同 F15 api/routers/audit.py 先例）。
2. 【模块契约】`inkflow.api.routers.chapter_audit` 必须暴露
   `router = APIRouter(prefix="/api/v1", tags=["章节审计"])`
   （app.py 需 include_router）与模块级工厂 `get_chapter_audit_service(db)`
   （deps.py 装配 ChapterAuditService，spec §8.1 MODIFY deps.py）。
3. 【服务契约（定死，防并行分歧）】`ChapterAuditService`：
   - async audit(project_id, chapter_id, *, include_static=True) -> ChapterAuditReport
   - async confirm(project_id, chapter_id, *, action, note="") -> AuditLog
   - async list_logs(project_id, *, offset=0, limit=20) -> tuple[list[AuditLog], int]
   router 必须以关键字透传 include_static/action/note/offset/limit
   （服务签名带 *，位置调用非法）。
4. 【错误映射（spec §3.3，文案 = 错误类消息）】ProjectNotFoundError → 404
   「项目不存在」；ChapterNotFoundError → 404「章节不存在」（复用 F9/F14
   错误类）；NoPendingAuditError → 422「该章无待确认审计」（新错误类
   inkflow.domain.ports.chapter_audit_errors）；其余异常 → 500「内部错误: ...」。
5. 【无效 UUID】project_id/chapter_id 非 UUID → 404（不 422）；audit 与
   confirm 端点各自独立解析两段路径参数，分别报「项目不存在」/「章节不存在」。
6. 【确认响应】POST confirm → 200 {status, confirmed_at}：status =
   AuditLog.status（accepted/rejected），confirmed_at = AuditLog.confirmed_at
   （无确认时为 null）。本文件只断言两键存在与值语义，容忍额外字段。
7. 【audit-logs 分页】limit Query 默认 20、ge=1、le=100；offset Query
   默认 0、ge=0；越界 422（FastAPI Query 校验，service 不被调用）。
8. 【RED 形态】inkflow.domain.models.chapter_audit 尚不存在 → 本文件顶部
   import 在【收集期】抛 ModuleNotFoundError（collected 0 items）；
   inkflow.domain.ports.chapter_audit_errors 同缺（NoPendingAuditError
   顶部 import 位于 models 之后——收集期错误先报 models，符合预期渐进 RED）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditLog,
    AuditSeverity,
    ChapterAuditFinding,
    ChapterAuditReport,
)
from inkflow.domain.ports.chapter_audit_errors import NoPendingAuditError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
CHAR_ID = uuid.UUID("0c000000-0000-4000-8000-00000000000c")
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
TS = datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC)
CONFIRMED_TS = datetime(2026, 8, 9, 10, 5, 0, tzinfo=UTC)


def _parse_iso(value: str) -> datetime:
    """解析 ISO 时间戳（兼容 Z / +00:00 两种 pydantic 序列化形态）。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _finding(**overrides: object) -> ChapterAuditFinding:
    """构造单条审计发现（默认 character_drift ERROR，spec §3.2 示例同款）。"""
    kwargs: dict[str, object] = {
        "check_type": AuditCheckType.CHARACTER_DRIFT,
        "severity": AuditSeverity.ERROR,
        "message": "本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」，行为可能与人设冲突",
        "suggestion": "可改为隐忍不发，或先铺垫情绪积累",
        "ref_entity_id": CHAR_ID,
        "ref_entity_name": "李青焰",
        "context": "“够了！”李青焰猛地拍案而起，怒视众人……",
    }
    kwargs.update(overrides)
    return ChapterAuditFinding(**kwargs)


def _report(**overrides: object) -> ChapterAuditReport:
    """构造完整 ChapterAuditReport（spec §2.2 模型 / §3.2 响应示例）。"""
    kwargs: dict[str, object] = {
        "chapter_id": CID,
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "findings": [
            _finding(),
            _finding(
                check_type=AuditCheckType.WORD_COUNT,
                severity=AuditSeverity.INFO,
                message="本章 2,845 字，低于目标 3,000 字",
                suggestion="",
                ref_entity_id=None,
                ref_entity_name="",
                context="",
            ),
        ],
        "summary": "本章整体符合设定，一处角色行为值得斟酌",
        "degraded": False,
        "created_at": TS,
        "confirmed_at": None,
    }
    kwargs.update(overrides)
    return ChapterAuditReport(**kwargs)


def _log(**overrides: object) -> AuditLog:
    """构造审计轻量记录（spec §2.3 AuditLog）。"""
    kwargs: dict[str, object] = {
        "id": LOG_ID,
        "project_id": PID,
        "chapter_id": CID,
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "1 error, 2 warnings, 0 info",
        "summary": "本章整体符合设定，一处角色行为值得斟酌",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
    }
    kwargs.update(overrides)
    return AuditLog(**kwargs)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock ChapterAuditService（patch 工厂返回它）。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestTriggerAudit:
    """POST /projects/{pid}/chapters/{cid}/audit — 手动触发审计（spec §3.1）。"""

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_trigger_audit_200_report_fields(self, mock_get_svc: MagicMock) -> None:
        """触发成功 → 200 + ChapterAuditReport 全字段（confirmed_at=null，spec §3.2）。"""
        svc = _mock_svc(mock_get_svc)
        report = _report()
        svc.audit = AsyncMock(return_value=report)

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["chapter_id"] == str(CID)
        assert data["chapter_title"] == "第 3 章 龙的苏醒"
        assert data["status"] == "pending"
        assert data["summary"] == "本章整体符合设定，一处角色行为值得斟酌"
        assert data["degraded"] is False
        assert data["confirmed_at"] is None
        assert _parse_iso(data["created_at"]) == TS
        # findings 结构（check_type/severity/message/suggestion/ref_entity_id/
        # ref_entity_name/context，spec §2.2）
        assert len(data["findings"]) == 2
        f0 = data["findings"][0]
        assert f0["check_type"] == "character_drift"
        assert f0["severity"] == "error"
        assert f0["message"].startswith("本章「李青焰」怒斥同伴")
        assert f0["suggestion"] == "可改为隐忍不发，或先铺垫情绪积累"
        assert f0["ref_entity_id"] == str(CHAR_ID)
        assert f0["ref_entity_name"] == "李青焰"
        assert f0["context"].startswith("“够了！”")
        f1 = data["findings"][1]
        assert f1["check_type"] == "word_count"
        assert f1["severity"] == "info"
        assert f1["ref_entity_id"] is None
        assert f1["ref_entity_name"] == ""
        assert f1["context"] == ""
        svc.audit.assert_awaited_once_with(PID, CID, include_static=True)

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_trigger_audit_include_static_false_passthrough(
        self, mock_get_svc: MagicMock
    ) -> None:
        """include_static=False 请求体透传（spec §2.4 AuditTriggerRequest）。"""
        svc = _mock_svc(mock_get_svc)
        svc.audit = AsyncMock(return_value=_report())

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/{CID}/audit",
            json={"include_static": False},
        )

        assert response.status_code == 200
        svc.audit.assert_awaited_once_with(PID, CID, include_static=False)

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_trigger_audit_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在 → 404「项目不存在」（spec §3.3，复用 F9 ProjectNotFoundError）。"""
        svc = _mock_svc(mock_get_svc)
        svc.audit = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_trigger_audit_chapter_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """章节不存在 → 404「章节不存在」（spec §3.3，复用 F14 ChapterNotFoundError）。"""
        svc = _mock_svc(mock_get_svc)
        svc.audit = AsyncMock(side_effect=ChapterNotFoundError())

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_trigger_audit_invalid_project_uuid_404(
        self, mock_get_svc: MagicMock
    ) -> None:
        """无效 project_id → 404「项目不存在」（不进服务，spec §3.3 无效 UUID 语义）。"""
        svc = _mock_svc(mock_get_svc)
        svc.audit = AsyncMock(return_value=_report())

        response = client.post(
            f"/api/v1/projects/not-a-uuid/chapters/{CID}/audit", json={}
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        svc.audit.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_trigger_audit_invalid_chapter_uuid_404(
        self, mock_get_svc: MagicMock
    ) -> None:
        """无效 chapter_id → 404「章节不存在」（路径两段独立解析）。"""
        svc = _mock_svc(mock_get_svc)
        svc.audit = AsyncMock(return_value=_report())

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/not-a-uuid/audit", json={}
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"
        svc.audit.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_trigger_audit_internal_error_500(self, mock_get_svc: MagicMock) -> None:
        """其余异常 → 500「内部错误: ...」（spec §3.3）。"""
        svc = _mock_svc(mock_get_svc)
        svc.audit = AsyncMock(side_effect=RuntimeError("内核炸了"))

        response = client.post(f"/api/v1/projects/{PID}/chapters/{CID}/audit", json={})

        assert response.status_code == 500
        assert response.json()["detail"] == "内部错误: 内核炸了"


class TestConfirmAudit:
    """POST /projects/{pid}/chapters/{cid}/audit/confirm — 用户确认（Q2=B 双入口）。"""

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_confirm_accept_200(self, mock_get_svc: MagicMock) -> None:
        """accept → 200 {status: accepted, confirmed_at}（spec §3.2）。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm = AsyncMock(
            return_value=_log(status="accepted", confirmed_at=CONFIRMED_TS)
        )

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/{CID}/audit/confirm",
            json={"action": "accept"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert _parse_iso(data["confirmed_at"]) == CONFIRMED_TS
        svc.confirm.assert_awaited_once_with(PID, CID, action="accept", note="")

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_confirm_reject_with_note_200(self, mock_get_svc: MagicMock) -> None:
        """reject + note → 200 {status: rejected}，note 透传落库（spec §2.4）。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm = AsyncMock(
            return_value=_log(
                status="rejected", confirmed_at=CONFIRMED_TS, note="人设需再打磨"
            )
        )

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/{CID}/audit/confirm",
            json={"action": "reject", "note": "人设需再打磨"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        svc.confirm.assert_awaited_once_with(
            PID, CID, action="reject", note="人设需再打磨"
        )

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_confirm_no_pending_422(self, mock_get_svc: MagicMock) -> None:
        """无待确认审计 → 422「该章无待确认审计」（spec §3.3 / E9）。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm = AsyncMock(side_effect=NoPendingAuditError())

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/{CID}/audit/confirm",
            json={"action": "accept"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "该章无待确认审计"

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_confirm_invalid_action_422(self, mock_get_svc: MagicMock) -> None:
        """action 非法（非 accept/reject）→ 422 Pydantic 校验（spec §3.3 DTO 层）。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm = AsyncMock(
            return_value=_log(status="accepted", confirmed_at=CONFIRMED_TS)
        )

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/{CID}/audit/confirm",
            json={"action": "xxx"},
        )

        assert response.status_code == 422
        assert "action" in str(response.json()["detail"])
        svc.confirm.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_confirm_missing_action_422(self, mock_get_svc: MagicMock) -> None:
        """action 缺失（必填）→ 422 Pydantic 校验（spec §2.4 AuditConfirmRequest）。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm = AsyncMock(
            return_value=_log(status="accepted", confirmed_at=CONFIRMED_TS)
        )

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/{CID}/audit/confirm", json={}
        )

        assert response.status_code == 422
        assert "action" in str(response.json()["detail"])
        svc.confirm.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_confirm_invalid_project_uuid_404(self, mock_get_svc: MagicMock) -> None:
        """无效 project_id → 404「项目不存在」（不进服务）。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm = AsyncMock(
            return_value=_log(status="accepted", confirmed_at=CONFIRMED_TS)
        )

        response = client.post(
            f"/api/v1/projects/not-a-uuid/chapters/{CID}/audit/confirm",
            json={"action": "accept"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        svc.confirm.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_confirm_invalid_chapter_uuid_404(self, mock_get_svc: MagicMock) -> None:
        """无效 chapter_id → 404「章节不存在」（路径两段独立解析）。"""
        svc = _mock_svc(mock_get_svc)
        svc.confirm = AsyncMock(
            return_value=_log(status="accepted", confirmed_at=CONFIRMED_TS)
        )

        response = client.post(
            f"/api/v1/projects/{PID}/chapters/not-a-uuid/audit/confirm",
            json={"action": "accept"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"
        svc.confirm.assert_not_awaited()


class TestAuditLogs:
    """GET /projects/{pid}/audit-logs — 审计记录查询（Q1=C 可追溯入口）。"""

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_list_audit_logs_200(self, mock_get_svc: MagicMock) -> None:
        """记录列表 → 200 {total, logs}（spec §3.2；默认分页 offset=0 limit=20）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(return_value=([_log()], 1))

        response = client.get(f"/api/v1/projects/{PID}/audit-logs")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["logs"]) == 1
        log = data["logs"][0]
        assert log["id"] == str(LOG_ID)
        assert log["chapter_title"] == "第 3 章 龙的苏醒"
        assert log["status"] == "pending"
        assert log["severity_summary"] == "1 error, 2 warnings, 0 info"
        assert log["summary"] == "本章整体符合设定，一处角色行为值得斟酌"
        assert log["degraded"] is False
        assert log["note"] == ""
        assert log["confirmed_at"] is None
        assert _parse_iso(log["created_at"]) == TS
        svc.list_logs.assert_awaited_once_with(PID, offset=0, limit=20)

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_list_audit_logs_explicit_pagination(self, mock_get_svc: MagicMock) -> None:
        """显式 limit/offset 透传（spec §7 E15 分页契约）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/audit-logs", params={"limit": 5, "offset": 1}
        )

        assert response.status_code == 200
        assert response.json()["total"] == 0
        svc.list_logs.assert_awaited_once_with(PID, offset=1, limit=5)

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_list_audit_logs_limit_101_422(self, mock_get_svc: MagicMock) -> None:
        """limit=101（> 最大 100）→ 422（spec §7 E15，service 不被调用）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/audit-logs", params={"limit": 101}
        )

        assert response.status_code == 422
        svc.list_logs.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_list_audit_logs_limit_negative_422(self, mock_get_svc: MagicMock) -> None:
        """limit=-1（< 1）→ 422（spec §7 E15）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/audit-logs", params={"limit": -1}
        )

        assert response.status_code == 422
        svc.list_logs.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_list_audit_logs_offset_negative_422(self, mock_get_svc: MagicMock) -> None:
        """offset=-1（< 0）→ 422（spec §7 E15）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/audit-logs", params={"offset": -1}
        )

        assert response.status_code == 422
        svc.list_logs.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_list_audit_logs_invalid_project_uuid_404(
        self, mock_get_svc: MagicMock
    ) -> None:
        """无效 project_id → 404「项目不存在」（不进服务）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(return_value=([], 0))

        response = client.get("/api/v1/projects/not-a-uuid/audit-logs")

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        svc.list_logs.assert_not_awaited()

    @patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")
    def test_list_audit_logs_project_not_found_404(
        self, mock_get_svc: MagicMock
    ) -> None:
        """项目不存在 → 404「项目不存在」（spec §3.3）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.get(f"/api/v1/projects/{PID}/audit-logs")

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
