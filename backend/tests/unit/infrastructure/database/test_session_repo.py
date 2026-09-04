"""SQLiteSessionRepository 集成测试 — in-memory SQLite（F24 仓储层 RED→GREEN，M2）.

覆盖 SessionRepositoryProtocol 全部方法（spec §8.2 / §9 仓储测试）:
- 双实体 CRUD 往返（Session add/get/get 缺失/list/list_include_deleted/update）
- 过滤列表: session_type / status / project_id / search(title icontains) 任意组合
- 列表排序 created_at DESC（最新在前，spec §6.2）与分页 offset/limit
- seq 分配: next_seq = 会话内 max(seq)+1（无日志 = 1，会话间隔离）
- 归档（soft_delete）/ 解除（restore）/ 真实删除（hard_delete，日志级联）
- 视图聚合: count_logs / last_log（0 日志 → last_log=None；last_log = 最大 seq）
- 软删会话不进列表、但日志保留（履历可追溯，spec §2.2）
- (session_id, seq) 唯一约束（spec §8 SessionLogORM）→ 重复 seq 插入 IntegrityError
- title 可重复（实例语义，无唯一约束，spec §2.1）

══════════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准）:
- 仓储类: inkflow.infrastructure.database.repositories.session_repo.SQLiteSessionRepository
  （构造入参 AsyncSession，同 F12/F13 仓储）
- ORM: inkflow.infrastructure.database.models.session → SessionORM / SessionLogORM
  * SessionORM: id int 自增 PK；session_type str 索引；status str 默认 'active' 索引；
    project_id int 可空 FK→projects.id ON DELETE SET NULL 索引；title str；
    description str 默认 ''；context/result JSON 默认 {}；error str 默认 ''；
    started_at/created_at/updated_at datetime；paused_at/completed_at datetime 可空；
    is_deleted bool 默认 False 索引
  * SessionLogORM: id int 自增 PK；session_id int FK→sessions.id ON DELETE CASCADE 索引；
    seq int；level str 默认 'info'；message str；payload JSON 默认 {}；created_at datetime；
    唯一约束 (session_id, seq)
- UUID↔int: 领域 id 落库为 uuid.UUID(int=...) 映射（F1 惯例）；project_id 同
- 方法签名（全部 async）: add(session)->Session / get(session_id:int)->Session|None（不含软删）/
  list_include_deleted(session_id:int)->Session|None / list(session_type:str|None=None,
  status:str|None=None, project_id:int|None=None, search:str|None=None, offset:int=0,
  limit:int=50)->tuple[list[Session], int]（created_at DESC，total=未分页过滤总数）/
  update(session)->Session（缺失 → ValueError，同 F12）/ soft_delete(id)->bool /
  restore(id)->Session|None（未归档/缺失 → None）/ hard_delete(id)->bool /
  add_log(entry)->SessionLogEntry / next_seq(session_id:int)->int /
  list_logs(session_id:int, offset=0, limit=50)->tuple[list[SessionLogEntry], int]（seq ASC）/
  count_logs(session_id:int)->int / last_log(session_id:int)->SessionLogEntry|None
- list_logs 不因会话归档过滤（归档 404 由服务层判定，仓储只做物理查询——履历保留契约）
- 本文件 fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），FK CASCADE 才生效
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.session import (
    LogLevel,
    Session,
    SessionLogEntry,
    SessionStatus,
    SessionType,
)
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.session import SessionLogORM, SessionORM
from inkflow.infrastructure.database.repositories.session_repo import (
    SQLiteSessionRepository,
)


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
    """一个基础项目（sessions.project_id 的 FK 依赖；会话 project_id 可空）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _dt(day: int) -> datetime:
    """构造 2026-01-day 的 UTC 时间（时区感知，测试用固定时间戳）."""
    return datetime(2026, 1, day, tzinfo=UTC)


