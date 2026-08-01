"""SQLiteForeshadowingRepository 集成测试 — in-memory SQLite（F13 仓储层 RED→GREEN）.

覆盖 ForeshadowingRepositoryProtocol 全部方法（spec §8.1 / §9 仓储测试）:
- 伏笔 CRUD 往返（含 event_id 挂接/解除持久化、resolved_at 保留）
- get_by_title 命中与未命中（软删排除、项目隔离）
- partial unique: 活动同名插入 → IntegrityError（回滚后可继续）；
  软删除后同名可重建（spec §2.3 档案语义）
- list 搜索（title icontains）/ status 精确过滤（open/resolved/不传=全部）/
  各 sort_by 排序（priority 默认降序，priority 相等按 updated_at DESC 兜底）/
  分页
- list_open: F6 注入集合只含 open 活动伏笔，按 (priority DESC, updated_at DESC)，
  resolved/软删除排除（spec §5.3/§8.1）
- 软删除后 get/list 不可见 / restore 恢复且 status/resolved_at 原样保留 /
  hard_delete 物理删除
- 事件硬删 → 伏笔 event_id 自动置 NULL（FK ON DELETE SET NULL）
- 项目硬删 → 伏笔级联物理删除（FK CASCADE）

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK SET NULL / CASCADE 语义才生效。
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
from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingStatus
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
    SQLiteForeshadowingRepository,
)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联/SET NULL）."""
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
    """一个基础项目（伏笔/时间线事件的 FK 依赖）."""
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


def _foreshadowing(project: ProjectORM, title: str, **kw) -> Foreshadowing:
    """构造待持久化的伏笔领域对象.

    领域 id 为随机 UUID；落库时由 DB 自增分配 int 主键，
    读回时以 uuid.UUID(int=orm.id) 还原（F1 映射惯例）。
    可通过 kw 覆盖 id/status/event_id/created_at/updated_at 等字段.
    """
    foreshadowing_id = kw.pop("id", uuid.uuid4())
    created_at = kw.pop("created_at", _now())
    updated_at = kw.pop("updated_at", _now())
    return Foreshadowing(
        id=foreshadowing_id,
        project_id=uuid.UUID(int=project.id),
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        **kw,
    )


async def _event_row(db_session, project: ProjectORM) -> TimelineEventORM:
    """直接落库一个时间线事件行（F13 测试不依赖 F12 仓储，仅用其 ORM 建表/建行）."""
    ev = TimelineEventORM(project_id=project.id, title="林尘觉醒金手指")
    db_session.add(ev)
    await db_session.commit()
    await db_session.refresh(ev)
    return ev


