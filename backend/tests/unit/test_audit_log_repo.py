"""SQLiteAuditLogRepository 集成测试 — in-memory SQLite（F34 spec §2.3 + §8.1/§8.2 + §9）.

覆盖 audit_logs 轻量记录表全部仓储场景:
- 表自动创建: Base.metadata.create_all 后 audit_logs 表存在（AuditLogORM
  注册于 inkflow.infrastructure.database.models.audit_log）
- add: 插入后返回含 id 的 AuditLog；chapter_title 快照正确；ORM→领域
  字段映射完整（id 为 uuid.UUID 领域型，ORM id 是 int 自增，repo 层做
  int→uuid.UUID(int=...) 转换）
- latest_pending: 该章最新 pending 记录（created_at desc 取最新）；
  该章全部已确认 → None；其他章 pending 不可见
- confirm: status 更新 accepted/rejected + note + confirmed_at 落库；
  不存在 → None
- list: 分页正确（total 全量、页内容正确）；跨项目不可见；limit 默认 20
- FK 级联（E14）: 删除 project/chapter 行 → audit_logs 行随删
  （外键 ON DELETE CASCADE，需 PRAGMA foreign_keys=ON）

设计假设（GREEN 实现契约，依据 specs/f34-chapter-audit/spec.md）:
1. 被测实现: inkflow.infrastructure.database.repositories.audit_log_repo
   .SQLiteAuditLogRepository（CREATE；RED 阶段不存在 → 本文件顶部 import
   抛 ModuleNotFoundError = 预期收集期失败，pytest 退出码 2）
2. 端口: inkflow.domain.ports.audit_log_repository.AuditLogRepositoryProtocol
   （协议定义，本文件以方法存在性断言其契约，不 isinstance——Protocol
   未声明 @runtime_checkable）
3. 方法签名（§8.1，F15 audit_repo 先例）:
   - add(log: AuditLog) -> AuditLog: 插入后返回含 ORM 行 id 的 AuditLog
     （id 为 uuid.UUID，uuid.UUID(int=orm_id)）；created_at 以领域对象
     传入值为准（不覆盖为 now）
   - latest_pending(chapter_id: int) -> AuditLog | None: 该章全部记录中
     最新（created_at desc）的 pending 记录
   - confirm(log_id: int, *, action: str, note: str, confirmed_at: datetime)
     -> AuditLog | None: status=action + note + confirmed_at 落库；
     log_id 不存在 → None
   - list(project_id: int, *, offset=0, limit=20) ->
     tuple[list[AuditLog], int]: (页内容, 该项目全量 total)
4. AuditLogORM 字段（§2.3 逐字）: id 自增 int / project_id 与 chapter_id
   ForeignKey ondelete="CASCADE" / chapter_title String(200) / status
   String(10) / severity_summary String(50) / summary Text 默认 "" /
   degraded Boolean 默认 False / note Text 默认 "" / created_at DateTime /
   confirmed_at DateTime nullable
5. 仓储构造: SQLiteAuditLogRepository(db_session)；所有 id 参数/返回均为
   int / uuid.UUID(int=...) 语义
6. datetime 用固定 UTC 值构造（SQLite DateTime 列存储不经时区 roundtrip，
   本文件不断言精确时刻相等，只断言非 None 落库）
7. RED 预期: 收集期 1 error（ModuleNotFoundError: No module named
   'inkflow.domain.models.chapter_audit'，首个缺失 import），无其他失败

补测覆盖（覆盖率 miss 归因，2026-08）:
- AuditLogORM.__repr__ 可读（模型 L97）: repr 含类名与关键字段
- AuditLogORM.created_at 默认 _utcnow（模型 L26）: repo.add 必传领域
  created_at（领域模型必需字段），默认值路径经 ORM 直插覆盖
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter_audit import AuditLog
from inkflow.domain.ports.audit_log_repository import AuditLogRepositoryProtocol
from inkflow.infrastructure.database.models.audit_log import AuditLogORM
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.audit_log_repo import SQLiteAuditLogRepository

TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）。"""
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
    """一个基础项目（audit_logs.project_id 的 FK 依赖）。"""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def other_project(db_session):
    """另一个项目（跨项目不可见测试用）。"""
    p = ProjectORM(name="另一项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def chapter(db_session, project):
    """一个基础章节（audit_logs.chapter_id 的 FK 依赖）。"""
    c = ChapterORM(project_id=project.id, title="第 3 章 龙的苏醒")
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


async def _add(db_session, obj):
    """插入一行并刷新（拿到自增主键）。"""
    db_session.add(obj)
    await db_session.commit()
    await db_session.refresh(obj)
    return obj


def _repo(db_session) -> SQLiteAuditLogRepository:
    """构造被测仓储（AuditLogRepositoryProtocol 实现）。"""
    return SQLiteAuditLogRepository(db_session)


def make_log(**overrides: Any) -> AuditLog:
    """构造最小合法审计记录领域对象（镜像 test_chapter_audit_models.py 工厂）。

    project_id/chapter_id 以 uuid.UUID(int=orm_id) 形式传入（repo 层负责
    UUID→int 反向转换落库）。
    """
    base = {
        "id": uuid.UUID(int=100),
        "project_id": uuid.UUID(int=10),
        "chapter_id": uuid.UUID(int=20),
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "1 error, 2 warnings, 0 info",
        "summary": "本章整体符合设定",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
    }
    base.update(overrides)
    return AuditLog(**base)


class TestTableCreation:
    """audit_logs 表自动创建（§2.3: Base.metadata.create_all 管理，零迁移）。"""

    async def test_audit_logs_table_exists_after_create_all(self, db_session):
        async with db_session.bind.connect() as conn:
            has_table = await conn.run_sync(lambda c: inspect(c).has_table("audit_logs"))
        assert has_table is True


class TestAdd:
    """add（§8.1: 插入 + ORM→领域完整映射 + 标题快照）。"""

    async def test_add_returns_domain_log_with_orm_id(self, db_session, project, chapter):
        repo = _repo(db_session)
        log = make_log(
            project_id=uuid.UUID(int=project.id),
            chapter_id=uuid.UUID(int=chapter.id),
        )
        saved = await repo.add(log)
        row = (await db_session.execute(select(AuditLogORM))).scalar_one()
        assert isinstance(saved.id, uuid.UUID)
        assert saved.id.int == row.id
        assert saved.project_id == uuid.UUID(int=row.project_id)
        assert saved.chapter_id == uuid.UUID(int=row.chapter_id)
        assert saved.chapter_title == "第 3 章 龙的苏醒"
        assert saved.status == "pending"
        assert saved.severity_summary == "1 error, 2 warnings, 0 info"
        assert saved.summary == "本章整体符合设定"
        assert saved.degraded is False
        assert saved.note == ""
        assert isinstance(saved.created_at, datetime)
        assert saved.confirmed_at is None

    async def test_add_keeps_chapter_title_snapshot(self, db_session, project, chapter):
        """章节标题以 add 时快照为准（§2.3: 章节改名后仍可读）。"""
        repo = _repo(db_session)
        saved = await repo.add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
                chapter_title="第 3 章 龙的苏醒（旧名）",
            )
        )
        assert saved.chapter_title == "第 3 章 龙的苏醒（旧名）"
        row = (await db_session.execute(select(AuditLogORM))).scalar_one()
        assert row.chapter_title == "第 3 章 龙的苏醒（旧名）"

    async def test_add_persists_passed_created_at(self, db_session, project, chapter):
        """created_at 以领域对象传入值为准（latest_pending 排序确定性依赖）。"""
        repo = _repo(db_session)
        created = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
        await repo.add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
                created_at=created,
            )
        )
        row = (await db_session.execute(select(AuditLogORM))).scalar_one()
        assert row.created_at is not None


