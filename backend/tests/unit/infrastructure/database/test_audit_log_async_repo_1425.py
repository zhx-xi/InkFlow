"""#1425 RED 契约 —— 异步语义仓储面（新列往返 + 幂等复用 + 完成/失败/状态读）.

契约（GREEN 实现必须满足）:
- ORM 增 `content_hash` / `run_status` / `error`；`add(log, *, findings=, content_hash=)`
  落库三值；读回（`get` / `get_status` / `list`）带 `run_status` + `error`。
- `find_reusable(chapter_id, content_hash, *, stale_before) -> AuditLog | None`
  复用谓词（spec §7 E8）：同章同 hash 且
    ① `run_status='running'` 且 `created_at >= stale_before`（窗口内在跑），或
    ② `run_status='completed'` 且 `status='pending'` 且 `degraded=False`（已审待确认）
  → 取 created_at 最新一条；否则 None。
  反例：窗口外 running / 已确认 / failed / degraded / hash 不符 / hash 为空串 → None。
- `complete(log_id, *, findings, severity_summary, summary, degraded)` → run_status='completed'
  且清空 error；`fail(log_id, *, error)` → run_status='failed' + error；不存在 → None。
- `get_status(log_id) -> AuditLog | None`（轻量，不含 findings；未命中 → None）。

依据: issue #1425 + specs/f34-chapter-audit/spec.md §2.3/§5.1/§7 E8/E19-E22。
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditLog,
    AuditLogDetail,
    AuditRunStatus,
    AuditSeverity,
    ChapterAuditFinding,
)
from inkflow.domain.ports.audit_log_repository import AuditLogRepositoryProtocol
from inkflow.infrastructure.database.models.audit_log import AuditLogORM
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.audit_log_repo import SQLiteAuditLogRepository

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)
STALE_BEFORE = NOW - timedelta(seconds=900)
HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """一个基础项目（audit_logs.project_id 的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def chapter(db_session, project):
    """一个基础章节（audit_logs.chapter_id 的 FK 依赖）."""
    c = ChapterORM(project_id=project.id, title="第 3 章 龙的苏醒")
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


def _log(
    project: Any,
    chapter: Any,
    *,
    run_status: AuditRunStatus = AuditRunStatus.COMPLETED,
    status: str = "pending",
    degraded: bool = False,
    created_at: datetime = NOW,
    error: str = "",
    severity_summary: str = "0 error, 0 warnings, 0 info",
) -> AuditLog:
    """构造领域审计记录（执行态可注入）."""
    return AuditLog(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        chapter_id=uuid.UUID(int=chapter.id),
        chapter_title="第 3 章 龙的苏醒",
        status=status,  # type: ignore[arg-type]  # 测试构造：仅取合法确认态
        run_status=run_status,
        severity_summary=severity_summary,
        summary="",
        degraded=degraded,
        note="",
        created_at=created_at,
        confirmed_at=None,
        error=error,
    )


def _finding() -> ChapterAuditFinding:
    """一条 error finding（完成落库用）."""
    return ChapterAuditFinding(
        check_type=AuditCheckType.CHARACTER_DRIFT,
        severity=AuditSeverity.ERROR,
        message="角色行为疑似与人设冲突",
    )


def test_orm_declares_async_columns() -> None:
    """ORM 层：audit_logs 表已声明三列（create_all 建新表即含）."""
    cols = AuditLogORM.__table__.columns
    for name in ("content_hash", "run_status", "error"):
        assert name in cols


def test_protocol_declares_async_surface() -> None:
    """端口契约：add 带 content_hash 关键字 + find_reusable/complete/fail/get_status 齐备."""
    sig = inspect.signature(AuditLogRepositoryProtocol.add)
    assert "content_hash" in sig.parameters
    assert sig.parameters["content_hash"].kind is inspect.Parameter.KEYWORD_ONLY
    for name in ("find_reusable", "complete", "fail", "get_status"):
        assert hasattr(AuditLogRepositoryProtocol, name), f"须新增 {name} 端口方法"
    reusable = inspect.signature(AuditLogRepositoryProtocol.find_reusable)
    assert list(reusable.parameters) == ["self", "chapter_id", "content_hash", "stale_before"]
    assert reusable.parameters["stale_before"].kind is inspect.Parameter.KEYWORD_ONLY