@pytest.mark.integration
class TestForeshadowingRepository:
    """SQLiteForeshadowingRepository 集成测试."""

    # ── Foreshadowing CRUD ──

    async def test_add_and_get_roundtrip(self, db_session, project):
        """add 落库并返回领域对象；get 按 int 主键读回，字段与 UUID 映射正确."""
        repo = SQLiteForeshadowingRepository(db_session)
        saved = await repo.add(
            _foreshadowing(
                project,
                "林晚的身世",
                description="铜镜里反复出现的女子侧脸，暗示林晚身世。",
                priority=80,
                location="第 5 章·林晚沐浴场景",
                extra={"标签": ["身世"]},
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.id == uuid.UUID(int=saved.id.int)
        assert saved.title == "林晚的身世"
        assert saved.description == "铜镜里反复出现的女子侧脸，暗示林晚身世。"
        assert saved.priority == 80
        assert saved.status == ForeshadowingStatus.OPEN
        assert saved.location == "第 5 章·林晚沐浴场景"
        assert saved.event_id is None
        assert saved.resolved_at is None
        assert saved.extra == {"标签": ["身世"]}
        assert saved.is_deleted is False

        # 持久化验证：直接查表
        row = await db_session.execute(
            select(ForeshadowingORM).where(ForeshadowingORM.id == saved.id.int)
        )
        assert row.scalar_one().title == "林晚的身世"

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.project_id == uuid.UUID(int=project.id)
        assert got.priority == 80
        assert got.status == ForeshadowingStatus.OPEN
        assert got.created_at == saved.created_at
        assert got.updated_at == saved.updated_at

    async def test_get_returns_none_for_missing(self, db_session, project):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteForeshadowingRepository(db_session)
        assert await repo.get(99999) is None

    # ── get_by_title ──

    async def test_get_by_title_hit_and_miss(self, db_session, project):
        """get_by_title 命中活动伏笔；未命中/软删/其他项目均返回 None."""
        repo = SQLiteForeshadowingRepository(db_session)
        saved = await repo.add(_foreshadowing(project, "林晚的身世"))

        hit = await repo.get_by_title(project.id, "林晚的身世")
        assert hit is not None
        assert hit.id == saved.id

        # 未命中
        assert await repo.get_by_title(project.id, "铜镜的秘密") is None

        # 软删除后同名不可见（同名唯一检查语义：软删后同名可复用）
        await repo.soft_delete(saved.id.int)
        assert await repo.get_by_title(project.id, "林晚的身世") is None

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.get_by_title(other.id, "林晚的身世") is None

    # ── partial unique（spec §2.3）──

    async def test_partial_unique_active_title_conflict(self, db_session, project):
        """项目内活动伏笔同名唯一：插入第二个活动同名 → IntegrityError，回滚后可继续."""
        repo = SQLiteForeshadowingRepository(db_session)
        project_id = project.id  # rollback 会使 ORM 对象过期，先缓存 int 主键
        await repo.add(_foreshadowing(project, "林晚的身世"))

        with pytest.raises(IntegrityError):
            await repo.add(_foreshadowing(project, "林晚的身世"))
        await db_session.rollback()  # 事务回滚，恢复可用

        # 回滚后仅剩 1 条活动伏笔
        items, total = await repo.list(project_id)
        assert total == 1
        assert items[0].title == "林晚的身世"

        # 不同项目同名互不冲突
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        saved = await repo.add(_foreshadowing(other, "林晚的身世"))
        assert saved.id != items[0].id

    async def test_same_title_rebuildable_after_soft_delete(self, db_session, project):
        """软删除后同名可重建（旧档案已废弃，作者重新埋同一条线）."""
        repo = SQLiteForeshadowingRepository(db_session)
        first = await repo.add(_foreshadowing(project, "林晚的身世"))
        await repo.soft_delete(first.id.int)

        rebuilt = await repo.add(_foreshadowing(project, "林晚的身世"))
        assert rebuilt.id != first.id
        assert rebuilt.is_deleted is False

        # 两条记录并存（旧档案软删保留 + 新活动档案）
        rows = await db_session.execute(select(ForeshadowingORM))
        assert len(rows.scalars().all()) == 2

    # ── list ──

    async def test_list_returns_active_with_total(self, db_session, project):
        """list 排除软删与其他项目，返回 (列表, 总数)."""
        repo = SQLiteForeshadowingRepository(db_session)
        f1 = await repo.add(_foreshadowing(project, "林晚的身世"))
        f2 = await repo.add(_foreshadowing(project, "铜镜的秘密"))
        f3 = await repo.add(_foreshadowing(project, "古鼎之谜"))
        await repo.soft_delete(f3.id.int)

        items, total = await repo.list(project.id)
        assert total == 2
        assert {f.id for f in items} == {f1.id, f2.id}

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.list(other.id) == ([], 0)

    async def test_list_search_icontains(self, db_session, project):
        """search 对 title 不区分大小写子串匹配."""
        repo = SQLiteForeshadowingRepository(db_session)
        await repo.add(_foreshadowing(project, "林晚的身世"))
        await repo.add(_foreshadowing(project, "身世之谜"))
        await repo.add(_foreshadowing(project, "铜镜的秘密"))

        items, total = await repo.list(project.id, search="身世")
        assert total == 2
        assert {f.title for f in items} == {"林晚的身世", "身世之谜"}

        items2, total2 = await repo.list(project.id, search="不存在")
        assert total2 == 0
        assert items2 == []

    async def test_list_status_filter(self, db_session, project):
        """status 精确过滤：open / resolved / 不传=全部活动伏笔."""
        repo = SQLiteForeshadowingRepository(db_session)
        open_f = await repo.add(_foreshadowing(project, "林晚的身世", priority=80))
        resolved_f = await repo.add(
            _foreshadowing(
                project,
                "铜镜的秘密",
                status=ForeshadowingStatus.RESOLVED,
                resolved_at=_dt(5),
            )
        )

        open_items, open_total = await repo.list(project.id, status="open")
        assert open_total == 1
        assert [f.id for f in open_items] == [open_f.id]

        resolved_items, resolved_total = await repo.list(project.id, status="resolved")
        assert resolved_total == 1
        assert [f.id for f in resolved_items] == [resolved_f.id]

        # 不传 = 全部活动（open + resolved）
        all_items, all_total = await repo.list(project.id)
        assert all_total == 2
        assert {f.id for f in all_items} == {open_f.id, resolved_f.id}

    async def test_list_default_sort_by_priority_desc(self, db_session, project):
        """默认按 priority DESC 排序（大者在前，与 F6 注入顺序一致）."""
        repo = SQLiteForeshadowingRepository(db_session)
        await repo.add(_foreshadowing(project, "低优先级", priority=10))
        await repo.add(_foreshadowing(project, "高优先级", priority=90))
        await repo.add(_foreshadowing(project, "中优先级", priority=50))

        items, _ = await repo.list(project.id)
        assert [f.title for f in items] == ["高优先级", "中优先级", "低优先级"]

        asc, _ = await repo.list(project.id, sort_desc=False)
        assert [f.title for f in asc] == ["低优先级", "中优先级", "高优先级"]

    async def test_list_priority_tie_break_by_updated_at_desc(self, db_session, project):
        """priority 相等时按 updated_at DESC 兜底稳定排序（spec §6.2）."""
        repo = SQLiteForeshadowingRepository(db_session)
        late = await repo.add(_foreshadowing(project, "后更新", priority=50))
        early = await repo.add(_foreshadowing(project, "先更新", priority=50))

        # 注入受控 updated_at，使「同优先级 → updated_at DESC」可确定性断言
        await db_session.execute(
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == late.id.int)
            .values(updated_at=_dt(3))
        )
        await db_session.execute(
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == early.id.int)
            .values(updated_at=_dt(1))
        )
        await db_session.commit()

        items, _ = await repo.list(project.id)
        assert [f.id for f in items] == [late.id, early.id]

    async def test_list_sort_by_title_and_created_at(self, db_session, project):
        """sort_by=title/created_at 与 sort_desc 生效."""
        repo = SQLiteForeshadowingRepository(db_session)
        await repo.add(_foreshadowing(project, "charlie"))
        await repo.add(_foreshadowing(project, "alpha"))
        await repo.add(_foreshadowing(project, "bravo"))

        asc, _ = await repo.list(project.id, sort_by="title", sort_desc=False)
        assert [f.title for f in asc] == ["alpha", "bravo", "charlie"]

        desc, _ = await repo.list(project.id, sort_by="title", sort_desc=True)
        assert [f.title for f in desc] == ["charlie", "bravo", "alpha"]

        by_created, _ = await repo.list(project.id, sort_by="created_at", sort_desc=False)
        assert [f.title for f in by_created] == ["charlie", "alpha", "bravo"]

    async def test_list_sort_by_status_and_updated_at(self, db_session, project):
        """sort_by=status/updated_at 生效."""
        repo = SQLiteForeshadowingRepository(db_session)
        resolved = await repo.add(
            _foreshadowing(
                project,
                "b-resolved",
                status=ForeshadowingStatus.RESOLVED,
                resolved_at=_dt(2),
            )
        )
        open_f = await repo.add(_foreshadowing(project, "a-open"))

        # status 字符串排序（"open" < "resolved"，升序 open 在前）
        asc, _ = await repo.list(project.id, sort_by="status", sort_desc=False)
        assert [f.title for f in asc] == ["a-open", "b-resolved"]

        # updated_at 排序（注入受控时间戳）
        await db_session.execute(
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == open_f.id.int)
            .values(updated_at=_dt(5))
        )
        await db_session.execute(
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == resolved.id.int)
            .values(updated_at=_dt(1))
        )
        await db_session.commit()

        desc, _ = await repo.list(project.id, sort_by="updated_at", sort_desc=True)
        assert [f.title for f in desc] == ["a-open", "b-resolved"]

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数；越界返回空列表."""
        repo = SQLiteForeshadowingRepository(db_session)
        for i in range(5):
            await repo.add(_foreshadowing(project, f"伏笔{i}", priority=i))

        page1, total = await repo.list(project.id, offset=0, limit=2)
        page2, _ = await repo.list(project.id, offset=2, limit=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {f.id for f in page1}.isdisjoint({f.id for f in page2})
        # 分页越界 → 空列表（同 F1）
        page3, _ = await repo.list(project.id, offset=99, limit=2)
        assert page3 == []

    # ── list_open（F6 注入集合，spec §5.3/§8.1）──

    async def test_list_open_only_open_active_sorted(self, db_session, project):
        """list_open 只含 open 活动伏笔，按 (priority DESC, updated_at DESC)；
        resolved/软删除/其他项目排除."""
        repo = SQLiteForeshadowingRepository(db_session)
        low = await repo.add(_foreshadowing(project, "低优先级", priority=10))
        high = await repo.add(_foreshadowing(project, "高优先级", priority=90))
        mid = await repo.add(_foreshadowing(project, "中优先级", priority=50))
        # resolved 伏笔不进入注入集合（下方精确顺序断言已覆盖排除）
        await repo.add(
            _foreshadowing(
                project,
                "已回收",
                status=ForeshadowingStatus.RESOLVED,
                resolved_at=_dt(5),
                priority=95,
            )
        )
        gone = await repo.add(_foreshadowing(project, "软删", priority=100))
        await repo.soft_delete(gone.id.int)

        # 注入受控 updated_at：同优先级（此处无）与 (priority DESC, updated_at DESC) 断言
        await db_session.execute(
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == high.id.int)
            .values(updated_at=_dt(3))
        )
        await db_session.execute(
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == mid.id.int)
            .values(updated_at=_dt(2))
        )
        await db_session.execute(
            sa_update(ForeshadowingORM)
            .where(ForeshadowingORM.id == low.id.int)
            .values(updated_at=_dt(1))
        )
        await db_session.commit()

        items = await repo.list_open(project.id)
        assert [f.id for f in items] == [high.id, mid.id, low.id]

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.list_open(other.id) == []

    # ── update ──

    async def test_update_foreshadowing_with_event_attach_detach(self, db_session, project):
        """update 按 id 定位更新字段并返回最新领域对象（含 event_id 挂接/解除持久化）."""
        repo = SQLiteForeshadowingRepository(db_session)
        f = await repo.add(_foreshadowing(project, "林晚的身世", priority=50))
        ev = await _event_row(db_session, project)

        # 挂接事件（event_id UUID ↔ DB int 映射）
        attached = await repo.update(
            f.model_copy(
                update={
                    "title": "林晚的身世·改",
                    "priority": 90,
                    "location": "第 8 章",
                    "event_id": uuid.UUID(int=ev.id),
                }
            )
        )
        assert attached.id == f.id
        assert attached.title == "林晚的身世·改"
        assert attached.priority == 90
        assert attached.event_id == uuid.UUID(int=ev.id)
        assert attached.updated_at >= f.updated_at

        # 持久化验证：DB 行 event_id 为 int
        row = await db_session.execute(
            select(ForeshadowingORM).where(ForeshadowingORM.id == f.id.int)
        )
        assert row.scalar_one().event_id == ev.id

        # 解除挂接（event_id=None）
        detached = await repo.update(attached.model_copy(update={"event_id": None}))
        assert detached.event_id is None
        row2 = await db_session.execute(
            select(ForeshadowingORM).where(ForeshadowingORM.id == f.id.int)
        )
        assert row2.scalar_one().event_id is None

        # resolved_at 更新持久化（服务层状态迁移经 update 落库）。
        # 注: SQLite 存储时区感知时间会丢失 tzinfo（读回为 naive），
        # 断言用 naive 时间戳（项目既有行为，同 F12 created_at 处理）
        resolved = await repo.update(
            detached.model_copy(
                update={
                    "status": ForeshadowingStatus.RESOLVED,
                    "resolved_at": _dt(10),
                }
            )
        )
        assert resolved.status == ForeshadowingStatus.RESOLVED
        assert resolved.resolved_at == datetime(2026, 1, 10)

    async def test_update_missing_raises_value_error(self, db_session, project):
        """update 不存在的 id → ValueError."""
        repo = SQLiteForeshadowingRepository(db_session)
        with pytest.raises(ValueError):
            await repo.update(_foreshadowing(project, "幽灵", id=uuid.UUID(int=99999)))
        await db_session.rollback()

    # ── 软删 / 恢复 / 硬删 ──

    async def test_soft_delete_then_get_returns_none(self, db_session, project):
        """软删除后 get/list 均不可见；重复软删返回 False."""
        repo = SQLiteForeshadowingRepository(db_session)
        f = await repo.add(_foreshadowing(project, "林晚的身世"))

        assert await repo.soft_delete(f.id.int) is True
        assert await repo.get(f.id.int) is None
        items, total = await repo.list(project.id)
        assert items == [] and total == 0

        # 已删除/不存在 → False
        assert await repo.soft_delete(f.id.int) is False
        assert await repo.soft_delete(99999) is False

    async def test_restore_preserves_status_and_resolved_at(self, db_session, project):
        """restore 恢复软删伏笔；status/resolved_at 原样保留（spec §2.4）；重复操作无毒."""
        repo = SQLiteForeshadowingRepository(db_session)
        f = await repo.add(_foreshadowing(project, "铜镜的秘密"))
        await repo.update(
            f.model_copy(
                update={
                    "status": ForeshadowingStatus.RESOLVED,
                    "resolved_at": _dt(10),
                }
            )
        )
        await repo.soft_delete(f.id.int)

        restored = await repo.restore(f.id.int)
        assert restored is not None
        assert restored.id == f.id
        assert restored.is_deleted is False
        assert restored.status == ForeshadowingStatus.RESOLVED
        # SQLite 读回时间无 tzinfo（naive），断言用 naive 时间戳
        assert restored.resolved_at == datetime(2026, 1, 10)
        assert await repo.get(f.id.int) is not None

        # 恢复未删除的/不存在的 → None（重复操作无毒）
        assert await repo.restore(f.id.int) is None
        assert await repo.restore(99999) is None

    async def test_hard_delete_foreshadowing(self, db_session, project):
        """hard_delete 物理删除伏笔行；重复删除返回 False."""
        repo = SQLiteForeshadowingRepository(db_session)
        f = await repo.add(_foreshadowing(project, "林晚的身世"))

        assert await repo.hard_delete(f.id.int) is True
        assert await repo.get(f.id.int) is None
        assert await repo.hard_delete(f.id.int) is False

    # ── FK 语义 ──

    async def test_event_hard_delete_sets_event_id_null(self, db_session, project):
        """事件硬删 → 伏笔 event_id 自动置 NULL（FK ON DELETE SET NULL，挂接解除）."""
        repo = SQLiteForeshadowingRepository(db_session)
        ev = await _event_row(db_session, project)
        f = await repo.add(_foreshadowing(project, "林晚的身世", event_id=uuid.UUID(int=ev.id)))
        assert f.event_id == uuid.UUID(int=ev.id)

        # 物理删除事件行（FK SET NULL 由 SQLite 自动执行）
        ev_row = await db_session.execute(
            select(TimelineEventORM).where(TimelineEventORM.id == ev.id)
        )
        await db_session.delete(ev_row.scalar_one())
        await db_session.commit()

        # 伏笔仍在，event_id 置 NULL
        got = await repo.get(f.id.int)
        assert got is not None
        assert got.event_id is None
        row = await db_session.execute(
            select(ForeshadowingORM).where(ForeshadowingORM.id == f.id.int)
        )
        assert row.scalar_one().event_id is None

    async def test_project_hard_delete_cascades_foreshadowings(self, db_session, project):
        """项目硬删 → 伏笔行物理删除（DB FK CASCADE）."""
        repo = SQLiteForeshadowingRepository(db_session)
        await repo.add(_foreshadowing(project, "林晚的身世"))
        await repo.add(_foreshadowing(project, "铜镜的秘密"))

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count = await db_session.execute(select(func.count()).select_from(ForeshadowingORM))
        assert count.scalar_one() == 0