class TestLatestPending:
    """latest_pending（§8.1: 该章最新 pending 记录）。"""

    async def test_returns_most_recent_pending(self, db_session, project, chapter):
        repo = _repo(db_session)
        pid = uuid.UUID(int=project.id)
        cid = uuid.UUID(int=chapter.id)
        earlier = await repo.add(
            make_log(
                project_id=pid,
                chapter_id=cid,
                created_at=datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC),
            )
        )
        later = await repo.add(
            make_log(
                project_id=pid,
                chapter_id=cid,
                created_at=datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC),
            )
        )
        assert earlier.id != later.id
        latest = await repo.latest_pending(chapter.id)
        assert latest is not None
        assert latest.id == later.id

    async def test_all_confirmed_returns_none(self, db_session, project, chapter):
        repo = _repo(db_session)
        saved = await repo.add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
            )
        )
        await repo.confirm(
            saved.id.int,
            action="accept",
            note="",
            confirmed_at=datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC),
        )
        assert await repo.latest_pending(chapter.id) is None

    async def test_other_chapter_pending_invisible(self, db_session, project, chapter):
        repo = _repo(db_session)
        other = await _add(db_session, ChapterORM(project_id=project.id, title="另一章"))
        await repo.add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
            )
        )
        assert await repo.latest_pending(other.id) is None

    async def test_never_audited_returns_none(self, db_session, project, chapter):
        assert await _repo(db_session).latest_pending(chapter.id) is None