async def test_add_persists_async_columns(db_session, project, chapter) -> None:
    """add 落 run_status='running' + content_hash；读回一致（get_status / get）."""
    repo = SQLiteAuditLogRepository(db_session)

    created = await repo.add(
        _log(project, chapter, run_status=AuditRunStatus.RUNNING, severity_summary=""),
        findings=[],
        content_hash=HASH_A,
    )

    assert created.run_status is AuditRunStatus.RUNNING
    light = await repo.get_status(created.id)
    assert light is not None
    assert light.run_status is AuditRunStatus.RUNNING
    assert light.error == ""
    detail = await repo.get(created.id)
    assert detail is not None
    assert detail.run_status is AuditRunStatus.RUNNING
    assert detail.findings == []


async def test_get_status_is_light_and_unknown_returns_none(db_session, project, chapter) -> None:
    """get_status 返回轻量记录（非 Detail）+ 未命中 None."""
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(_log(project, chapter), findings=[_finding()], content_hash=HASH_A)

    light = await repo.get_status(created.id)

    assert light is not None
    assert not isinstance(light, AuditLogDetail)
    assert "findings" not in light.model_dump(mode="json")
    assert await repo.get_status(uuid.UUID(int=999999)) is None


async def test_complete_sets_fields_and_clears_error(db_session, project, chapter) -> None:
    """complete → run_status='completed' + findings/severity_summary/summary/degraded 落库."""
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(
        _log(project, chapter, run_status=AuditRunStatus.RUNNING, severity_summary=""),
        findings=[],
        content_hash=HASH_A,
    )

    updated = await repo.complete(
        created.id,
        findings=[_finding()],
        severity_summary="1 error, 0 warnings, 0 info",
        summary="本章整体符合设定",
        degraded=False,
    )

    assert updated is not None
    assert updated.run_status is AuditRunStatus.COMPLETED
    assert updated.severity_summary == "1 error, 0 warnings, 0 info"
    assert updated.summary == "本章整体符合设定"
    assert updated.error == ""
    detail = await repo.get(created.id)
    assert detail is not None
    assert len(detail.findings) == 1


async def test_complete_unknown_returns_none(db_session) -> None:
    """complete 未命中 → None（服务层防御面）."""
    repo = SQLiteAuditLogRepository(db_session)

    assert (
        await repo.complete(
            uuid.UUID(int=999999),
            findings=[],
            severity_summary="",
            summary="",
            degraded=False,
        )
        is None
    )


async def test_fail_sets_failed_and_error(db_session, project, chapter) -> None:
    """fail → run_status='failed' + error 落库（保留原 severity_summary）."""
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(
        _log(project, chapter, run_status=AuditRunStatus.RUNNING, severity_summary=""),
        findings=[],
        content_hash=HASH_A,
    )

    updated = await repo.fail(created.id, error="审计任务失败: boom")

    assert updated is not None
    assert updated.run_status is AuditRunStatus.FAILED
    assert updated.error == "审计任务失败: boom"


async def test_fail_unknown_returns_none(db_session) -> None:
    """fail 未命中 → None."""
    repo = SQLiteAuditLogRepository(db_session)

    assert await repo.fail(uuid.UUID(int=999999), error="x") is None


async def test_find_reusable_hits_running_within_window(db_session, project, chapter) -> None:
    """命中 ①：窗口内 running（并发重跑去重）."""
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(
        _log(project, chapter, run_status=AuditRunStatus.RUNNING),
        findings=[],
        content_hash=HASH_A,
    )

    found = await repo.find_reusable(uuid.UUID(int=chapter.id), HASH_A, stale_before=STALE_BEFORE)

    assert found is not None
    assert found.id == created.id


async def test_find_reusable_skips_stale_running(db_session, project, chapter) -> None:
    """反例：窗口外 running（疑似内核崩溃遗留）→ 不复用（不阻塞重审，E21）."""
    repo = SQLiteAuditLogRepository(db_session)
    await repo.add(
        _log(
            project,
            chapter,
            run_status=AuditRunStatus.RUNNING,
            created_at=NOW - timedelta(seconds=901),
        ),
        findings=[],
        content_hash=HASH_A,
    )

    assert (
        await repo.find_reusable(uuid.UUID(int=chapter.id), HASH_A, stale_before=STALE_BEFORE)
        is None
    )


async def test_find_reusable_hits_completed_pending_not_degraded(
    db_session, project, chapter
) -> None:
    """命中 ②：已完成 + 待确认 + 未降级（幂等重跑不新增记录）."""
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(
        _log(project, chapter, run_status=AuditRunStatus.COMPLETED, status="pending"),
        findings=[_finding()],
        content_hash=HASH_A,
    )

    found = await repo.find_reusable(uuid.UUID(int=chapter.id), HASH_A, stale_before=STALE_BEFORE)

    assert found is not None
    assert found.id == created.id


