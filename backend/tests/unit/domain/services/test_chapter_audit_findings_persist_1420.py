"""#1420 RED 契约 —— 审计完成后 findings 落库（写入侧）+ 按记录 ID 取回（服务层）.

契约（GREEN 实现必须满足）:
- `ChapterAuditService.audit` 落库时把 `report.findings` 一并交给仓储
  （`add(log, findings=report.findings)`）——与 POST /audit 响应体同源同内容，
  客户端超时（响应丢弃）后仍可按记录 ID 取回。
- 新增 `ChapterAuditService.get_log(log_id) -> AuditLogDetail`：命中透传仓储结果；
  不存在 → 抛 `AuditLogNotFoundError`（API 层映射 404）。
- 反例守护：audit 的返回报告与既有轻量记录字段（severity_summary/summary/degraded/
  status/created_at）零变化。

依据: issue #1420 + specs/f34-chapter-audit/spec.md §5.1/§8.1（v1.4 演进留痕）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.chapter import Chapter, ChapterStatus
from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditLog,
    AuditLogDetail,
    AuditSeverity,
    ChapterAuditFinding,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.chapter_audit_errors import AuditLogNotFoundError
from inkflow.domain.services.chapter_audit_service import ChapterAuditService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _project(target_words: int = 3000) -> Project:
    """构造测试项目（config.default_words = 章节目标字数）."""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(default_words=target_words),
        created_at=TS,
        updated_at=TS,
    )


def _chapter(*, word_count: int = 100) -> Chapter:
    """构造空正文章节（content 为空 → 跳过 LLM 检查，结果确定性）."""
    return Chapter(
        id=CID,
        project_id=PID,
        title="第 3 章 龙的苏醒",
        content="",
        status=ChapterStatus.REVIEW,
        word_count=word_count,
        created_at=TS,
        updated_at=TS,
    )


def _svc(repo_get_result: AuditLogDetail | None = None) -> tuple[ChapterAuditService, MagicMock]:
    """构造服务 + 捕获调用的审计日志仓储 Mock（空档案 → 零 LLM 调用）."""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(return_value=_chapter())
    character_repo = MagicMock()
    character_repo.list = AsyncMock(return_value=([], 0))
    world_repo = MagicMock()
    world_repo.list = AsyncMock(return_value=([], 0))
    audit_service = MagicMock()
    audit_service.run_audit = AsyncMock(return_value=MagicMock(findings=[]))
    llm_client = MagicMock()

    log_repo = MagicMock()
    log_repo.add = AsyncMock(side_effect=lambda log, **kwargs: log)
    log_repo.get = AsyncMock(return_value=repo_get_result)

    service = ChapterAuditService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=character_repo,
        world_repo=world_repo,
        audit_service=audit_service,
        llm_client=llm_client,
        audit_log_repo=log_repo,
    )
    return service, log_repo


async def test_audit_persists_report_findings() -> None:
    """写入侧：audit 落库时 findings == 响应体 report.findings（超时可恢复的根因修复）."""
    service, log_repo = _svc()

    report = await service.audit(PID, CID, include_static=False)

    assert report.findings, "本用例前提：确定性字数检查应产出 1 条 finding"
    log_repo.add.assert_awaited_once()
    call = log_repo.add.await_args
    assert "findings" in call.kwargs, (
        f"audit 落库必须显式传 findings=（与响应体同源）；实际 kwargs: {sorted(call.kwargs)}"
    )
    passed = list(call.kwargs["findings"])
    assert passed == list(report.findings)
    assert passed[0].check_type == AuditCheckType.WORD_COUNT
    assert passed[0].severity == AuditSeverity.INFO


async def test_audit_persists_empty_findings_without_error() -> None:
    """无 findings 的报告（字数在区间内）→ 落库空列表，不抛错."""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(return_value=_chapter(word_count=3000))
    character_repo = MagicMock()
    character_repo.list = AsyncMock(return_value=([], 0))
    world_repo = MagicMock()
    world_repo.list = AsyncMock(return_value=([], 0))
    log_repo = MagicMock()
    log_repo.add = AsyncMock(side_effect=lambda log, **kwargs: log)

    service = ChapterAuditService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=character_repo,
        world_repo=world_repo,
        audit_service=MagicMock(),
        llm_client=MagicMock(),
        audit_log_repo=log_repo,
    )

    report = await service.audit(PID, CID, include_static=False)

    assert report.findings == []
    assert list(log_repo.add.await_args.kwargs["findings"]) == []


async def test_audit_light_record_fields_unchanged() -> None:
    """反例守护：落库的轻量记录字段（Q1=C）与响应体一致、语义不变."""
    service, log_repo = _svc()

    report = await service.audit(PID, CID, include_static=False)

    persisted: AuditLog = log_repo.add.await_args.args[0]
    assert persisted.project_id == PID
    assert persisted.chapter_id == CID
    assert persisted.chapter_title == "第 3 章 龙的苏醒"
    assert persisted.status == "pending"
    assert persisted.severity_summary == "0 error, 0 warnings, 1 info"
    assert persisted.summary == report.summary == ""
    assert persisted.degraded is False
    assert persisted.confirmed_at is None
    # 落库时间与响应体一致（既有契约）
    assert persisted.created_at == report.created_at
    # 轻量实体本身仍无 findings 字段
    assert "findings" not in persisted.model_dump(mode="json")


async def test_get_log_returns_detail_from_repo() -> None:
    """读口：get_log 透传仓储明细（含 findings）."""
    detail = AuditLogDetail(
        id=LOG_ID,
        project_id=PID,
        chapter_id=CID,
        chapter_title="第 3 章 龙的苏醒",
        status="pending",
        severity_summary="0 error, 0 warnings, 1 info",
        summary="",
        degraded=False,
        note="",
        created_at=TS,
        confirmed_at=None,
        findings=[
            ChapterAuditFinding(
                check_type=AuditCheckType.WORD_COUNT,
                severity=AuditSeverity.INFO,
                message="本章 100 字，低于目标 3,000 字",
            )
        ],
    )
    service, log_repo = _svc(repo_get_result=detail)

    result = await service.get_log(LOG_ID)

    assert result == detail
    assert len(result.findings) == 1
    log_repo.get.assert_awaited_once_with(LOG_ID)


async def test_get_log_unknown_raises_not_found() -> None:
    """读口：记录不存在 → AuditLogNotFoundError（消息即 API 404 detail）."""
    service, _ = _svc(repo_get_result=None)

    with pytest.raises(AuditLogNotFoundError) as exc_info:
        await service.get_log(LOG_ID)

    assert str(exc_info.value) == "审计记录不存在"