def _session(
    project: ProjectORM | None,
    title: str,
    *,
    session_type: SessionType = SessionType.WRITING,
    status: SessionStatus = SessionStatus.ACTIVE,
    **kw,
) -> Session:
    """构造待持久化的会话领域对象.

    领域 id 为随机 UUID；落库时由 DB 自增分配 int 主键，读回时以
    uuid.UUID(int=orm.id) 还原（F1 映射惯例）。project_id 用持久化项目
    的 int 主键映射（陷阱 18：勿用随机 uuid4().int 当 FK，SQLite INTEGER
    64 位溢出）。可通过 kw 覆盖 created_at/updated_at（稳定排序测试）。
    """
    session_id = kw.pop("id", uuid.uuid4())
    created_at = kw.pop("created_at", _now())
    updated_at = kw.pop("updated_at", _now())
    return Session(
        id=session_id,
        session_type=session_type,
        status=status,
        project_id=uuid.UUID(int=project.id) if project is not None else None,
        title=title,
        started_at=created_at,
        created_at=created_at,
        updated_at=updated_at,
        **kw,
    )


def _log(session_id: uuid.UUID, seq: int, message: str = "进度日志", **kw) -> SessionLogEntry:
    """构造待持久化的日志条目领域对象（seq 由测试显式指定，服务层负责分配）."""
    kw.setdefault("level", LogLevel.INFO)
    return SessionLogEntry(
        id=uuid.uuid4(),
        session_id=session_id,
        seq=seq,
        message=message,
        payload={},
        created_at=_now(),
        **kw,
    )