@pytest.mark.parametrize(
    ("overrides", "case"),
    [
        ({"status": "accepted"}, "已确认（审计周期闭合）"),
        ({"status": "rejected"}, "已拒绝（审计周期闭合）"),
        ({"run_status": AuditRunStatus.FAILED}, "failed（允许重试）"),
    ],
)
async def test_find_reusable_misses_terminal_states(
    db_session, project, chapter, overrides: dict[str, Any], case: str
) -> None:
    """反例族：已确认 / failed → 不复用."""
    repo = SQLiteAuditLogRepository(db_session)
    log = _log(project, chapter)
    for key, value in overrides.items():
        setattr(log, key, value)
    await repo.add(log, findings=[], content_hash=HASH_A)

    assert (
        await repo.find_reusable(uuid.UUID(int=chapter.id), HASH_A, stale_before=STALE_BEFORE)
        is None
    ), case


async def test_find_reusable_hits_degraded_completed_pending(db_session, project, chapter) -> None:
    """降级记录**同样复用**（#1425 实测修正：无模型/LLM 抖动环境下不复用会每次新增重复记录）.

    过期形态 = 「每次触发都多一条无法区分的记录」，正是 #1425 要根治的；要刷新降级
    结果 → 先确认该记录（accepted/rejected）或改动正文，均自然产生新记录。
    """
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(
        _log(project, chapter, degraded=True), findings=[], content_hash=HASH_A
    )

    found = await repo.find_reusable(
        uuid.UUID(int=chapter.id), HASH_A, stale_before=STALE_BEFORE
    )

    assert found is not None
    assert found.id == created.id


async def test_find_reusable_misses_hash_mismatch(db_session, project, chapter) -> None:
    """反例：内容变更（hash 不符）→ 不复用（新记录，E11）.**"""
    repo = SQLiteAuditLogRepository(db_session)
    await repo.add(_log(project, chapter), findings=[], content_hash=HASH_A)

    assert (
        await repo.find_reusable(uuid.UUID(int=chapter.id), HASH_B, stale_before=STALE_BEFORE)
        is None
    )


async def test_find_reusable_misses_empty_hash(db_session, project, chapter) -> None:
    """反例：hash 为空串（旧行/未记录）→ 永不命中（E23）."""
    repo = SQLiteAuditLogRepository(db_session)
    await repo.add(_log(project, chapter), findings=[], content_hash="")

    assert (
        await repo.find_reusable(uuid.UUID(int=chapter.id), "", stale_before=STALE_BEFORE) is None
    )


async def test_find_reusable_prefers_latest_match(db_session, project, chapter) -> None:
    """多条匹配 → 取 created_at 最新一条（确认面「最新一条」语义一致）."""
    repo = SQLiteAuditLogRepository(db_session)
    await repo.add(
        _log(project, chapter, created_at=NOW - timedelta(seconds=60)),
        findings=[],
        content_hash=HASH_A,
    )
    latest = await repo.add(
        _log(project, chapter, created_at=NOW), findings=[], content_hash=HASH_A
    )

    found = await repo.find_reusable(uuid.UUID(int=chapter.id), HASH_A, stale_before=STALE_BEFORE)

    assert found is not None
    assert found.id == latest.id


async def test_find_reusable_scoped_to_chapter(db_session, project, chapter) -> None:
    """反例：同 hash 但不同章节 → 不复用（去重键含 chapter_id）."""
    repo = SQLiteAuditLogRepository(db_session)
    other = ChapterORM(project_id=project.id, title="第 4 章 另一章")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    await repo.add(_log(project, chapter), findings=[], content_hash=HASH_A)

    assert (
        await repo.find_reusable(uuid.UUID(int=other.id), HASH_A, stale_before=STALE_BEFORE) is None
    )


async def test_list_entries_expose_run_status(db_session, project, chapter) -> None:
    """列表轻量记录增补 run_status/error（--history 区分尝试的可见面）."""
    repo = SQLiteAuditLogRepository(db_session)
    await repo.add(
        _log(project, chapter, run_status=AuditRunStatus.FAILED, error="boom"),
        findings=[],
        content_hash=HASH_A,
    )

    logs, total = await repo.list(uuid.UUID(int=project.id))

    assert total == 1
    assert logs[0].run_status is AuditRunStatus.FAILED
    assert logs[0].error == "boom"
    assert "findings" not in logs[0].model_dump(mode="json")
