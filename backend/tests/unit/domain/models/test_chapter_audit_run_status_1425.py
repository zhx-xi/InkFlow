"""#1425 RED 契约 —— 异步语义领域模型（AuditRunStatus / AuditLog 新字段 / DTO）.

契约（GREEN 实现必须满足）:
- `AuditRunStatus`（StrEnum）：running / completed / failed。
- `AuditLog` 增 `run_status`（默认 `COMPLETED`——v1.5 前均为同步执行完成）
  与 `error`（默认 `""`）。
- `AuditLogDetail` 继承上述字段（读口形态含执行态）。
- 新增 DTO：`AuditTriggerAccepted`（202 响应 `{log_id, status}`）与
  `AuditRunInfo`（`/status` 轮询响应）。
- 反例守护：v1.4（#1420）既有字段集**只增不改**（D11 契约向后兼容）。

依据: issue #1425 + specs/f34-chapter-audit/spec.md §2.3/§2.4（v1.5）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.chapter_audit import (
    AuditLog,
    AuditLogDetail,
    AuditRunInfo,
    AuditRunStatus,
    AuditTriggerAccepted,
)

TS = datetime(2026, 10, 7, 10, 0, 0, tzinfo=UTC)
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")


def _log(**overrides: object) -> AuditLog:
    """构造最小合法 AuditLog（新字段走默认值）."""
    kwargs: dict[str, object] = {
        "id": LOG_ID,
        "project_id": PID,
        "chapter_id": CID,
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "0 error, 0 warnings, 0 info",
        "created_at": TS,
    }
    kwargs.update(overrides)
    return AuditLog(**kwargs)  # type: ignore[arg-type]  # 测试构造：overrides 为合法字段子集


def test_run_status_enum_values() -> None:
    """AuditRunStatus 三取值（spec §2.3 v1.5）."""
    assert AuditRunStatus.RUNNING.value == "running"
    assert AuditRunStatus.COMPLETED.value == "completed"
    assert AuditRunStatus.FAILED.value == "failed"
    assert {s.value for s in AuditRunStatus} == {"running", "completed", "failed"}


def test_audit_log_defaults_run_status_completed_and_error_empty() -> None:
    """默认 run_status=completed（兼容同步路径/历史行）、error=''（spec §2.3）."""
    log = _log()

    assert log.run_status is AuditRunStatus.COMPLETED
    assert log.error == ""


def test_audit_log_accepts_running_and_error_text() -> None:
    """显式 running + error 可承载（后台执行态）."""
    log = _log(run_status=AuditRunStatus.RUNNING, error="")

    assert log.run_status is AuditRunStatus.RUNNING
    failed = _log(run_status=AuditRunStatus.FAILED, error="审计任务失败: boom")
    assert failed.error == "审计任务失败: boom"


def test_audit_log_detail_inherits_run_status() -> None:
    """AuditLogDetail 继承执行态字段（读口形态）."""
    detail = AuditLogDetail(**_log(run_status=AuditRunStatus.RUNNING).model_dump())

    assert detail.run_status is AuditRunStatus.RUNNING
    assert detail.error == ""
    assert detail.findings == []


def test_audit_log_serializes_run_status_as_lowercase_string() -> None:
    """model_dump(mode='json') 输出小写字符串（API 契约面）."""
    dumped = _log(run_status=AuditRunStatus.FAILED, error="x").model_dump(mode="json")

    assert dumped["run_status"] == "failed"
    assert dumped["error"] == "x"


def test_audit_log_v14_fields_unchanged() -> None:
    """反例守护：v1.4（#1420）字段集只增不改（D11 向后兼容）."""
    dumped = _log().model_dump(mode="json")

    for field in (
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
    ):
        assert field in dumped, f"v1.4 字段 {field} 不得移除"
    assert "findings" not in dumped, "轻量 AuditLog 不得含 findings（列表形态零变化）"


def test_audit_trigger_accepted_dto() -> None:
    """202 响应 DTO：{log_id, status}（spec §2.4）."""
    dto = AuditTriggerAccepted(log_id=LOG_ID, status=AuditRunStatus.RUNNING)

    dumped = dto.model_dump(mode="json")
    assert dumped == {"log_id": str(LOG_ID), "status": "running"}


def test_audit_trigger_accepted_rejects_unknown_status() -> None:
    """status 取值受限（Pydantic 校验）."""
    with pytest.raises(ValidationError):
        AuditTriggerAccepted(log_id=LOG_ID, status="bogus")  # type: ignore[arg-type]  # 反例：非法枚举值


def test_audit_run_info_dto_roundtrip() -> None:
    """轮询读口 DTO 字段齐备（spec §2.4）."""
    info = AuditRunInfo(
        log_id=LOG_ID,
        run_status=AuditRunStatus.COMPLETED,
        status="pending",
        degraded=False,
        error="",
        chapter_id=CID,
        chapter_title="第 3 章 龙的苏醒",
        created_at=TS,
    )

    dumped = info.model_dump(mode="json")
    assert dumped["log_id"] == str(LOG_ID)
    assert dumped["run_status"] == "completed"
    assert dumped["status"] == "pending"
    assert dumped["chapter_id"] == str(CID)
    assert dumped["error"] == ""
