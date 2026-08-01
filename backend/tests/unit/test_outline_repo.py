"""SQLiteOutlineRepository 集成测试 — in-memory SQLite（F11 M2 RED→GREEN）.

覆盖 OutlineRepositoryProtocol 全部方法（spec §8.1 / §9 仓储测试）:
- Outline / PlotPoint / StoryArc 三实体 CRUD 往返
- partial unique: 活动同名唯一；软删后可重建同名；恢复旧记录 → IntegrityError
- next_position（空大纲 → 1、追加 → max+1、软删不计入）
- 级联软删/恢复（大纲 ↔ 情节点）、弧线软删 → 成员 arc_id 置 NULL
- list 搜索/分页/排序、list_points 按 position 稳定排序、list_arcs 按 name 升序
- 硬删除 FK 级联（大纲硬删 → 情节点级联；项目硬删 → 三实体级联）

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK CASCADE / SET NULL 语义才生效。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.outline import Outline, PlotPoint, StoryArc
from inkflow.infrastructure.database.models.outline import (
    OutlineORM,
    PlotPointORM,
    StoryArcORM,
)
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository


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
    """一个基础项目（大纲/情节点/弧线的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _outline(project: ProjectORM, name: str, **kw) -> Outline:
    """构造待持久化的大纲领域对象.

    领域 id 为随机 UUID；落库时由 DB 自增分配 int 主键，
    读回时以 uuid.UUID(int=orm.id) 还原（F1 映射惯例）。
    """
    return Outline(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _point(outline: Outline, project: ProjectORM, name: str, **kw) -> PlotPoint:
    """构造待持久化的情节点领域对象."""
    return PlotPoint(
        id=uuid.uuid4(),
        outline_id=outline.id,
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _arc(project: ProjectORM, name: str, **kw) -> StoryArc:
    """构造待持久化的故事弧线领域对象."""
    return StoryArc(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


@pytest.mark.integration
class TestOutlineRepository:
    """SQLiteOutlineRepository 集成测试."""

    # ── Outline CRUD ──

    async def test_add_and_get_outline_roundtrip(self, db_session, project):
        """add 落库并返回领域对象；get 按 int 主键读回，字段与 UUID 映射正确."""
        repo = SQLiteOutlineRepository(db_session)
        saved = await repo.add(
            _outline(
                project,
                "第一卷大纲",
                description="开篇设定",
                sort_order=3,
                extra={"生成标记": True},
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.id == uuid.UUID(int=saved.id.int)
        assert saved.name == "第一卷大纲"
        assert saved.description == "开篇设定"
        assert saved.sort_order == 3
        assert saved.extra == {"生成标记": True}
        assert saved.is_deleted is False

        # 持久化验证：直接查表
        row = await db_session.execute(select(OutlineORM).where(OutlineORM.id == saved.id.int))
        assert row.scalar_one().name == "第一卷大纲"

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.project_id == uuid.UUID(int=project.id)
        assert got.created_at == saved.created_at
        assert got.updated_at == saved.updated_at

    async def test_get_returns_none_for_missing(self, db_session, project):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteOutlineRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_miss_and_excludes_soft_deleted(self, db_session, project):
        """get_by_name 命中活动大纲；未命中/跨项目/软删后均返回 None."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))

        hit = await repo.get_by_name(project.id, "第一卷大纲")
        assert hit is not None and hit.id == o.id
        assert await repo.get_by_name(project.id, "不存在") is None

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.get_by_name(other.id, "第一卷大纲") is None

        # 软删后不再命中
        await repo.soft_delete(o.id.int)
        assert await repo.get_by_name(project.id, "第一卷大纲") is None

    async def test_list_returns_active_outlines_with_total(self, db_session, project):
        """list 排除软删与其他项目，返回 (列表, 总数)."""
        repo = SQLiteOutlineRepository(db_session)
        o1 = await repo.add(_outline(project, "第一卷大纲"))
        o2 = await repo.add(_outline(project, "第二卷大纲"))
        o3 = await repo.add(_outline(project, "番外大纲"))
        await repo.soft_delete(o3.id.int)

        outlines, total = await repo.list(project.id)
        assert total == 2
        assert {o.id for o in outlines} == {o1.id, o2.id}

    async def test_list_search_icontains(self, db_session, project):
        """search 对 name 不区分大小写子串匹配."""
        repo = SQLiteOutlineRepository(db_session)
        await repo.add(_outline(project, "第一卷大纲"))
        await repo.add(_outline(project, "第二卷大纲"))
        await repo.add(_outline(project, "人物设定"))

        outlines, total = await repo.list(project.id, search="大纲")
        assert total == 2
        assert {o.name for o in outlines} == {"第一卷大纲", "第二卷大纲"}

        outlines2, total2 = await repo.list(project.id, search="不存在")
        assert total2 == 0
        assert outlines2 == []

    async def test_list_sort_by_name_and_created_at(self, db_session, project):
        """sort_by=name/created_at 与 sort_desc 生效."""
        repo = SQLiteOutlineRepository(db_session)
        await repo.add(_outline(project, "charlie"))
        await repo.add(_outline(project, "alpha"))
        await repo.add(_outline(project, "bravo"))

        asc, _ = await repo.list(project.id, sort_by="name", sort_desc=False)
        assert [o.name for o in asc] == ["alpha", "bravo", "charlie"]

        desc, _ = await repo.list(project.id, sort_by="name", sort_desc=True)
        assert [o.name for o in desc] == ["charlie", "bravo", "alpha"]

        by_created, _ = await repo.list(project.id, sort_by="created_at", sort_desc=False)
        assert [o.name for o in by_created] == ["charlie", "alpha", "bravo"]

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数."""
        repo = SQLiteOutlineRepository(db_session)
        for i in range(5):
            await repo.add(_outline(project, f"大纲{i}"))

        page1, total = await repo.list(
            project.id, sort_by="name", sort_desc=False, offset=0, limit=2
        )
        page2, _ = await repo.list(project.id, sort_by="name", sort_desc=False, offset=2, limit=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {o.id for o in page1}.isdisjoint({o.id for o in page2})
        # 分页越界 → 空列表（同 F1）
        page3, _ = await repo.list(project.id, offset=99, limit=2)
        assert page3 == []

    async def test_update_outline(self, db_session, project):
        """update 按 id 定位更新字段并返回最新领域对象."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲", description="旧描述", sort_order=1))

        updated = await repo.update(
            o.model_copy(update={"name": "第一卷·改", "description": "新描述", "sort_order": 5})
        )
        assert updated.id == o.id
        assert updated.name == "第一卷·改"
        assert updated.description == "新描述"
        assert updated.sort_order == 5
        assert updated.updated_at >= o.updated_at

        got = await repo.get(o.id.int)
        assert got is not None and got.name == "第一卷·改"

    async def test_soft_delete_outline_then_get_returns_none(self, db_session, project):
        """软删除后 get/get_by_name/list 均不可见；重复软删返回 False."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))

        assert await repo.soft_delete(o.id.int) is True
        assert await repo.get(o.id.int) is None
        assert await repo.get_by_name(project.id, "第一卷大纲") is None
        outlines, total = await repo.list(project.id)
        assert outlines == [] and total == 0

        # 已删除/不存在 → False
        assert await repo.soft_delete(o.id.int) is False
        assert await repo.soft_delete(99999) is False

    async def test_restore_outline(self, db_session, project):
        """restore 恢复软删大纲；恢复未删除/不存在的大纲返回 None（重复操作无毒）."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        await repo.soft_delete(o.id.int)

        restored = await repo.restore(o.id.int)
        assert restored is not None
        assert restored.id == o.id
        assert restored.is_deleted is False
        assert await repo.get(o.id.int) is not None

        assert await repo.restore(o.id.int) is None
        assert await repo.restore(99999) is None

    async def test_hard_delete_outline(self, db_session, project):
        """hard_delete 物理删除大纲行；重复删除返回 False."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))

        assert await repo.hard_delete(o.id.int) is True
        assert await repo.get(o.id.int) is None
        assert await repo.hard_delete(o.id.int) is False

    # ── partial unique ──

    async def test_duplicate_active_outline_name_raises_integrity_error(self, db_session, project):
        """插入第二个活动同名大纲 → IntegrityError（partial unique）."""
        repo = SQLiteOutlineRepository(db_session)
        await repo.add(_outline(project, "第一卷大纲"))

        with pytest.raises(IntegrityError):
            await repo.add(_outline(project, "第一卷大纲"))
        await db_session.rollback()

    async def test_soft_deleted_outline_name_reusable_but_restore_conflicts(
        self, db_session, project
    ):
        """软删后可重建同名；恢复旧大纲与活动同名冲突 → IntegrityError."""
        repo = SQLiteOutlineRepository(db_session)
        first = await repo.add(_outline(project, "第一卷大纲"))
        await repo.soft_delete(first.id.int)

        # partial unique 排除已删除行 → 同名可复用
        second = await repo.add(_outline(project, "第一卷大纲"))
        assert second.id != first.id
        assert second.name == "第一卷大纲"

        # 恢复旧大纲 → 项目内出现两个活动同名 → IntegrityError
        with pytest.raises(IntegrityError):
            await repo.restore(first.id.int)
        await db_session.rollback()

    # ── PlotPoint ──

    async def test_point_crud_roundtrip(self, db_session, project):
        """情节点 add/get/update 全流程，arc_id 可为空."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        p = await repo.add_point(
            _point(o, project, "主角登场", type="开篇", description="林尘踏入青云宗", position=1)
        )

        got = await repo.get_point(p.id.int)
        assert got is not None
        assert got.id == p.id
        assert got.outline_id == o.id
        assert got.project_id == uuid.UUID(int=project.id)
        assert got.name == "主角登场"
        assert got.type == "开篇"
        assert got.description == "林尘踏入青云宗"
        assert got.position == 1
        assert got.arc_id is None
        assert got.is_deleted is False

        updated = await repo.update_point(
            p.model_copy(update={"name": "主角登场·改", "type": "转折", "position": 2})
        )
        assert updated.name == "主角登场·改"
        assert updated.type == "转折"
        assert updated.position == 2

        assert await repo.get_point(99999) is None

    async def test_next_position_empty_then_append(self, db_session, project):
        """next_position 空大纲 → 1；追加 → max+1；软删的情节点不计入."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))

        # 空大纲 → 1
        assert await repo.next_position(o.id.int) == 1

        await repo.add_point(_point(o, project, "情节点一", position=1))
        p2 = await repo.add_point(_point(o, project, "情节点二", position=2))

        # 追加 → max+1
        assert await repo.next_position(o.id.int) == 3

        # 显式 position=0 的记录不计入 max
        p0 = await repo.add_point(_point(o, project, "序章", position=0))
        assert await repo.next_position(o.id.int) == 3

        # 软删后不再计入 max（max 活动 = 1 → 2）
        await repo.soft_delete_point(p2.id.int)
        assert await repo.next_position(o.id.int) == 2
        await repo.hard_delete_point(p0.id.int)

        # 大纲隔离：其他大纲的 position 不影响本大纲
        o2 = await repo.add(_outline(project, "第二卷大纲"))
        assert await repo.next_position(o2.id.int) == 1
        assert await repo.next_position(o.id.int) == 2

    async def test_list_points_sorted_by_position_asc(self, db_session, project):
        """list_points 按 position ASC 稳定排序，排除软删."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        p1 = await repo.add_point(_point(o, project, "情节点一", position=1))
        p3 = await repo.add_point(_point(o, project, "情节点三", position=3))
        p2 = await repo.add_point(_point(o, project, "情节点二", position=2))
        pd = await repo.add_point(_point(o, project, "废弃点", position=0))
        await repo.soft_delete_point(pd.id.int)

        points = await repo.list_points(o.id.int)
        assert [p.name for p in points] == ["情节点一", "情节点二", "情节点三"]
        assert [p.id for p in points] == [p1.id, p2.id, p3.id]

        # 其他大纲的情节点不混入
        o2 = await repo.add(_outline(project, "第二卷大纲"))
        await repo.add_point(_point(o2, project, "另一大纲的点"))
        assert len(await repo.list_points(o.id.int)) == 3

    async def test_list_points_by_arc(self, db_session, project):
        """list_points_by_arc 按弧线聚合活动情节点."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        a1 = await repo.add_arc(_arc(project, "主角成长线"))
        a2 = await repo.add_arc(_arc(project, "反派线"))

        pa = await repo.add_point(_point(o, project, "拜师", arc_id=a1.id))
        pb = await repo.add_point(_point(o, project, "背叛", arc_id=a1.id))
        await repo.add_point(_point(o, project, "阴谋", arc_id=a2.id))
        await repo.add_point(_point(o, project, "无弧线"))

        arcs_points = await repo.list_points_by_arc(a1.id.int)
        assert {p.id for p in arcs_points} == {pa.id, pb.id}
        assert len(await repo.list_points_by_arc(a2.id.int)) == 1
        assert await repo.list_points_by_arc(99999) == []

    async def test_soft_delete_and_hard_delete_point(self, db_session, project):
        """情节点软删后不可见；硬删后物理消失."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        p = await repo.add_point(_point(o, project, "主角登场"))

        assert await repo.soft_delete_point(p.id.int) is True
        assert await repo.get_point(p.id.int) is None
        assert await repo.list_points(o.id.int) == []
        assert await repo.soft_delete_point(p.id.int) is False
        assert await repo.soft_delete_point(99999) is False

        assert await repo.hard_delete_point(p.id.int) is True
        count = await db_session.execute(select(func.count()).select_from(PlotPointORM))
        assert count.scalar_one() == 0
        assert await repo.hard_delete_point(p.id.int) is False

    async def test_restore_point(self, db_session, project):
        """restore_point 恢复软删情节点；重复/不存在返回 None."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        p = await repo.add_point(_point(o, project, "主角登场"))
        await repo.soft_delete_point(p.id.int)

        restored = await repo.restore_point(p.id.int)
        assert restored is not None
        assert restored.id == p.id
        assert restored.is_deleted is False
        assert await repo.get_point(p.id.int) is not None

        assert await repo.restore_point(p.id.int) is None
        assert await repo.restore_point(99999) is None

    # ── 级联软删/恢复/硬删 ──

    async def test_outline_soft_delete_cascades_points(self, db_session, project):
        """大纲软删 → 情节点级联软删；其他大纲的情节点不受影响."""
        repo = SQLiteOutlineRepository(db_session)
        o1 = await repo.add(_outline(project, "第一卷大纲"))
        o2 = await repo.add(_outline(project, "第二卷大纲"))
        p1 = await repo.add_point(_point(o1, project, "情节点一"))
        p2 = await repo.add_point(_point(o1, project, "情节点二"))
        p_other = await repo.add_point(_point(o2, project, "另一大纲的点"))

        assert await repo.soft_delete(o1.id.int) is True
        assert await repo.get_point(p1.id.int) is None
        assert await repo.get_point(p2.id.int) is None
        assert await repo.list_points(o1.id.int) == []

        # 未涉及的大纲不受影响
        assert await repo.get_point(p_other.id.int) is not None

    async def test_restore_outline_cascades_points(self, db_session, project):
        """大纲恢复 → 情节点级联恢复（restore_points_of）."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        p = await repo.add_point(_point(o, project, "情节点一"))

        await repo.soft_delete(o.id.int)
        assert await repo.get_point(p.id.int) is None

        restored = await repo.restore(o.id.int)
        assert restored is not None and restored.id == o.id
        point = await repo.get_point(p.id.int)
        assert point is not None
        assert point.is_deleted is False

    async def test_outline_hard_delete_cascades_points_physically(self, db_session, project):
        """大纲硬删 → 情节点行物理删除（DB FK CASCADE）."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        await repo.add_point(_point(o, project, "情节点一"))
        await repo.add_point(_point(o, project, "情节点二"))

        assert await repo.hard_delete(o.id.int) is True

        count = await db_session.execute(select(func.count()).select_from(PlotPointORM))
        assert count.scalar_one() == 0

    # ── StoryArc ──

    async def test_arc_crud_roundtrip(self, db_session, project):
        """弧线 add/get/update/list（name ASC）全流程."""
        repo = SQLiteOutlineRepository(db_session)
        a1 = await repo.add_arc(_arc(project, "主角成长线", description="从弱到强"))
        await repo.add_arc(_arc(project, "反派线"))

        got = await repo.get_arc(a1.id.int)
        assert got is not None and got.name == "主角成长线"
        assert got.description == "从弱到强"
        assert await repo.get_arc(99999) is None

        # name ASC（SQLite BINARY 排序：主 U+4E3B < 反 U+53CD）
        arcs = await repo.list_arcs(project.id)
        assert [a.name for a in arcs] == ["主角成长线", "反派线"]

        updated = await repo.update_arc(
            a1.model_copy(update={"name": "主角成长线·改", "description": "新说明"})
        )
        assert updated.name == "主角成长线·改"
        assert updated.description == "新说明"
        assert [a.name for a in await repo.list_arcs(project.id)] == ["主角成长线·改", "反派线"]

    async def test_get_arc_by_name_hit_miss_and_excludes_soft_deleted(self, db_session, project):
        """get_arc_by_name 命中活动弧线；未命中/跨项目/软删后均返回 None."""
        repo = SQLiteOutlineRepository(db_session)
        a = await repo.add_arc(_arc(project, "主角成长线"))

        hit = await repo.get_arc_by_name(project.id, "主角成长线")
        assert hit is not None and hit.id == a.id
        assert await repo.get_arc_by_name(project.id, "不存在") is None

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.get_arc_by_name(other.id, "主角成长线") is None

        await repo.soft_delete_arc(a.id.int)
        assert await repo.get_arc_by_name(project.id, "主角成长线") is None

    async def test_soft_delete_arc_clears_member_arc_id(self, db_session, project):
        """弧线软删 → 成员情节点 arc_id 置 NULL（情节点保留）."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        a = await repo.add_arc(_arc(project, "主角成长线"))
        p1 = await repo.add_point(_point(o, project, "拜师", arc_id=a.id))
        p2 = await repo.add_point(_point(o, project, "无弧线点"))

        assert await repo.soft_delete_arc(a.id.int) is True
        assert await repo.get_arc(a.id.int) is None
        assert await repo.soft_delete_arc(a.id.int) is False

        got1 = await repo.get_point(p1.id.int)
        got2 = await repo.get_point(p2.id.int)
        assert got1 is not None and got1.arc_id is None
        assert got2 is not None and got2.arc_id is None
        # 情节点本身仍活动
        assert got1.name == "拜师"

    async def test_restore_arc_restores_arc_only(self, db_session, project):
        """恢复弧线仅恢复弧线本身；成员 arc_id 保持 NULL（不重新挂载）."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        a = await repo.add_arc(_arc(project, "主角成长线"))
        p = await repo.add_point(_point(o, project, "拜师", arc_id=a.id))

        await repo.soft_delete_arc(a.id.int)
        restored = await repo.restore_arc(a.id.int)
        assert restored is not None
        assert restored.id == a.id
        assert restored.is_deleted is False

        got = await repo.get_point(p.id.int)
        assert got is not None and got.arc_id is None
        # 重复恢复/不存在 → None
        assert await repo.restore_arc(a.id.int) is None
        assert await repo.restore_arc(99999) is None

    async def test_duplicate_active_arc_name_raises_and_reusable_after_soft_delete(
        self, db_session, project
    ):
        """活动同名弧线 → IntegrityError；软删后同名可重建；恢复旧弧线冲突 → IntegrityError."""
        repo = SQLiteOutlineRepository(db_session)
        first = await repo.add_arc(_arc(project, "主角成长线"))

        with pytest.raises(IntegrityError):
            await repo.add_arc(_arc(project, "主角成长线"))
        await db_session.rollback()
        # rollback 会使 session 内 ORM 实例过期；重新加载 project 以便后续使用
        await db_session.refresh(project)

        await repo.soft_delete_arc(first.id.int)
        second = await repo.add_arc(_arc(project, "主角成长线"))
        assert second.id != first.id

        with pytest.raises(IntegrityError):
            await repo.restore_arc(first.id.int)
        await db_session.rollback()

    async def test_hard_delete_arc(self, db_session, project):
        """弧线硬删 → 行物理消失（成员 arc_id 由 FK SET NULL）."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        a = await repo.add_arc(_arc(project, "主角成长线"))
        p = await repo.add_point(_point(o, project, "拜师", arc_id=a.id))

        assert await repo.hard_delete_arc(a.id.int) is True
        assert await repo.get_arc(a.id.int) is None

        # FK SET NULL：情节点保留，arc_id 置 NULL
        count = await db_session.execute(select(func.count()).select_from(StoryArcORM))
        assert count.scalar_one() == 0
        got = await repo.get_point(p.id.int)
        assert got is not None and got.arc_id is None
        assert await repo.hard_delete_arc(a.id.int) is False

    # ── FK 级联（项目删除） ──

    async def test_project_hard_delete_cascades_all_three_entities(self, db_session, project):
        """项目硬删 → 大纲/情节点/弧线行物理删除（DB FK CASCADE）."""
        repo = SQLiteOutlineRepository(db_session)
        o = await repo.add(_outline(project, "第一卷大纲"))
        await repo.add_point(_point(o, project, "情节点一"))
        await repo.add_arc(_arc(project, "主角成长线"))

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count_o = await db_session.execute(select(func.count()).select_from(OutlineORM))
        count_p = await db_session.execute(select(func.count()).select_from(PlotPointORM))
        count_a = await db_session.execute(select(func.count()).select_from(StoryArcORM))
        assert count_o.scalar_one() == 0
        assert count_p.scalar_one() == 0
        assert count_a.scalar_one() == 0