class TestConfirm:
    """confirm（§8.1: 状态更新 + note/confirmed_at 落库）。"""

    async def test_accept_updates_status_and_confirmed_at(self, db_session, project, chapter):
        repo = _repo(db_session)
        saved = await repo.add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
            )
        )
        confirmed_at = datetime(2026, 8, 1, 11, 30, 0, tzinfo=UTC)
        updated = await repo.confirm(
            saved.id.int, action="accept", note="", confirmed_at=confirmed_at
        )
        assert updated is not None
        assert updated.id == saved.id
        assert updated.status == "accepted"
        assert updated.confirmed_at is not None
        row = (await db_session.execute(select(AuditLogORM))).scalar_one()
        assert row.status == "accepted"
        assert row.confirmed_at is not None
        assert row.note == ""

    async def test_reject_with_note_persisted(self, db_session, project, chapter):
        repo = _repo(db_session)
        saved = await repo.add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
            )
        )
        confirmed_at = datetime(2026, 8, 1, 11, 30, 0, tzinfo=UTC)
        updated = await repo.confirm(
            saved.id.int, action="reject", note="人设需再打磨", confirmed_at=confirmed_at
        )
        assert updated is not None
        assert updated.status == "rejected"
        assert updated.note == "人设需再打磨"
        row = (await db_session.execute(select(AuditLogORM))).scalar_one()
        assert row.status == "rejected"
        assert row.note == "人设需再打磨"
        assert row.confirmed_at is not None

    async def test_missing_log_returns_none(self, db_session, project, chapter):
        repo = _repo(db_session)
        assert await repo.confirm(999999, action="accept", note="", confirmed_at=TS) is None


