"""SQLiteTimelineRepository 集成测试 — in-memory SQLite（F12 仓储层 RED→GREEN）.

覆盖 TimelineRepositoryProtocol 全部方法（spec §8.1 / §9 仓储测试）:
- 事件 CRUD 往返（add/get/list/list_all/update/hard_delete）
- list 搜索（title icontains）/ 分页 / 各 sort_by 排序
  （narrative_position 默认升序；time_value 排序 NULLS LAST）
- list_all 全量事件（narrative_position 重复时 created_at ASC 稳定排序）
- next_position（空项目 → 1、追加 → max+1；真删不计入 max）
- 无唯一约束: title / narrative_position / time_value 均可重复（spec §2.4）
- 硬删除 FK 级联（项目物理删除 → 事件级联物理删除）

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK CASCADE 语义才生效。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.repositories.timeline_repo import (
    SQLiteTimelineRepository,
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
    """一个基础项目（时间线事件的 FK 依赖）."""
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


def _event(project: ProjectORM, title: str, **kw) -> TimelineEvent:
    """构造待持久化的时间线事件领域对象.

    领域 id 为随机 UUID；落库时由 DB 自增分配 int 主键，
    读回时以 uuid.UUID(int=orm.id) 还原（F1 映射惯例）。
    可通过 kw 覆盖 id/created_at/updated_at（如稳定排序测试）。
    """
    event_id = kw.pop("id", uuid.uuid4())
    created_at = kw.pop("created_at", _now())
    updated_at = kw.pop("updated_at", _now())
    return TimelineEvent(
        id=event_id,
        project_id=uuid.UUID(int=project.id),
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        **kw,
    )


@pytest.mark.integration
class TestTimelineRepository:
    """SQLiteTimelineRepository 集成测试."""

    # ── TimelineEvent CRUD ──

    async def test_add_and_get_roundtrip(self, db_session, project):
        """add 落库并返回领域对象；get 按 int 主键读回，字段与 UUID 映射正确."""
        repo = SQLiteTimelineRepository(db_session)
        saved = await repo.add(
            _event(
                project,
                "林尘觉醒金手指",
                description="外门考核夜，古鼎第一次亮起。",
                time_value=317.5,
                time_unit="年",
                time_display="青元历 317 年秋",
                narrative_position=3,
                timeline_flag="flashback",
                extra={"参与角色": ["林尘"]},
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.id == uuid.UUID(int=saved.id.int)
        assert saved.title == "林尘觉醒金手指"
        assert saved.description == "外门考核夜，古鼎第一次亮起。"
        assert saved.time_value == 317.5
        assert saved.time_unit == "年"
        assert saved.time_display == "青元历 317 年秋"
        assert saved.narrative_position == 3
        assert saved.timeline_flag == "flashback"
        assert saved.extra == {"参与角色": ["林尘"]}

        # 持久化验证：直接查表
        row = await db_session.execute(
            select(TimelineEventORM).where(TimelineEventORM.id == saved.id.int)
        )
        assert row.scalar_one().title == "林尘觉醒金手指"

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.project_id == uuid.UUID(int=project.id)
        assert got.time_value == 317.5
        assert got.created_at == saved.created_at
        assert got.updated_at == saved.updated_at

    async def test_get_returns_none_for_missing(self, db_session, project):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteTimelineRepository(db_session)
        assert await repo.get(99999) is None

    async def test_list_returns_events_with_total(self, db_session, project):
        """list 返回 (列表, 总数)；真删事件不可见."""
        repo = SQLiteTimelineRepository(db_session)
        e1 = await repo.add(_event(project, "觉醒"))
        e2 = await repo.add(_event(project, "宗门大比"))
        e3 = await repo.add(_event(project, "古神禁地"))
        await repo.hard_delete(e3.id.int)

        events, total = await repo.list(project.id)
        assert total == 2
        assert {e.id for e in events} == {e1.id, e2.id}

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.list(other.id) == ([], 0)

    async def test_list_search_icontains(self, db_session, project):
        """search 对 title 不区分大小写子串匹配."""
        repo = SQLiteTimelineRepository(db_session)
        await repo.add(_event(project, "林尘觉醒"))
        await repo.add(_event(project, "觉醒之夜"))
        await repo.add(_event(project, "宗门大比"))

        events, total = await repo.list(project.id, search="觉醒")
        assert total == 2
        assert {e.title for e in events} == {"林尘觉醒", "觉醒之夜"}

        events2, total2 = await repo.list(project.id, search="不存在")
        assert total2 == 0
        assert events2 == []

    async def test_list_default_sort_by_narrative_position(self, db_session, project):
        """默认按 narrative_position ASC 排序（小者在前）；sort_desc 生效."""
        repo = SQLiteTimelineRepository(db_session)
        await repo.add(_event(project, "第三幕", narrative_position=3))
        await repo.add(_event(project, "第一幕", narrative_position=1))
        await repo.add(_event(project, "第二幕", narrative_position=2))

        events, _ = await repo.list(project.id)
        assert [e.title for e in events] == ["第一幕", "第二幕", "第三幕"]

        desc, _ = await repo.list(project.id, sort_desc=True)
        assert [e.title for e in desc] == ["第三幕", "第二幕", "第一幕"]

    async def test_list_sort_by_time_value_nulls_last(self, db_session, project):
        """sort_by=time_value: 升/降序均 NULLS LAST（未知时间排末尾）."""
        repo = SQLiteTimelineRepository(db_session)
        await repo.add(_event(project, "未知", time_value=None))
        await repo.add(_event(project, "十年后", time_value=10.0))
        await repo.add(_event(project, "五年前", time_value=5.0))

        asc, _ = await repo.list(project.id, sort_by="time_value")
        assert [e.title for e in asc] == ["五年前", "十年后", "未知"]

        desc, _ = await repo.list(project.id, sort_by="time_value", sort_desc=True)
        assert [e.title for e in desc] == ["十年后", "五年前", "未知"]

    async def test_list_sort_by_title_and_created_at(self, db_session, project):
        """sort_by=title/created_at 与 sort_desc 生效."""
        repo = SQLiteTimelineRepository(db_session)
        await repo.add(_event(project, "charlie"))
        await repo.add(_event(project, "alpha"))
        await repo.add(_event(project, "bravo"))

        asc, _ = await repo.list(project.id, sort_by="title", sort_desc=False)
        assert [e.title for e in asc] == ["alpha", "bravo", "charlie"]

        desc, _ = await repo.list(project.id, sort_by="title", sort_desc=True)
        assert [e.title for e in desc] == ["charlie", "bravo", "alpha"]

        by_created, _ = await repo.list(project.id, sort_by="created_at", sort_desc=False)
        assert [e.title for e in by_created] == ["charlie", "alpha", "bravo"]

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数；越界返回空列表."""
        repo = SQLiteTimelineRepository(db_session)
        for i in range(5):
            await repo.add(_event(project, f"事件{i}", narrative_position=i))

        page1, total = await repo.list(project.id, offset=0, limit=2)
        page2, _ = await repo.list(project.id, offset=2, limit=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {e.id for e in page1}.isdisjoint({e.id for e in page2})
        # 分页越界 → 空列表（同 F1）
        page3, _ = await repo.list(project.id, offset=99, limit=2)
        assert page3 == []

    async def test_list_all_returns_events_sorted(self, db_session, project):
        """list_all 全量事件；narrative_position 重复时 created_at ASC 稳定排序."""
        repo = SQLiteTimelineRepository(db_session)
        late_first = await repo.add(_event(project, "位置1·后建", narrative_position=1))
        early = await repo.add(_event(project, "位置1·先建", narrative_position=1))
        pos2 = await repo.add(_event(project, "位置2", narrative_position=2))
        gone = await repo.add(_event(project, "已删·位置0", narrative_position=0))
        await repo.hard_delete(gone.id.int)

        # created_at 由 DB 生成（插入序）；用直接 UPDATE 注入受控时间戳，
        # 使「同位置 → created_at ASC」排序可确定性断言
        await db_session.execute(
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == late_first.id.int)
            .values(created_at=_dt(3))
        )
        await db_session.execute(
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == early.id.int)
            .values(created_at=_dt(1))
        )
        await db_session.execute(
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == pos2.id.int)
            .values(created_at=_dt(2))
        )
        await db_session.commit()

        events = await repo.list_all(project.id)
        assert [e.id for e in events] == [early.id, late_first.id, pos2.id]

    async def test_next_position_empty_project_returns_1(self, db_session, project):
        """空项目 next_position = 1."""
        repo = SQLiteTimelineRepository(db_session)
        assert await repo.next_position(project.id) == 1

    async def test_next_position_appends_after_max(self, db_session, project):
        """next_position = 项目内事件 max+1；真删事件不计入 max；项目隔离."""
        repo = SQLiteTimelineRepository(db_session)
        await repo.add(_event(project, "事件A", narrative_position=5))
        assert await repo.next_position(project.id) == 6

        # 重复位置允许 → max 不变
        await repo.add(_event(project, "事件B", narrative_position=5))
        assert await repo.next_position(project.id) == 6

        # 真删事件不计入 max
        high = await repo.add(_event(project, "事件C", narrative_position=100))
        await repo.hard_delete(high.id.int)
        assert await repo.next_position(project.id) == 6

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.next_position(other.id) == 1

    async def test_update_event(self, db_session, project):
        """update 按 id 定位更新字段并返回最新领域对象（含 time_value 清除）."""
        repo = SQLiteTimelineRepository(db_session)
        e = await repo.add(_event(project, "觉醒", time_value=317.5, narrative_position=2))

        updated = await repo.update(
            e.model_copy(
                update={
                    "title": "觉醒·改",
                    "time_value": None,  # 清除世界内时间（置为未知）
                    "narrative_position": 1,
                }
            )
        )
        assert updated.id == e.id
        assert updated.title == "觉醒·改"
        assert updated.time_value is None
        assert updated.narrative_position == 1
        assert updated.updated_at >= e.updated_at

        got = await repo.get(e.id.int)
        assert got is not None
        assert got.title == "觉醒·改"
        assert got.time_value is None

    async def test_update_missing_event_raises_value_error(self, db_session, project):
        """update 不存在的 id → ValueError."""
        repo = SQLiteTimelineRepository(db_session)
        with pytest.raises(ValueError):
            await repo.update(_event(project, "幽灵", id=uuid.UUID(int=99999)))
        await db_session.rollback()

    async def test_hard_delete_event(self, db_session, project):
        """hard_delete 物理删除事件行；重复删除返回 False."""
        repo = SQLiteTimelineRepository(db_session)
        e = await repo.add(_event(project, "觉醒"))

        assert await repo.hard_delete(e.id.int) is True
        assert await repo.get(e.id.int) is None
        assert await repo.hard_delete(e.id.int) is False

    # ── 无唯一约束（spec §2.4）──

    async def test_duplicate_title_position_and_time_allowed(self, db_session, project):
        """title/narrative_position/time_value 重复均可插入（无唯一约束）."""
        repo = SQLiteTimelineRepository(db_session)
        first = await repo.add(_event(project, "回忆", narrative_position=2, time_value=5.0))
        second = await repo.add(_event(project, "回忆", narrative_position=2, time_value=5.0))

        assert second.id != first.id
        events, total = await repo.list(project.id)
        assert total == 2
        assert {e.id for e in events} == {first.id, second.id}

    # ── 硬删除 FK 级联 ──

    async def test_project_hard_delete_cascades_events(self, db_session, project):
        """项目硬删 → 事件行物理删除（DB FK CASCADE）."""
        repo = SQLiteTimelineRepository(db_session)
        await repo.add(_event(project, "觉醒"))
        await repo.add(_event(project, "宗门大比"))

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count = await db_session.execute(select(func.count()).select_from(TimelineEventORM))
        assert count.scalar_one() == 0

    # ── source_chapter_id（F14 跨模块 MODIFY F12）──

    async def test_source_chapter_id_roundtrip_with_none_default(self, db_session, project):
        """add 带 source_chapter_id → get 读回一致（UUID 映射）；手工事件缺省 None."""
        repo = SQLiteTimelineRepository(db_session)
        chapter = ChapterORM(project_id=project.id, title="第一章")
        db_session.add(chapter)
        await db_session.commit()
        await db_session.refresh(chapter)

        extracted = await repo.add(
            _event(project, "觉醒", source_chapter_id=uuid.UUID(int=chapter.id))
        )
        assert extracted.source_chapter_id == uuid.UUID(int=chapter.id)

        manual = await repo.add(_event(project, "手工建档"))
        assert manual.source_chapter_id is None

        # 持久化验证：直接查表（DB int 列）
        row = await db_session.execute(
            select(TimelineEventORM).where(TimelineEventORM.id == extracted.id.int)
        )
        assert row.scalar_one().source_chapter_id == chapter.id

        got = await repo.get(extracted.id.int)
        assert got is not None
        assert got.source_chapter_id == uuid.UUID(int=chapter.id)

        got_manual = await repo.get(manual.id.int)
        assert got_manual is not None
        assert got_manual.source_chapter_id is None

    async def test_list_by_chapter_filters_events_sorted(self, db_session, project):
        """list_by_chapter 按章过滤事件；(narrative_position, created_at)
        ASC 排序；真删不入、跨章互不干扰."""
        repo = SQLiteTimelineRepository(db_session)
        ch1 = ChapterORM(project_id=project.id, title="第一章")
        ch2 = ChapterORM(project_id=project.id, title="第二章")
        db_session.add_all([ch1, ch2])
        await db_session.commit()
        await db_session.refresh(ch1)
        await db_session.refresh(ch2)
        c1 = uuid.UUID(int=ch1.id)
        c2 = uuid.UUID(int=ch2.id)

        late_first = await repo.add(
            _event(project, "一章·后建", source_chapter_id=c1, narrative_position=1)
        )
        early = await repo.add(
            _event(project, "一章·先建", source_chapter_id=c1, narrative_position=1)
        )
        other_ch = await repo.add(
            _event(project, "二章事件", source_chapter_id=c2, narrative_position=5)
        )
        gone = await repo.add(
            _event(project, "一章·已删", source_chapter_id=c1, narrative_position=0)
        )
        await repo.hard_delete(gone.id.int)

        # 注入受控 created_at，使「同位置 → created_at ASC」排序可确定性断言
        await db_session.execute(
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == late_first.id.int)
            .values(created_at=_dt(3))
        )
        await db_session.execute(
            sa_update(TimelineEventORM)
            .where(TimelineEventORM.id == early.id.int)
            .values(created_at=_dt(1))
        )
        await db_session.commit()

        events = await repo.list_by_chapter(project.id, ch1.id)
        assert [e.id for e in events] == [early.id, late_first.id]
        assert all(e.source_chapter_id == c1 for e in events)

        # 跨章互不干扰（二章事件不进一章结果）
        events2 = await repo.list_by_chapter(project.id, ch2.id)
        assert [e.id for e in events2] == [other_ch.id]

        # 无该章事件 → 空列表
        assert await repo.list_by_chapter(project.id, 99999) == []

    async def test_chapter_hard_delete_sets_source_chapter_id_null(self, db_session, project):
        """章节硬删 → 事件 source_chapter_id 置 None（FK ON DELETE SET NULL，事件保留）."""
        repo = SQLiteTimelineRepository(db_session)
        chapter = ChapterORM(project_id=project.id, title="第一章")
        db_session.add(chapter)
        await db_session.commit()
        await db_session.refresh(chapter)

        e = await repo.add(_event(project, "觉醒", source_chapter_id=uuid.UUID(int=chapter.id)))
        assert e.source_chapter_id == uuid.UUID(int=chapter.id)

        ch_row = await db_session.execute(select(ChapterORM).where(ChapterORM.id == chapter.id))
        await db_session.delete(ch_row.scalar_one())
        await db_session.commit()

        got = await repo.get(e.id.int)
        assert got is not None
        assert got.source_chapter_id is None
        # 事件行保留（仅来源置空）
        count = await db_session.execute(select(func.count()).select_from(TimelineEventORM))
        assert count.scalar_one() == 1