@pytest.mark.integration
class TestSessionRepository:
    """SQLiteSessionRepository 集成测试."""

    # ── Session CRUD ──

    async def test_add_and_get_roundtrip(self, db_session, project):
        """add 落库并返回领域对象；get 按 int 主键读回，字段与 UUID 映射正确."""
        repo = SQLiteSessionRepository(db_session)
        saved = await repo.add(
            _session(
                project,
                "第三章续写",
                session_type=SessionType.WRITING,
                status=SessionStatus.PAUSED,
                description="续写第三章",
                context={"chapter_id": "7b9c", "mode": "continue"},
                result={"words": 1280},
                error="",
                paused_at=_dt(2),
                completed_at=None,
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.id == uuid.UUID(int=saved.id.int)
        assert saved.title == "第三章续写"
        assert saved.session_type == SessionType.WRITING
        assert saved.status == SessionStatus.PAUSED
        assert saved.project_id == uuid.UUID(int=project.id)
        assert saved.context == {"chapter_id": "7b9c", "mode": "continue"}
        assert saved.result == {"words": 1280}
        assert saved.paused_at == _dt(2)
        assert saved.is_deleted is False

        # 持久化验证：直接查表
        row = await db_session.execute(select(SessionORM).where(SessionORM.id == saved.id.int))
        assert row.scalar_one().title == "第三章续写"

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.session_type == SessionType.WRITING
        assert got.status == SessionStatus.PAUSED
        assert got.project_id == uuid.UUID(int=project.id)
        assert got.started_at == saved.started_at
        assert got.updated_at == saved.updated_at

    async def test_add_with_null_project_id(self, db_session):
        """project_id=None（全局会话）合法落库并读回 None."""
        repo = SQLiteSessionRepository(db_session)
        saved = await repo.add(_session(None, "全局定时任务", session_type=SessionType.TASK))
        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.project_id is None

    async def test_get_returns_none_for_missing(self, db_session):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteSessionRepository(db_session)
        assert await repo.get(99999) is None

    async def test_list_returns_active_sessions_sorted_desc(self, db_session, project):
        """list 排除软删、按 created_at DESC（最新在前，spec §6.2）、返回 (列表, 总数)."""
        repo = SQLiteSessionRepository(db_session)
        e1 = await repo.add(_session(project, "觉醒"))
        e2 = await repo.add(_session(project, "宗门大比"))
        e3 = await repo.add(_session(project, "古神禁地"))
        await repo.soft_delete(e3.id.int)

        # 注入受控 created_at，使 DESC 排序可确定性断言
        await db_session.execute(
            sa_update(SessionORM).where(SessionORM.id == e1.id.int).values(created_at=_dt(1))
        )
        await db_session.execute(
            sa_update(SessionORM).where(SessionORM.id == e2.id.int).values(created_at=_dt(3))
        )
        await db_session.commit()

        sessions, total = await repo.list()
        assert total == 2
        assert [s.id for s in sessions] == [e2.id, e1.id]  # DESC: 后建的在前

    async def test_list_filters_combine(self, db_session, project):
        """session_type/status/project_id 过滤任意组合（缺省 = 全量未归档）."""
        repo = SQLiteSessionRepository(db_session)
        s1 = await repo.add(_session(project, "写作一", session_type=SessionType.WRITING))
        s2 = await repo.add(_session(project, "任务一", session_type=SessionType.TASK))
        s3 = await repo.add(
            _session(
                project,
                "任务完成",
                session_type=SessionType.TASK,
                status=SessionStatus.COMPLETED,
            )
        )
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        s4 = await repo.add(_session(other, "他项目任务", session_type=SessionType.TASK))

        # 单维度
        by_type, t1 = await repo.list(session_type="task")
        assert t1 == 3
        assert {s.id for s in by_type} == {s2.id, s3.id, s4.id}
        by_status, t2 = await repo.list(status="active")
        assert t2 == 3
        assert {s.id for s in by_status} == {s1.id, s2.id, s4.id}
        by_project, t3 = await repo.list(project_id=project.id)
        assert t3 == 3
        assert {s.id for s in by_project} == {s1.id, s2.id, s3.id}
        # 组合
        both, t4 = await repo.list(session_type="task", status="completed")
        assert t4 == 1
        assert [s.id for s in both] == [s3.id]
        # 全缺省 = 全部未归档
        _, t5 = await repo.list()
        assert t5 == 4

    async def test_list_search_icontains_title(self, db_session, project):
        """search 对 title 不区分大小写子串匹配（不匹配 description，spec §6.3）."""
        repo = SQLiteSessionRepository(db_session)
        await repo.add(_session(project, "每日定时写作", description="包含关键词的描述"))
        await repo.add(_session(project, "每夜定时写作"))
        await repo.add(_session(project, "第三章续写"))

        sessions, total = await repo.list(search="定时")
        assert total == 2
        assert {s.title for s in sessions} == {"每日定时写作", "每夜定时写作"}

        sessions2, total2 = await repo.list(search="不存在")
        assert total2 == 0
        assert sessions2 == []

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数；越界返回空列表."""
        repo = SQLiteSessionRepository(db_session)
        for i in range(5):
            await repo.add(_session(project, f"会话{i}"))

        page1, total = await repo.list(offset=0, limit=2)
        page2, _ = await repo.list(offset=2, limit=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {s.id for s in page1}.isdisjoint({s.id for s in page2})
        page3, _ = await repo.list(offset=99, limit=2)
        assert page3 == []

    async def test_list_include_deleted(self, db_session, project):
        """list_include_deleted 返回已归档会话（详情可追溯，spec §7 #7）；缺失 → None."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))
        assert await repo.list_include_deleted(s.id.int) is not None

        await repo.soft_delete(s.id.int)
        assert await repo.get(s.id.int) is None
        got = await repo.list_include_deleted(s.id.int)
        assert got is not None
        assert got.is_deleted is True
        assert await repo.list_include_deleted(99999) is None

    async def test_update_session(self, db_session, project):
        """update 按 id 定位更新字段并返回最新领域对象；updated_at 前移."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))

        updated = await repo.update(
            s.model_copy(
                update={
                    "title": "觉醒·改",
                    "description": "新描述",
                    "context": {"mode": "revise"},
                    "status": SessionStatus.PAUSED,
                    "paused_at": _dt(5),
                }
            )
        )
        assert updated.id == s.id
        assert updated.title == "觉醒·改"
        assert updated.description == "新描述"
        assert updated.context == {"mode": "revise"}
        assert updated.status == SessionStatus.PAUSED
        assert updated.paused_at == _dt(5)
        assert updated.updated_at >= s.updated_at

        got = await repo.get(s.id.int)
        assert got is not None
        assert got.title == "觉醒·改"
        assert got.status == SessionStatus.PAUSED

    async def test_update_missing_session_raises_value_error(self, db_session, project):
        """update 不存在的 id → ValueError（同 F12）."""
        repo = SQLiteSessionRepository(db_session)
        with pytest.raises(ValueError):
            await repo.update(_session(project, "幽灵", id=uuid.UUID(int=99999)))
        await db_session.rollback()

    async def test_duplicate_titles_allowed(self, db_session, project):
        """title 允许重复（会话是实例非档案，无唯一约束，spec §2.1）."""
        repo = SQLiteSessionRepository(db_session)
        first = await repo.add(_session(project, "每日写作"))
        second = await repo.add(_session(project, "每日写作"))

        assert second.id != first.id
        sessions, total = await repo.list()
        assert total == 2
        assert {s.id for s in sessions} == {first.id, second.id}

    # ── 归档 / 解除 / 真实删除（spec §2.5 两级删除）──

    async def test_soft_delete_then_invisible(self, db_session, project):
        """soft_delete 后 get/list 均不可见；重复软删/不存在返回 False."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))

        assert await repo.soft_delete(s.id.int) is True
        assert await repo.get(s.id.int) is None
        sessions, total = await repo.list()
        assert sessions == [] and total == 0

        assert await repo.soft_delete(s.id.int) is False
        assert await repo.soft_delete(99999) is False

    async def test_restore_session(self, db_session, project):
        """restore 解除归档；未归档/不存在返回 None（重复操作无毒）."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))
        await repo.soft_delete(s.id.int)

        restored = await repo.restore(s.id.int)
        assert restored is not None
        assert restored.id == s.id
        assert restored.is_deleted is False
        assert await repo.get(s.id.int) is not None

        assert await repo.restore(s.id.int) is None
        assert await repo.restore(99999) is None

    async def test_hard_delete_session(self, db_session, project):
        """hard_delete 物理删除会话行；重复删除返回 False."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))

        assert await repo.hard_delete(s.id.int) is True
        assert await repo.get(s.id.int) is None
        assert await repo.list_include_deleted(s.id.int) is None
        assert await repo.hard_delete(s.id.int) is False

    async def test_hard_delete_cascades_logs(self, db_session, project):
        """会话真实删除 → 日志行物理删除（FK ON DELETE CASCADE，spec §2.2）."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))
        await repo.add_log(_log(s.id, 1))
        await repo.add_log(_log(s.id, 2))

        assert await repo.hard_delete(s.id.int) is True
        count = await db_session.execute(select(func.count()).select_from(SessionLogORM))
        assert count.scalar_one() == 0

    # ── SessionLogEntry ──

    async def test_add_log_and_list_logs_seq_asc(self, db_session, project):
        """add_log 落库；list_logs 按 seq ASC 稳定排序，分页 total 为未分页总数."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))
        e1 = await repo.add_log(_log(s.id, 1, "开始"))
        e2 = await repo.add_log(_log(s.id, 2, "重试"))
        await repo.add_log(_log(s.id, 3, "完成"))

        assert isinstance(e1.id, uuid.UUID)
        assert e2.seq == 2

        logs, total = await repo.list_logs(s.id.int)
        assert total == 3
        assert [e.seq for e in logs] == [1, 2, 3]
        assert logs[0].message == "开始"
        assert logs[0].session_id == s.id

        page, _ = await repo.list_logs(s.id.int, offset=1, limit=1)
        assert [e.seq for e in page] == [2]
        assert await repo.list_logs(99999) == ([], 0)

    async def test_next_seq(self, db_session, project):
        """next_seq = 会话内 max(seq)+1；无日志 = 1；会话间隔离."""
        repo = SQLiteSessionRepository(db_session)
        s1 = await repo.add(_session(project, "会话一"))
        s2 = await repo.add(_session(project, "会话二"))

        assert await repo.next_seq(s1.id.int) == 1
        await repo.add_log(_log(s1.id, 1))
        await repo.add_log(_log(s1.id, 2))
        assert await repo.next_seq(s1.id.int) == 3
        # 会话间隔离
        assert await repo.next_seq(s2.id.int) == 1

    async def test_count_logs_and_last_log(self, db_session, project):
        """count_logs / last_log（SessionView 聚合数据源）；0 日志 → 0/None."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))

        assert await repo.count_logs(s.id.int) == 0
        assert await repo.last_log(s.id.int) is None

        await repo.add_log(_log(s.id, 1, "开始"))
        await repo.add_log(_log(s.id, 2, "重试", level=LogLevel.WARNING))
        assert await repo.count_logs(s.id.int) == 2
        last = await repo.last_log(s.id.int)
        assert last is not None
        assert last.seq == 2
        assert last.level == LogLevel.WARNING

    async def test_logs_retained_after_soft_delete(self, db_session, project):
        """会话归档 → 日志保留（履历可追溯，spec §2.2/§2.5）；仓储层不因归档过滤."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))
        await repo.add_log(_log(s.id, 1))

        await repo.soft_delete(s.id.int)
        logs, total = await repo.list_logs(s.id.int)
        assert total == 1
        assert logs[0].seq == 1
        assert await repo.count_logs(s.id.int) == 1

    async def test_duplicate_seq_raises_integrity_error(self, db_session, project):
        """(session_id, seq) 唯一约束：同会话重复 seq 插入 → IntegrityError（spec §7 #13）."""
        repo = SQLiteSessionRepository(db_session)
        s = await repo.add(_session(project, "觉醒"))
        await repo.add_log(_log(s.id, 1))

        with pytest.raises(IntegrityError):
            await repo.add_log(_log(s.id, 1, "重复 seq"))
        await db_session.rollback()
        # rollback 使 ORM 对象过期，refresh 后才能读 project.id（F13 先例）
        await db_session.refresh(project)
        # 回滚后同 seq 不同会话仍可插入（约束是 (session_id, seq) 复合）
        s2 = await repo.add(_session(project, "另一会话"))
        e = await repo.add_log(_log(s2.id, 1))
        assert e.seq == 1


class TestListIncludeDeleted:
    """#486 会话 UI：list include_deleted 参数（会话页需列出/恢复已归档会话）。"""

    async def test_list_default_excludes_archived(self, db_session, project):
        """默认 list 不含已归档（既有活动列表语义不变）。"""
        repo = SQLiteSessionRepository(db_session)
        await repo.add(_session(project, "活动会话"))
        archived = await repo.add(_session(project, "已归档会话"))
        await repo.soft_delete(archived.id.int)

        items, total = await repo.list()
        assert total == 1
        assert [s.title for s in items] == ["活动会话"]

    async def test_list_include_deleted_returns_archived(self, db_session, project):
        """include_deleted=True → 活动+归档全量（created_at DESC 排序保持）。"""
        repo = SQLiteSessionRepository(db_session)
        await repo.add(_session(project, "活动会话", created_at=_dt(2)))
        archived = await repo.add(_session(project, "已归档会话", created_at=_dt(1)))
        await repo.soft_delete(archived.id.int)

        items, total = await repo.list(include_deleted=True)
        assert total == 2
        assert [s.title for s in items] == ["活动会话", "已归档会话"]
        assert items[1].is_deleted is True

    async def test_list_include_deleted_filter_combination(self, db_session, project):
        """include_deleted=True 与过滤参数组合：类型过滤 + 分页仍生效。"""
        repo = SQLiteSessionRepository(db_session)
        await repo.add(_session(project, "写作一", created_at=_dt(3)))
        archived = await repo.add(_session(project, "写作归档", created_at=_dt(2)))
        await repo.soft_delete(archived.id.int)
        await repo.add(
            _session(project, "任务一", session_type=SessionType.TASK, created_at=_dt(1))
        )

        items, total = await repo.list(session_type="writing", include_deleted=True)
        assert total == 2
        assert [s.title for s in items] == ["写作一", "写作归档"]

        items2, total2 = await repo.list(session_type="writing", include_deleted=True, limit=1)
        assert total2 == 2
        assert len(items2) == 1
        assert items2[0].title == "写作一"
