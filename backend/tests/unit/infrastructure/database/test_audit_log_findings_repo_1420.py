"""#1420 RED 契约 —— audit_logs.findings 落库 + 按记录 ID 取回（仓储层）.

契约（GREEN 实现必须满足）:
- ORM `AuditLogORM` 增 `findings` 列（LenientJSON，nullable=False，default=list）。
- `SQLiteAuditLogRepository.add(log, *, findings=...)` 把 findings 序列化落库；
  findings 缺省（None）→ 落空列表；返回值仍为轻量 `AuditLog`（签名向后兼容）。
- 新增 `SQLiteAuditLogRepository.get(log_id) -> AuditLogDetail | None`
  （命中 → 记录元信息 + findings；不存在 → None）。
- 反例守护（Q1=C 向后兼容）: `list` / `latest_pending` / `confirm` 返回的仍是
  **轻量 AuditLog**（无 findings 键），列表响应形态零变化。
- findings 序列化往返保真（含 ref_entity_id UUID → 字符串 → uuid.UUID）。

依据: issue #1420 + specs/f34-chapter-audit/spec.md §2.3/§8.1（v1.4 演进留痕）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditLog,
    AuditLogDetail,
    AuditSeverity,
    ChapterAuditFinding,
)
from inkflow.domain.ports.audit_log_repository import AuditLogRepositoryProtocol
from inkflow.infrastructure.database.models.audit_log import AuditLogORM
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.audit_log_repo import SQLiteAuditLogRepository

TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
REF_ID = uuid.UUID("0c000000-0000-4000-8000-00000000000c")


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


def _log(project, chapter, **overrides: Any) -> AuditLog:
    """构造领域轻量审计记录."""
    kwargs: dict[str, Any] = {
        "id": uuid.uuid4(),
        "project_id": uuid.UUID(int=project.id),
        "chapter_id": uuid.UUID(int=chapter.id),
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "1 error, 1 warnings, 1 info",
        "summary": "",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
    }
    kwargs.update(overrides)
    return AuditLog(**kwargs)


def _findings() -> list[ChapterAuditFinding]:
    """两条 findings（error + info，覆盖 ref_entity_id 有无 / context 有无）."""
    return [
        ChapterAuditFinding(
            check_type=AuditCheckType.CHARACTER_DRIFT,
            severity=AuditSeverity.ERROR,
            message="角色行为疑似与人设冲突",
            suggestion="可改为隐忍不发",
            ref_entity_id=REF_ID,
            ref_entity_name="角色甲",
            context="“够了！”他猛地拍案而起",
        ),
        ChapterAuditFinding(
            check_type=AuditCheckType.WORD_COUNT,
            severity=AuditSeverity.INFO,
            message="本章 2,845 字，低于目标 3,000 字",
        ),
    ]


def test_orm_column_registered() -> None:
    """ORM 层：audit_logs 表已声明 findings 列（create_all 建新表即含）."""
    assert "findings" in AuditLogORM.__table__.columns


def test_protocol_declares_add_findings_and_get() -> None:
    """端口契约：add 带 findings 关键字 + 新增 get（结构化子类型须齐备）."""
    import inspect

    sig = inspect.signature(AuditLogRepositoryProtocol.add)
    assert "findings" in sig.parameters, "仓储 add 须显式接收 findings（落库口径）"
    assert sig.parameters["findings"].kind is inspect.Parameter.KEYWORD_ONLY
    assert hasattr(AuditLogRepositoryProtocol, "get"), "须新增按 log_id 取回明细的仓储方法"
    get_sig = inspect.signature(AuditLogRepositoryProtocol.get)
    assert list(get_sig.parameters) == ["self", "log_id"]


async def test_add_with_findings_then_get_returns_detail(db_session, project, chapter) -> None:
    """写入 findings → get(log_id) 取回同内容明细（元信息 + findings 逐字段保真）."""
    repo = SQLiteAuditLogRepository(db_session)
    findings = _findings()

    created = await repo.add(_log(project, chapter), findings=findings)

    detail = await repo.get(created.id)
    assert isinstance(detail, AuditLogDetail)
    assert detail is not None
    assert detail.id == created.id
    assert detail.chapter_title == "第 3 章 龙的苏醒"
    assert detail.severity_summary == "1 error, 1 warnings, 1 info"
    assert detail.status == "pending"
    assert [f.check_type for f in detail.findings] == [
        AuditCheckType.CHARACTER_DRIFT,
        AuditCheckType.WORD_COUNT,
    ]
    assert [f.severity for f in detail.findings] == [AuditSeverity.ERROR, AuditSeverity.INFO]
    assert detail.findings[0].message == "角色行为疑似与人设冲突"
    assert detail.findings[0].suggestion == "可改为隐忍不发"
    assert detail.findings[0].ref_entity_id == REF_ID
    assert detail.findings[0].ref_entity_name == "角色甲"
    assert detail.findings[0].context == "“够了！”他猛地拍案而起"
    assert detail.findings[1].ref_entity_id is None
    assert detail.findings[1].context == ""


async def test_add_findings_defaults_to_empty_list(db_session, project, chapter) -> None:
    """未传 findings（旧调用点）→ 落空列表，get 返回空 findings 而非崩溃/None."""
    repo = SQLiteAuditLogRepository(db_session)

    created = await repo.add(_log(project, chapter))
    detail = await repo.get(created.id)

    assert detail is not None
    assert detail.findings == []


async def test_add_empty_findings_roundtrip(db_session, project, chapter) -> None:
    """显式空 findings 列表 → 与缺省同语义（空列表落库，读回 []）."""
    repo = SQLiteAuditLogRepository(db_session)

    created = await repo.add(_log(project, chapter), findings=[])
    detail = await repo.get(created.id)

    assert detail is not None
    assert detail.findings == []


async def test_get_unknown_log_returns_none(db_session) -> None:
    """log_id 不存在 → None（服务层据此映射 404）."""
    repo = SQLiteAuditLogRepository(db_session)

    assert await repo.get(uuid.UUID(int=999999)) is None


async def test_list_entries_stay_light_no_findings(db_session, project, chapter) -> None:
    """反例守护：list 返回轻量 AuditLog（无 findings 键），列表响应形态零变化."""
    repo = SQLiteAuditLogRepository(db_session)
    await repo.add(_log(project, chapter), findings=_findings())

    logs, total = await repo.list(uuid.UUID(int=project.id))

    assert total == 1
    assert len(logs) == 1
    entry = logs[0]
    assert isinstance(entry, AuditLog)
    assert not isinstance(entry, AuditLogDetail)
    assert "findings" not in entry.model_dump(mode="json")
    # 既有摘要字段照旧
    assert entry.severity_summary == "1 error, 1 warnings, 1 info"
    assert entry.chapter_title == "第 3 章 龙的苏醒"
    assert entry.degraded is False
    assert entry.note == ""
    assert entry.confirmed_at is None


async def test_confirm_entry_stays_light_no_findings(db_session, project, chapter) -> None:
    """反例守护：confirm 返回轻量 AuditLog（确认链路契约零变化）."""
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(_log(project, chapter), findings=_findings())

    confirmed = await repo.confirm(created.id, action="accept", note="", confirmed_at=TS)

    assert confirmed is not None
    assert confirmed.status == "accepted"
    assert "findings" not in confirmed.model_dump(mode="json")


async def test_latest_pending_stays_light_no_findings(db_session, project, chapter) -> None:
    """反例守护：latest_pending 返回轻量 AuditLog（确认状态机前置校验零变化）."""
    repo = SQLiteAuditLogRepository(db_session)
    await repo.add(_log(project, chapter), findings=_findings())

    pending = await repo.latest_pending(uuid.UUID(int=chapter.id))

    assert pending is not None
    assert "findings" not in pending.model_dump(mode="json")


async def test_findings_survive_multiple_logs_independently(db_session, project, chapter) -> None:
    """多记录互不串扰：每条的 findings 独立落库、按 id 精确取回."""
    repo = SQLiteAuditLogRepository(db_session)
    first = await repo.add(_log(project, chapter), findings=_findings()[:1])
    second = await repo.add(
        _log(project, chapter, severity_summary="0 error, 0 warnings, 0 info"), findings=[]
    )

    detail_first = await repo.get(first.id)
    detail_second = await repo.get(second.id)

    assert detail_first is not None and detail_second is not None
    assert len(detail_first.findings) == 1
    assert detail_second.findings == []


async def test_migrated_legacy_row_reads_empty_findings(db_session, project, chapter) -> None:
    """#1420 E17 组合面：旧库经 ALTER 补列后的存量行（findings 为 SQL 默认 '[]'）→ 读口空 findings.

    `test_ensure_audit_logs_findings_old_db_adds_column` 锁「补列后存量行为 '[]'」，
    本用例接上后半链：该行经 ORM（LenientJSON 解析）→ `_log_orm_to_detail` → 空列表，
    不因旧行形态崩溃、不 404。
    """
    from sqlalchemy import text as sql_text

    insert = await db_session.execute(
        sql_text(
            "INSERT INTO audit_logs (project_id, chapter_id, chapter_title, status, "
            "severity_summary, summary, degraded, note, created_at, findings) "
            "VALUES (:pid, :cid, '第 3 章 龙的苏醒', 'pending', "
            "'0 error, 0 warnings, 0 info', '', 0, '', '2026-08-01 10:00:00', '[]')"
        ),
        {"pid": project.id, "cid": chapter.id},
    )
    await db_session.commit()
    row_id = int(insert.lastrowid)

    repo = SQLiteAuditLogRepository(db_session)
    detail = await repo.get(uuid.UUID(int=row_id))

    assert detail is not None
    assert detail.findings == []
    assert detail.severity_summary == "0 error, 0 warnings, 0 info"


async def test_get_detail_degraded_flag_preserved(db_session, project, chapter) -> None:
    """读口保留 degraded 标记（可追溯审计质量）."""
    repo = SQLiteAuditLogRepository(db_session)
    created = await repo.add(_log(project, chapter, degraded=True), findings=[])

    detail = await repo.get(created.id)

    assert detail is not None
    assert detail.degraded is True