# ══ P5 删除引用残留清理（#284 最后一批，spec §2.10/§5.18）══
#
# 生产 foreign_keys=OFF → 删除时间线事件后伏笔 event_id 残留。
# 本段用 OFF fixture 契约「hard_delete 显式清理」（镜像生产，不依赖 FK）。


@pytest.fixture
async def db_session_off_fk():
    """独立 in-memory SQLite — 不设 PRAGMA foreign_keys（默认 OFF，镜像生产）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # 刻意不设置 foreign_keys=ON —— 镜像生产（apply_sqlite_pragma 无此设置）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestP5HardDeleteCleansForeshadowings:
    """P5：hard_delete 显式置空 foreshadowings.event_id——RED 预期 FAIL."""

    async def test_hard_delete_event_sets_foreshadowing_event_id_null(
        self, db_session_off_fk, project
    ):
        """删除事件 → 关联伏笔 event_id 置 None（伏笔保留，仅解除锚点）."""
        repo = SQLiteTimelineRepository(db_session_off_fk)
        e = await repo.add(_event(project, "林尘觉醒"))

        # 直接插入伏笔（ForeshadowingORM，event_id 指向事件）
        fs = ForeshadowingORM(
            title="金手指伏笔",
            project_id=project.id,
            description="",
            event_id=e.id.int,
        )
        db_session_off_fk.add(fs)
        await db_session_off_fk.commit()

        assert await repo.hard_delete(e.id.int) is True

        row = await db_session_off_fk.execute(
            select(ForeshadowingORM).where(ForeshadowingORM.id == fs.id)
        )
        assert row.scalar_one().event_id is None
