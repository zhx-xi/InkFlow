"""#1420 RED 契约 —— GET /api/v1/audit-logs/{log_id}（审计记录明细读口）.

覆盖:
- 200: AuditLogDetail 全字段（轻量记录元信息 + findings，spec §3.2 形态）
- 200: findings 为空列表（旧记录/降级）不 404
- 404: AuditLogNotFoundError →「审计记录不存在」（消息即 detail）
- 404: 非法 log_id（非 UUID/非整数）→「审计记录不存在」，不进服务层
- 整数形态 log_id（ORM 自增主键回退解析，镜像 _parse_id）→ 进入服务层
- 500: 其余异常 →「内部错误: ...」

设计假设（GREEN 实现必须满足的契约）:
1. 路由落点 `inkflow.api.routers.chapter_audit`，路径 `/audit-logs/{log_id}`
   （router prefix=/api/v1）。**无项目段**——超时场景下客户端只有 log id。
2. 服务取用 = 模块级 `get_chapter_audit_service(db)`（无项目上下文，
   不走需要 project_id 的 `_get_svc`）→ 单测 patch
   `inkflow.api.routers.chapter_audit.get_chapter_audit_service` 生效。
3. 返回体 = `AuditLogDetail.model_dump(mode="json")`（扁平，非信封）。
4. 异常映射复用 `_run_service`：新增 `AuditLogNotFoundError → 404`。

依据: issue #1420 + specs/f34-chapter-audit/spec.md §3.1/§3.2/§3.3（v1.4 演进留痕）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditLogDetail,
    AuditSeverity,
    ChapterAuditFinding,
)
from inkflow.domain.ports.chapter_audit_errors import AuditLogNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
CHAR_ID = uuid.UUID("0c000000-0000-4000-8000-00000000000c")
TS = datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC)

PATCH_TARGET = "inkflow.api.routers.chapter_audit.get_chapter_audit_service"


def _parse_iso(value: str) -> datetime:
    """解析 ISO 时间戳（兼容 Z / +00:00 两种 pydantic 序列化形态）。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _detail(**overrides: object) -> AuditLogDetail:
    """构造读口返回明细（轻量记录 + findings，spec §3.2 形态）。"""
    kwargs: dict[str, object] = {
        "id": LOG_ID,
        "project_id": PID,
        "chapter_id": CID,
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "1 error, 1 warnings, 0 info",
        "summary": "",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
        "findings": [
            ChapterAuditFinding(
                check_type=AuditCheckType.CHARACTER_DRIFT,
                severity=AuditSeverity.ERROR,
                message="角色行为疑似与人设冲突",
                suggestion="可改为隐忍不发",
                ref_entity_id=CHAR_ID,
                ref_entity_name="角色甲",
                context="节选片段",
            )
        ],
    }
    kwargs.update(overrides)
    return AuditLogDetail(**kwargs)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock ChapterAuditService（patch 工厂返回它）。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestGetAuditLogDetail:
    """GET /audit-logs/{log_id} — 按记录 ID 取回审计明细（#1420 方案 2 读口）。"""

    @patch(PATCH_TARGET)
    def test_get_detail_200_full_fields(self, mock_get_svc: MagicMock) -> None:
        """命中 → 200 + 轻量记录元信息 + findings 全字段。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_log = AsyncMock(return_value=_detail())

        response = client.get(f"/api/v1/audit-logs/{LOG_ID}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(LOG_ID)
        assert data["project_id"] == str(PID)
        assert data["chapter_id"] == str(CID)
        assert data["chapter_title"] == "第 3 章 龙的苏醒"
        assert data["status"] == "pending"
        assert data["severity_summary"] == "1 error, 1 warnings, 0 info"
        assert data["degraded"] is False
        assert data["confirmed_at"] is None
        assert _parse_iso(data["created_at"]) == TS
        assert len(data["findings"]) == 1
        finding = data["findings"][0]
        assert finding["check_type"] == "character_drift"
        assert finding["severity"] == "error"
        assert finding["message"] == "角色行为疑似与人设冲突"
        assert finding["suggestion"] == "可改为隐忍不发"
        assert finding["ref_entity_id"] == str(CHAR_ID)
        assert finding["ref_entity_name"] == "角色甲"
        assert finding["context"] == "节选片段"
        svc.get_log.assert_awaited_once_with(LOG_ID)

    @patch(PATCH_TARGET)
    def test_get_detail_empty_findings_200(self, mock_get_svc: MagicMock) -> None:
        """findings 为空（旧记录/降级）→ 仍 200，不 404。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_log = AsyncMock(return_value=_detail(findings=[]))

        response = client.get(f"/api/v1/audit-logs/{LOG_ID}")

        assert response.status_code == 200
        assert response.json()["findings"] == []

    @patch(PATCH_TARGET)
    def test_get_detail_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """记录不存在 → 404「审计记录不存在」（消息即 detail）。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_log = AsyncMock(side_effect=AuditLogNotFoundError())

        response = client.get(f"/api/v1/audit-logs/{LOG_ID}")

        assert response.status_code == 404
        assert response.json()["detail"] == "审计记录不存在"

    @patch(PATCH_TARGET)
    def test_get_detail_invalid_uuid_404(self, mock_get_svc: MagicMock) -> None:
        """非法 log_id → 404「审计记录不存在」，不进服务层。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_log = AsyncMock(return_value=_detail())

        response = client.get("/api/v1/audit-logs/not-a-log-id")

        assert response.status_code == 404
        assert response.json()["detail"] == "审计记录不存在"
        svc.get_log.assert_not_awaited()

    @patch(PATCH_TARGET)
    def test_get_detail_integer_log_id_parsed(self, mock_get_svc: MagicMock) -> None:
        """整数形态 log_id（ORM 自增主键回退）→ uuid.UUID(int=1) 进服务层。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_log = AsyncMock(return_value=_detail())

        response = client.get("/api/v1/audit-logs/1")

        assert response.status_code == 200
        svc.get_log.assert_awaited_once_with(uuid.UUID(int=1))

    @patch(PATCH_TARGET)
    def test_get_detail_internal_error_500(self, mock_get_svc: MagicMock) -> None:
        """其余异常 → 500「内部错误: ...」（spec §3.3 兜底）。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_log = AsyncMock(side_effect=RuntimeError("内核炸了"))

        response = client.get(f"/api/v1/audit-logs/{LOG_ID}")

        assert response.status_code == 500
        assert response.json()["detail"] == "内部错误: 内核炸了"
