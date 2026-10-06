"""#1425 RED 契约 —— ChapterAuditService 异步语义（submit / run_audit_job / get_status）.

契约（GREEN 实现必须满足）:
- `submit(project_id, chapter_id, *, include_static=True) -> tuple[AuditLog, bool]`：
  ① 项目/章节校验（404 语义，受理前）；② `content_hash = sha256(chapter.content)`；
  ③ 命中 `find_reusable` → 复用既有记录（`created=False`，**不新增**、不落 running）；
  ④ 未命中 → 落一条 `run_status='running'`（`status='pending'`、`severity_summary=''`、
     `findings=[]`）记录 → `(log, True)`。
- `run_audit_job(project_id, chapter_id, log_id, *, include_static=True) -> None`：
  跑既有检查段 → 成功 `complete(log_id, findings=报告 findings, severity_summary=..., summary=...,
  degraded=...)`；异常 → `fail(log_id, error=...)`（**绝不抛出**）。
- `get_status(log_id) -> AuditLog`：未命中 → `AuditLogNotFoundError`（404 语义）。
- 同步 `audit()` 语义不变（进程内三处调用零改动）。

依据: issue #1425 + specs/f34-chapter-audit/spec.md §5.1（v1.5）/§7 E8/E19-E22。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.chapter_audit import AuditCheckType, AuditLog, AuditRunStatus
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.chapter_audit_errors import AuditLogNotFoundError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError
from inkflow.domain.services.chapter_audit_service import ChapterAuditService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000099")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
TS = datetime(2026, 10, 7, 10, 0, 0, tzinfo=UTC)
CONTENT = "林晚推开窗。李青焰站在门外，怒斥道：“够了！”"
EXPECTED_HASH = hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
STALE_BEFORE = datetime(2026, 10, 7, 9, 45, 0, tzinfo=UTC)


def _project() -> Project:
    """测试项目（default_words=3000）."""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(default_words=3000),
        created_at=TS,
        updated_at=TS,
    )


def _chapter(**overrides: object) -> Chapter:
    """测试章节（默认属于 PID、正文 = CONTENT、2400 字 → 80% 边界无 finding）."""
    kwargs: dict[str, object] = {
        "id": CID,
        "project_id": PID,
        "title": "第 1 章 开端",
        "content": CONTENT,
        "word_count": 2400,
    }
    kwargs.update(overrides)
    return Chapter(**kwargs)


def _svc(
    *,
    project: object | None = None,
    chapter: object | None = None,
    reusable: AuditLog | None = None,
) -> tuple[ChapterAuditService, dict]:
    """装配 ChapterAuditService（全 Mock；空档案 + 无大纲 → 不触发 LLM）."""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project() if project is None else project)
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(return_value=_chapter() if chapter is None else chapter)
    character_repo = MagicMock()
    character_repo.list = AsyncMock(return_value=([], 0))
    world_repo = MagicMock()
    world_repo.list = AsyncMock(return_value=([], 0))
    audit_service = MagicMock()
    audit_service.run_audit = AsyncMock(side_effect=AssertionError("include_static=False 不应委托"))
    audit_log_repo = MagicMock()
    audit_log_repo.add = AsyncMock(side_effect=lambda log, **kwargs: log)
    audit_log_repo.find_reusable = AsyncMock(return_value=reusable)
    audit_log_repo.complete = AsyncMock(return_value=_log(run_status=AuditRunStatus.COMPLETED))
    audit_log_repo.fail = AsyncMock(return_value=_log(run_status=AuditRunStatus.FAILED))
    audit_log_repo.get_status = AsyncMock(return_value=_log())

    service = ChapterAuditService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=character_repo,
        world_repo=world_repo,
        audit_service=audit_service,
        llm_client=MagicMock(),
        audit_log_repo=audit_log_repo,
    )
    return service, {"audit_log_repo": audit_log_repo, "project_repo": project_repo}


def _log(
    *,
    run_status: AuditRunStatus = AuditRunStatus.COMPLETED,
    status: str = "pending",
) -> AuditLog:
    """构造领域审计记录（执行态可注入）."""
    return AuditLog(
        id=LOG_ID,
        project_id=PID,
        chapter_id=CID,
        chapter_title="第 1 章 开端",
        status=status,  # type: ignore[arg-type]  # 测试构造：仅取合法确认态
        run_status=run_status,
        severity_summary="1 error, 0 warnings, 0 info",
        summary="",
        degraded=False,
        note="",
        created_at=TS,
        confirmed_at=None,
        error="",
    )


class TestSubmit:
    """submit —— 校验 + 幂等复用 + running 记录落库（spec §5.1 v1.5 ①-④）."""

    async def test_submit_creates_running_record_with_content_hash(self) -> None:
        """未命中复用 → 落 running 记录（content_hash = sha256(正文)），返回 created=True."""
        service, mocks = _svc()

        log, created = await service.submit(PID, CID, include_static=False)

        assert created is True
        assert log.run_status is AuditRunStatus.RUNNING
        call = mocks["audit_log_repo"].add.await_args
        passed = call.args[0] if call.args else call.kwargs["log"]
        assert passed.run_status is AuditRunStatus.RUNNING
        assert passed.status == "pending"
        assert passed.severity_summary == ""
        assert passed.project_id == PID
        assert passed.chapter_id == CID
        assert call.kwargs["content_hash"] == EXPECTED_HASH
        assert list(call.kwargs["findings"]) == []

    async def test_submit_reuses_existing_record(self) -> None:
        """命中复用 → 返回既有记录 + created=False，**不新增**、不写 running."""
        existing = _log(run_status=AuditRunStatus.COMPLETED)
        service, mocks = _svc(reusable=existing)

        log, created = await service.submit(PID, CID, include_static=False)

        assert created is False
        assert log is existing
        mocks["audit_log_repo"].add.assert_not_awaited()
        find = mocks["audit_log_repo"].find_reusable.await_args
        assert find.args[0] == CID
        assert find.args[1] == EXPECTED_HASH
        assert "stale_before" in find.kwargs

    async def test_submit_project_not_found(self) -> None:
        """项目不存在 → ProjectNotFoundError（404 语义），不落记录."""
        service, mocks = _svc(project=None)
        mocks["project_repo"].get = AsyncMock(return_value=None)

        with pytest.raises(ProjectNotFoundError):
            await service.submit(PID, CID, include_static=False)
        mocks["audit_log_repo"].add.assert_not_awaited()
        mocks["audit_log_repo"].find_reusable.assert_not_awaited()

    async def test_submit_chapter_not_found(self) -> None:
        """章节不存在 → ChapterNotFoundError（404 语义）."""
        service, mocks = _svc()
        service._chapter_repo.get_chapter = AsyncMock(return_value=None)

        with pytest.raises(ChapterNotFoundError):
            await service.submit(PID, CID, include_static=False)
        mocks["audit_log_repo"].add.assert_not_awaited()

    async def test_submit_chapter_in_other_project(self) -> None:
        """章节属于其他项目 → ChapterNotFoundError（跨项目 404）."""
        service, mocks = _svc(chapter=_chapter(project_id=OTHER_PID))

        with pytest.raises(ChapterNotFoundError):
            await service.submit(PID, CID, include_static=False)
        mocks["audit_log_repo"].add.assert_not_awaited()


class TestRunAuditJob:
    """run_audit_job —— 后台执行体（成功 complete / 异常 fail，绝不抛）."""

    async def test_job_completes_with_report_findings(self) -> None:
        """成功 → complete(log_id, findings=报告 findings, severity_summary, degraded)."""
        service, mocks = _svc()
        # 2370 字 = 79% → 1 条 word_count INFO（确定性，无需 LLM）
        service._chapter_repo.get_chapter = AsyncMock(return_value=_chapter(word_count=2370))

        await service.run_audit_job(PID, CID, LOG_ID, include_static=False)

        call = mocks["audit_log_repo"].complete.await_args
        assert call.args[0] == LOG_ID
        findings = call.kwargs["findings"]
        assert [f.check_type for f in findings] == [AuditCheckType.WORD_COUNT]
        assert call.kwargs["severity_summary"] == "0 error, 0 warnings, 1 info"
        assert call.kwargs["degraded"] is False
        mocks["audit_log_repo"].fail.assert_not_awaited()

    async def test_job_failure_marks_failed_and_does_not_raise(self) -> None:
        """执行异常（项目消失）→ fail(log_id, error=...)；不抛出（fire-and-forget 安全）."""
        service, mocks = _svc()
        mocks["project_repo"].get = AsyncMock(return_value=None)

        await service.run_audit_job(PID, CID, LOG_ID, include_static=False)

        call = mocks["audit_log_repo"].fail.await_args
        assert call.args[0] == LOG_ID
        assert call.kwargs["error"]
        mocks["audit_log_repo"].complete.assert_not_awaited()

    async def test_job_failure_swallows_repo_failure(self) -> None:
        """fail 自身失败 → 不级联抛出（后台任务绝不把异常抛到进程外）."""
        service, mocks = _svc()
        mocks["project_repo"].get = AsyncMock(return_value=None)
        mocks["audit_log_repo"].fail = AsyncMock(side_effect=RuntimeError("db down"))

        await service.run_audit_job(PID, CID, LOG_ID, include_static=False)  # 不抛


class TestGetStatus:
    """get_status —— 轮询读口（命中返回轻量记录；未命中 404 语义）."""

    async def test_get_status_returns_log(self) -> None:
        """命中 → 返回仓储轻量记录."""
        service, _ = _svc()

        log = await service.get_status(LOG_ID)

        assert log.id == LOG_ID
        assert log.run_status is AuditRunStatus.COMPLETED

    async def test_get_status_unknown_raises(self) -> None:
        """未命中 → AuditLogNotFoundError（router 映射 404）."""
        service, mocks = _svc()
        mocks["audit_log_repo"].get_status = AsyncMock(return_value=None)

        with pytest.raises(AuditLogNotFoundError):
            await service.get_status(LOG_ID)