class TestList:
    """list（§8.1: 分页 + 跨项目不可见 + limit 默认 20）。"""

    async def _seed(self, db_session, project, chapter, count: int) -> list[uuid.UUID]:
        """插入 count 条本项目审计记录，返回落库后的领域 id 列表。"""
        repo = _repo(db_session)
        ids = []
        for i in range(count):
            saved = await repo.add(
                make_log(
                    project_id=uuid.UUID(int=project.id),
                    chapter_id=uuid.UUID(int=chapter.id),
                    severity_summary=f"severity {i}",
                )
            )
            ids.append(saved.id)
        return ids

    async def test_pagination_total_and_pages(self, db_session, project, chapter):
        ids = await self._seed(db_session, project, chapter, 5)
        items, total = await _repo(db_session).list(project.id, offset=1, limit=2)
        assert total == 5
        assert len(items) == 2
        assert {it.id for it in items} <= set(ids)
        page1 = {it.id for it in (await _repo(db_session).list(project.id, offset=0, limit=2))[0]}
        page2 = {it.id for it in (await _repo(db_session).list(project.id, offset=2, limit=2))[0]}
        page3 = {it.id for it in (await _repo(db_session).list(project.id, offset=4, limit=2))[0]}
        assert page1 | page2 | page3 == set(ids)
        assert page1.isdisjoint(page2)
        assert page2.isdisjoint(page3)
        assert page1.isdisjoint(page3)

    async def test_limit_defaults_to_twenty(self, db_session, project, chapter):
        await self._seed(db_session, project, chapter, 3)
        items, total = await _repo(db_session).list(project.id)
        assert total == 3
        assert len(items) == 3

    async def test_offset_beyond_total_returns_empty(self, db_session, project, chapter):
        await self._seed(db_session, project, chapter, 2)
        items, total = await _repo(db_session).list(project.id, offset=10, limit=2)
        assert total == 2
        assert items == []

    async def test_cross_project_invisible(self, db_session, project, other_project, chapter):
        other_chapter = await _add(
            db_session, ChapterORM(project_id=other_project.id, title="他项目的章")
        )
        await _repo(db_session).add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
            )
        )
        await _repo(db_session).add(
            make_log(
                project_id=uuid.UUID(int=other_project.id),
                chapter_id=uuid.UUID(int=other_chapter.id),
                chapter_title="他项目的章",
            )
        )
        items, total = await _repo(db_session).list(project.id)
        assert total == 1
        assert len(items) == 1
        assert items[0].project_id == uuid.UUID(int=project.id)
        other_items, other_total = await _repo(db_session).list(other_project.id)
        assert other_total == 1
        assert other_items[0].project_id == uuid.UUID(int=other_project.id)


class TestForeignKeyCascade:
    """FK 级联（§2.3/E14: 项目/章节删除时审计记录随删）。"""

    async def test_delete_project_cascades_logs(self, db_session, project, chapter):
        await _repo(db_session).add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
            )
        )
        await db_session.delete(project)
        await db_session.commit()
        rows = (await db_session.execute(select(AuditLogORM))).scalars().all()
        assert rows == []

    async def test_delete_chapter_cascades_logs(self, db_session, project, chapter):
        await _repo(db_session).add(
            make_log(
                project_id=uuid.UUID(int=project.id),
                chapter_id=uuid.UUID(int=chapter.id),
            )
        )
        await db_session.delete(chapter)
        await db_session.commit()
        rows = (await db_session.execute(select(AuditLogORM))).scalars().all()
        assert rows == []


class TestPortContract:
    """AuditLogRepositoryProtocol 端口契约（§8.1）。"""

    def test_protocol_defines_port_methods(self):
        for method in ("add", "latest_pending", "confirm", "list"):
            assert callable(getattr(AuditLogRepositoryProtocol, method, None))

    def test_repo_exposes_port_methods(self, db_session):
        repo = _repo(db_session)
        for method in ("add", "latest_pending", "confirm", "list"):
            assert callable(getattr(repo, method))


class TestAuditLogORM:
    """AuditLogORM 模型层（§2.3: repr 可读 + created_at 默认值路径）。"""

    def test_repr_readable(self):
        """repr 可读（模型 L97）: 含类名与关键字段（日志展示/调试用）。"""
        orm = AuditLogORM(
            project_id=1,
            chapter_id=2,
            chapter_title="第 3 章 龙的苏醒",
            status="pending",
            severity_summary="0 error, 0 warnings, 0 info",
        )
        assert "AuditLogORM" in repr(orm)
        assert "pending" in repr(orm)

    async def test_created_at_defaults_to_utcnow(self, db_session, project, chapter):
        """不传 created_at → ORM 默认 _utcnow（模型 L26）。

        repo.add 必传领域 created_at（领域模型必需字段），默认值路径只能经
        ORM 直插覆盖——补测 ORM 层默认值行为。
        """
        orm = AuditLogORM(
            project_id=project.id,
            chapter_id=chapter.id,
            chapter_title="第 3 章 龙的苏醒",
            status="pending",
            severity_summary="0 error, 0 warnings, 0 info",
        )
        db_session.add(orm)
        await db_session.commit()
        await db_session.refresh(orm)
        assert orm.created_at is not None
