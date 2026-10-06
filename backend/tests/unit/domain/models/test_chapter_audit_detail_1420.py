"""#1420 RED 契约 —— AuditLog（Q1=C 轻量记录）与 AuditLogDetail 模型边界.

契约:
- `AuditLog` **字段集零变化**（Q1=C 摘要级落库，无 findings 明细）——
  反例守护：新增读口不得把 findings 塞进轻量记录实体（否则
  `GET /projects/{pid}/audit-logs` 列表响应会随 findings 膨胀）。
- 新增 `AuditLogDetail(AuditLog)`：轻量记录 + `findings: list[ChapterAuditFinding]`，
  默认空列表；仅读口 `GET /api/v1/audit-logs/{log_id}` 返回该形态。
- findings 元素沿用既有 `ChapterAuditFinding`（不新增并行模型）。

依据: issue #1420 + specs/f34-chapter-audit/spec.md §2.3（v1.4 演进留痕）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditLog,
    AuditLogDetail,
    AuditSeverity,
    ChapterAuditFinding,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
TS = datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC)

_QLC_LIGHT_FIELDS = {
    "id",
    "project_id",
    "chapter_id",
    "chapter_title",
    "status",
    "severity_summary",
    "summary",
    "degraded",
    "note",
    "created_at",
    "confirmed_at",
}

_ASYNC_FIELDS_1425 = {"run_status", "error"}
"""#1425 增补字段（执行态 + 失败原因）——加法式演进，v1.4 字段集不得因此被替换。"""


def _log_kwargs() -> dict:
    return {
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
    }


def _finding() -> ChapterAuditFinding:
    return ChapterAuditFinding(
        check_type=AuditCheckType.CHARACTER_DRIFT,
        severity=AuditSeverity.ERROR,
        message="角色行为疑似与人设冲突",
        suggestion="可改为隐忍不发",
        ref_entity_name="角色甲",
    )


def test_audit_log_field_set_unchanged() -> None:
    """反例守护：v1.4（#1420）字段集**只增不减**（D11 向后兼容）.

    #1425 增补 `run_status` / `error`（执行态 + 失败原因）——加法式演进，
    v1.4 的 11 个字段一个都不能少（含「不得混入 findings 明细」）。
    """
    assert set(AuditLog.model_fields) >= _QLC_LIGHT_FIELDS
    assert set(AuditLog.model_fields) == _QLC_LIGHT_FIELDS | _ASYNC_FIELDS_1425


def test_audit_log_dump_has_no_findings_key() -> None:
    """反例守护：轻量记录序列化不得出现 findings 键（列表响应形态不变）."""
    assert "findings" not in AuditLog(**_log_kwargs()).model_dump(mode="json")


def test_audit_log_detail_extends_light_record_with_findings() -> None:
    """AuditLogDetail = 轻量记录字段集 + findings（读口专用形态）."""
    assert set(AuditLogDetail.model_fields) == set(AuditLog.model_fields) | {"findings"}
    assert issubclass(AuditLogDetail, AuditLog)


def test_audit_log_detail_findings_default_empty() -> None:
    """findings 默认空列表（旧记录/未落明细时不炸）."""
    detail = AuditLogDetail(**_log_kwargs())
    assert detail.findings == []


def test_audit_log_detail_roundtrip_findings() -> None:
    """findings 逐字段可序列化往返（check_type/severity/ref_entity_id/context 全保留）."""
    ref_id = uuid.UUID("0c000000-0000-4000-8000-00000000000c")
    detail = AuditLogDetail(
        **_log_kwargs(),
        findings=[
            ChapterAuditFinding(
                check_type=AuditCheckType.WORD_COUNT,
                severity=AuditSeverity.INFO,
                message="本章 2,845 字，低于目标 3,000 字",
                ref_entity_id=ref_id,
                context="节选片段",
            )
        ],
    )

    payload = detail.model_dump(mode="json")
    assert payload["findings"][0]["check_type"] == "word_count"
    assert payload["findings"][0]["severity"] == "info"
    assert payload["findings"][0]["ref_entity_id"] == str(ref_id)
    assert payload["findings"][0]["context"] == "节选片段"
    # 轻量字段仍在（读口返回记录元信息 + 明细）
    assert payload["severity_summary"] == "1 error, 1 warnings, 0 info"
    assert payload["id"] == str(LOG_ID)
