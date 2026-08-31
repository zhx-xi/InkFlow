"""SQLiteWorldRepository 集成测试 — in-memory SQLite（F10 仓储层 RED→GREEN）.

覆盖 WorldRepositoryProtocol 方法（spec §8.1 / §9 仓储测试）:
- 条目 CRUD 往返（add/get/list/update/hard_delete）
- get_by_name 命中与未命中（跨项目隔离）
- 全唯一索引: 同层级同名唯一；真删后重建同名
- 真删后 get 返回 None
- list 搜索（name icontains）/category 过滤（含空串 = 未分类）
- list_categories 聚合（计数、排除空类别、count 降序 + category 升序）
- 分页（offset/limit，越界返回空列表）
- 硬删除 FK 级联（项目物理删除 → 条目级联物理删除）

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK CASCADE 语义才生效。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.world import WorldSetting
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldCategoryORM, WorldSettingORM
from inkflow.infrastructure.database.repositories.world_repo import (
    SQLiteWorldRepository,
    _int_to_uuid,
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
    """一个基础项目（世界观条目的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _setting(project: ProjectORM, name: str, **kw) -> WorldSetting:
    """构造待持久化的世界观条目领域对象.

    领域 id 为随机 UUID；落库时由 DB 自增分配 int 主键，
    读回时以 uuid.UUID(int=orm.id) 还原（F1 映射惯例）。
    """
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


@pytest.mark.integration
class TestWorldRepository:
    """SQLiteWorldRepository 集成测试."""

    # ── WorldSetting CRUD ──

    async def test_add_and_get_roundtrip(self, db_session, project):
        """add 落库并返回领域对象；get 按 int 主键读回，字段与 UUID 映射正确."""
        repo = SQLiteWorldRepository(db_session)
        saved = await repo.add(
            _setting(
                project,
                "灵气复苏",
                category="设定",
                content="天地灵气复苏，万物可修行。",
                extra={"别名": ["灵气时代"]},
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.id == uuid.UUID(int=saved.id.int)
        assert saved.name == "灵气复苏"
        assert saved.category == "设定"
        assert saved.content == "天地灵气复苏，万物可修行。"
        assert saved.extra == {"别名": ["灵气时代"]}

        # 持久化验证：直接查表
        row = await db_session.execute(
            select(WorldSettingORM).where(WorldSettingORM.id == saved.id.int)
        )
        assert row.scalar_one().name == "灵气复苏"

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.project_id == uuid.UUID(int=project.id)
        assert got.created_at == saved.created_at
        assert got.updated_at == saved.updated_at

    async def test_get_returns_none_for_missing(self, db_session, project):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteWorldRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_miss(self, db_session, project):
        """get_by_name 命中条目；未命中/跨项目/真删后均返回 None."""
        repo = SQLiteWorldRepository(db_session)
        s = await repo.add(_setting(project, "灵气复苏"))

        hit = await repo.get_by_name(project.id, "灵气复苏")
        assert hit is not None and hit.id == s.id
        assert await repo.get_by_name(project.id, "不存在") is None

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.get_by_name(other.id, "灵气复苏") is None

        # 真删后不再命中
        await repo.hard_delete(s.id.int)
        assert await repo.get_by_name(project.id, "灵气复苏") is None

    async def test_list_returns_settings_with_total(self, db_session, project):
        """list 返回 (列表, 总数)."""
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "灵气复苏"))
        s2 = await repo.add(_setting(project, "宗门等级", parent_id=s1.id))
        s3 = await repo.add(_setting(project, "古神禁地", parent_id=s1.id))

        settings, total = await repo.list(project.id)
        assert total == 3
        assert {s.id for s in settings} == {s1.id, s2.id, s3.id}

    async def test_list_search_icontains(self, db_session, project):
        """search 对 name 不区分大小写子串匹配."""
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "灵气复苏"))
        await repo.add(_setting(project, "灵气时代", parent_id=s1.id))
        await repo.add(_setting(project, "宗门等级", parent_id=s1.id))

        settings, total = await repo.list(project.id, search="灵气")
        assert total == 2
        assert {s.name for s in settings} == {"灵气复苏", "灵气时代"}

        settings2, total2 = await repo.list(project.id, search="不存在")
        assert total2 == 0
        assert settings2 == []

    async def test_list_category_filter(self, db_session, project):
        """category 精确过滤；空串过滤出未分类条目."""
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "灵气复苏", category="设定"))
        await repo.add(_setting(project, "宗门等级", category="规则", parent_id=s1.id))
        s3 = await repo.add(_setting(project, "无主之地", category="", parent_id=s1.id))

        settings, total = await repo.list(project.id, category="设定")
        assert total == 1
        assert [s.id for s in settings] == [s1.id]

        uncategorized, total_u = await repo.list(project.id, category="")
        assert total_u == 1
        assert [s.id for s in uncategorized] == [s3.id]
        assert await repo.list(project.id, category="地理") == ([], 0)

    async def test_list_sort_by_name_and_created_at(self, db_session, project):
        """sort_by=name/created_at 与 sort_desc 生效."""
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "charlie"))
        await repo.add(_setting(project, "alpha", parent_id=s1.id))
        await repo.add(_setting(project, "bravo", parent_id=s1.id))

        asc, _ = await repo.list(project.id, sort_by="name", sort_desc=False)
        assert [s.name for s in asc] == ["alpha", "bravo", "charlie"]

        desc, _ = await repo.list(project.id, sort_by="name", sort_desc=True)
        assert [s.name for s in desc] == ["charlie", "bravo", "alpha"]

        by_created, _ = await repo.list(project.id, sort_by="created_at", sort_desc=False)
        assert [s.name for s in by_created] == ["charlie", "alpha", "bravo"]

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数；越界返回空列表."""
        repo = SQLiteWorldRepository(db_session)
        first = await repo.add(_setting(project, "条目0"))
        for i in range(1, 5):
            await repo.add(_setting(project, f"条目{i}", parent_id=first.id))

        page1, total = await repo.list(
            project.id, sort_by="name", sort_desc=False, offset=0, limit=2
        )
        page2, _ = await repo.list(project.id, sort_by="name", sort_desc=False, offset=2, limit=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {s.id for s in page1}.isdisjoint({s.id for s in page2})
        # 分页越界 → 空列表（同 F1）
        page3, _ = await repo.list(project.id, offset=99, limit=2)
        assert page3 == []

    async def test_update_setting(self, db_session, project):
        """update 按 id 定位更新字段并返回最新领域对象."""
        repo = SQLiteWorldRepository(db_session)
        s = await repo.add(_setting(project, "灵气复苏", category="设定", content="旧内容"))

        updated = await repo.update(
            s.model_copy(update={"name": "灵气复苏·改", "category": "规则", "content": "新内容"})
        )
        assert updated.id == s.id
        assert updated.name == "灵气复苏·改"
        assert updated.category == "规则"
        assert updated.content == "新内容"
        assert updated.updated_at >= s.updated_at

        got = await repo.get(s.id.int)
        assert got is not None and got.name == "灵气复苏·改"

    async def test_hard_delete_setting(self, db_session, project):
        """hard_delete 物理删除条目行；重复删除返回 False."""
        repo = SQLiteWorldRepository(db_session)
        s = await repo.add(_setting(project, "灵气复苏"))

        assert await repo.hard_delete(s.id.int) is True
        assert await repo.get(s.id.int) is None
        assert await repo.hard_delete(s.id.int) is False

    # ── 全唯一索引 ──

    async def test_duplicate_active_name_raises_integrity_error(self, db_session, project):
        """插入同父下第二个同名条目 → IntegrityError（同级全唯一索引，spec §2.4）.

        F35 行为变更（spec §2.1 规则 5）：项目内全局唯一 → 同级唯一。
        顶层同名（parent_id NULL）DB 不再拦截（SQLite unique index NULL 不冲突），
        由 service 层应用层校验（422）；**同级同名仍由 DB 全唯一索引拦截**。
        """
        repo = SQLiteWorldRepository(db_session)
        parent = await repo.add(_setting(project, "青州"))
        await repo.add(_setting(project, "清河县城", parent_id=parent.id))

        with pytest.raises(IntegrityError):
            await repo.add(_setting(project, "清河县城", parent_id=parent.id))
        await db_session.rollback()

    async def test_deleted_name_reusable(self, db_session, project):
        """同父下真删后可重建同名（v1.1 全唯一索引仅约束现存行）."""
        repo = SQLiteWorldRepository(db_session)
        parent = await repo.add(_setting(project, "青州"))
        first = await repo.add(_setting(project, "清河县城", parent_id=parent.id))
        await repo.hard_delete(first.id.int)

        # 全唯一索引仅约束现存行 → 同父下同名可复用
        second = await repo.add(_setting(project, "清河县城", parent_id=parent.id))
        assert second.name == "清河县城"

    # ── list_categories 聚合 ──

    async def test_list_categories_aggregates_counts(self, db_session, project):
        """list_categories 聚合条目类别计数：排除空类别，count 降序 + category 升序."""
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "灵气复苏", category="设定"))
        await repo.add(_setting(project, "宗门等级", category="规则", parent_id=s1.id))
        await repo.add(_setting(project, "炼丹术", category="规则", parent_id=s1.id))
        # 未分类 → 不计入汇总
        await repo.add(_setting(project, "无主之地", category="", parent_id=s1.id))
        s_del = await repo.add(_setting(project, "古神禁地", category="地理", parent_id=s1.id))
        await repo.hard_delete(s_del.id.int)  # 真删 → 不计入汇总

        cats = await repo.list_categories(project.id)
        assert cats == [("规则", 2), ("设定", 1)]

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        assert await repo.list_categories(other.id) == []

    # ── 硬删除 FK 级联 ──

    async def test_project_hard_delete_cascades_settings(self, db_session, project):
        """项目硬删 → 世界观条目行物理删除（DB FK CASCADE）."""
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "灵气复苏"))
        await repo.add(_setting(project, "宗门等级", category="规则", parent_id=s1.id))

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count = await db_session.execute(select(func.count()).select_from(WorldSettingORM))
        assert count.scalar_one() == 0


# ── Phase 3 覆盖率补齐（#104）：_int_to_uuid 辅助 + update 缺失/防御分支 ──


def _patch_execute_returning_none_on_requery(session):
    """把 session.execute 的第 2 次调用替换为「回查无行」假结果（模拟 UPDATE 生效后行被并发删除）.

    返回原始 execute，供测试 finally 还原。
    """
    real_execute = session.execute
    call_no = 0

    async def _fake_execute(stmt, *args, **kwargs):
        nonlocal call_no
        call_no += 1
        if call_no == 2:
            fake_result = mock.MagicMock()
            fake_result.scalar_one_or_none.return_value = None
            return fake_result
        return await real_execute(stmt, *args, **kwargs)

    session.execute = _fake_execute  # type: ignore[method-assign]  # fake execute 覆盖 session 方法
    return real_execute


class TestWorldRepositoryCoverageGaps:
    """world_repo 剩余未覆盖行（Issue #104 Phase 3）."""

    def test_int_to_uuid_helper(self):
        """_int_to_uuid：None 直通 / int→UUID / UUID 直通."""
        assert _int_to_uuid(None) is None
        assert _int_to_uuid(42) == uuid.UUID(int=42)
        u = uuid.UUID(int=7)
        assert _int_to_uuid(u) is u

    async def test_update_setting_missing_raises_value_error(self, db_session, project):
        """update 不存在的 id（rowcount=0）→ ValueError."""
        repo = SQLiteWorldRepository(db_session)
        ghost = _setting(project, "幽灵条目")
        ghost.id = uuid.UUID(int=99999)  # 仓储层 int id：不存在但落在 SQLite 64 位范围内
        with pytest.raises(ValueError, match="WorldSetting 99999 not found"):
            await repo.update(ghost)

    async def test_update_setting_missing_after_update_raises(self, db_session, project):
        """UPDATE 生效（rowcount>0）但回查不到行 → ValueError「not found after update」."""
        repo = SQLiteWorldRepository(db_session)
        s = await repo.add(_setting(project, "灵气复苏"))

        real_execute = _patch_execute_returning_none_on_requery(db_session)
        try:
            with pytest.raises(ValueError, match="not found after update"):
                await repo.update(s.model_copy(update={"name": "改名"}))
        finally:
            db_session.execute = real_execute

    def test_world_setting_orm_repr(self):
        """WorldSettingORM.__repr__ 含 id 与 name（#576 coverage 补测 L123）。"""
        orm = WorldSettingORM(project_id=1, name="灵气复苏")
        s = repr(orm)
        assert "WorldSettingORM" in s
        assert "灵气复苏" in s

    def test_world_category_orm_repr(self):
        """WorldCategoryORM.__repr__ 含 id 与 name（#576 coverage 补测 L182）。"""
        orm = WorldCategoryORM(project_id=1, name="地理")
        s = repr(orm)
        assert "WorldCategoryORM" in s
        assert "地理" in s


# ── F35 地点树（#173）：parent_id 邻接表 / 递归 CTE / 同级唯一 / 列表过滤 ──


@pytest.mark.integration
class TestF35LocationTree:
    """F35 地点树仓储契约（spec §2.4/§5.3/§7 边界 16 + §9 测试策略 1/3/6/8）.

    RED 阶段预期: SQLiteWorldRepository 尚无 get_by_parent_and_name /
    collect_ancestor_ids / list_descendants 方法（AttributeError）、list 无
    parent_id 参数（TypeError）、WorldSetting 无 parent_id 字段（建树时
    extra='ignore' 静默丢弃 → 读回断言 AttributeError）。
    """

    # ── get_by_parent_and_name（同级唯一校验，spec §5.1 ③）──

    async def test_get_by_parent_and_name_same_level_hit(self, db_session, project):
        """同级命中：(project_id, parent_id, name) 三元组精确匹配直接子级.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        state = await repo.add(_setting(project, "青州", parent_id=country.id))
        await repo.add(_setting(project, "清河县城", parent_id=state.id))

        hit = await repo.get_by_parent_and_name(project.id, state.id.int, "清河县城")
        assert hit is not None
        assert hit.name == "清河县城"

    async def test_get_by_parent_and_name_top_level_hit(self, db_session, project):
        """顶层命中：parent_id=None 查询顶层地点（spec §2.4 应用层校验路径）.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        await repo.add(_setting(project, "青州", parent_id=country.id))

        hit = await repo.get_by_parent_and_name(project.id, None, "大越国")
        assert hit is not None and hit.id == country.id

    async def test_get_by_parent_and_name_miss_returns_none(self, db_session, project):
        """未命中（名字/父组合不存在）→ None.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        await repo.add(_setting(project, "青州", parent_id=country.id))

        assert await repo.get_by_parent_and_name(project.id, country.id.int, "不存在") is None
        assert await repo.get_by_parent_and_name(project.id, 99999, "青州") is None

    async def test_get_by_parent_and_name_excludes_deleted(self, db_session, project):
        """真删条目不命中（全唯一索引，spec §2.4）.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        state = await repo.add(_setting(project, "青州", parent_id=country.id))
        await repo.hard_delete(state.id.int)

        assert await repo.get_by_parent_and_name(project.id, country.id.int, "青州") is None

    # ── collect_ancestor_ids（递归 CTE 祖先链，不含自身，spec §5.2/§5.3）──

    async def test_collect_ancestor_ids_three_level_tree(self, db_session, project):
        """3 层树（国→州→县）：collect_ancestor_ids(县) = [州, 国]，不含自身（spec §9 场景 1）.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        state = await repo.add(_setting(project, "青州", parent_id=country.id))
        county = await repo.add(_setting(project, "清河县城", parent_id=state.id))

        ancestors = await repo.collect_ancestor_ids(county.id.int)
        assert ancestors == [state.id.int, country.id.int]  # 近→远，不含自身

    async def test_collect_ancestor_ids_top_level_empty(self, db_session, project):
        """顶层地点祖先链为空列表.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))

        assert await repo.collect_ancestor_ids(country.id.int) == []

    async def test_collect_ancestor_ids_missing_empty(self, db_session, project):
        """不存在的 id → 空列表（CTE 起点无行）.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        assert await repo.collect_ancestor_ids(99999) == []

    # ── list_descendants（递归 CTE 子树，含自身，层序，spec §5.3）──

    async def test_list_descendants_includes_self_level_order(self, db_session, project):
        """子树含自身 + 层序（父先子后，同层 created_at ASC）— 复制/级联删除确定性输出.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        state = await repo.add(_setting(project, "青州", parent_id=country.id))
        county = await repo.add(_setting(project, "清河县城", parent_id=state.id))

        subtree = await repo.list_descendants(country.id.int)
        assert [s.id for s in subtree] == [country.id, state.id, county.id]

    async def test_list_descendants_missing_empty(self, db_session, project):
        """不存在的 id → 空列表（不含自身；不存在无自身可言）.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        assert await repo.list_descendants(99999) == []

    # ── list parent_id 过滤（Q3=A，spec §7 边界 16）──

    async def test_list_parent_filter_direct_children(self, db_session, project):
        """list(parent_id=X) → 仅 X 的直接子级（不含孙代）.
        RED: list 签名无 parent_id → TypeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        state = await repo.add(_setting(project, "青州", parent_id=country.id))
        await repo.add(_setting(project, "清河县城", parent_id=state.id))
        await repo.add(_setting(project, "东大陆", parent_id=state.id))

        children, total = await repo.list(project.id, parent_id=country.id.int)
        assert total == 1
        assert [s.id for s in children] == [state.id]

    async def test_list_top_level_only(self, db_session, project):
        """list(top_level_only=True) → 仅顶层地点（parent_id IS NULL）.
        RED: list 签名无 top_level_only → TypeError.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        await repo.add(_setting(project, "青州", parent_id=country.id))

        tops, total = await repo.list(project.id, top_level_only=True)
        assert total == 1
        assert [s.id for s in tops] == [country.id]

    async def test_list_default_no_filter_backward_compat(self, db_session, project):
        """缺省（不带 parent_id 参数）→ 全量，向后兼容（Q3=A 回归）."""
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        await repo.add(_setting(project, "青州", parent_id=country.id))

        all_s, total = await repo.list(project.id)
        _ = all_s  # 列表内容由后续断言覆盖
        assert total == 2

    # ── get_by_name 确定性（spec §2.4 声明）──

    async def test_get_by_name_deterministic_earliest_created(self, db_session, project):
        """跨层同名多条 → get_by_name 返回最早创建（created_at ASC）一条（spec §2.4
        提取合并锚点确定性声明）.
        ⚠️ RED 阶段预期失败形态: 旧全局唯一索引 uq_world_settings_active_name
        (project_id, name) 仍拦截第二条同名插入 → **IntegrityError**（GREEN 阶段
        ORM 替换为同级唯一索引 (project_id, parent_id, name) 后本用例通过）.
        造数: 第一条走 repo.add（挂青州下）；第二条 core insert 显式 created_at
        更晚（跨层同名，旧索引不区分 parent → 拦截；新索引 NULL/不同父不冲突）.
        """
        repo = SQLiteWorldRepository(db_session)
        country = await repo.add(_setting(project, "大越国"))
        state = await repo.add(_setting(project, "青州", parent_id=country.id))
        first = await repo.add(_setting(project, "旧城区", parent_id=state.id))
        later = _now() + timedelta(minutes=5)
        await db_session.execute(
            insert(WorldSettingORM).values(
                project_id=project.id,
                name="旧城区",
                parent_id=country.id.int,
                created_at=later,
                updated_at=later,
            )
        )
        await db_session.commit()

        hit = await repo.get_by_name(project.id, "旧城区")
        assert hit is not None and hit.id == first.id  # 最早创建一条

    # ── repo 三写点 parent_id 往返（F14 教训，spec §9 场景 8）──

    async def test_add_parent_id_roundtrip(self, db_session, project):
        """写点一：add 带 parent_id → get 读回一致（UUID 领域值）.
        RED: WorldSetting 无 parent_id 字段 → add 静默丢弃 → 读回断言 AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        parent = await repo.add(_setting(project, "大越国"))
        child = await repo.add(_setting(project, "青州", parent_id=parent.id))

        got = await repo.get(child.id.int)
        assert got is not None and got.parent_id == parent.id

    async def test_update_parent_id_roundtrip(self, db_session, project):
        """写点二：update 改 parent_id → get 读回一致.
        RED: add 丢弃 parent_id + update .values() 无 parent_id → 读回断言 AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        p1 = await repo.add(_setting(project, "大越国"))
        p2 = await repo.add(_setting(project, "东大陆", parent_id=p1.id))
        state = await repo.add(_setting(project, "青州", parent_id=p1.id))

        # 显式构造完整实体改挂（不依赖 model_copy(update=...) 对未知字段的行为）
        moved = WorldSetting(
            id=state.id,
            project_id=state.project_id,
            name=state.name,
            category=state.category,
            content=state.content,
            extra=state.extra,
            created_at=state.created_at,
            updated_at=state.updated_at,
            parent_id=p2.id,
        )
        await repo.update(moved)

        got = await repo.get(state.id.int)
        assert got is not None and got.parent_id == p2.id

    async def test_add_without_parent_keeps_none(self, db_session, project):
        """写点三：无 parent_id → 顶层保持 None（边界 X：顶层语义不受影响）."""
        repo = SQLiteWorldRepository(db_session)
        top = await repo.add(_setting(project, "大越国"))

        got = await repo.get(top.id.int)
        assert got is not None and got.parent_id is None


# ── F35 补测（coverage-gap，非 RED）：delete_with_reparent 缺失分支 ──


@pytest.mark.integration
class TestF35DeleteWithReparentCoverage:
    """F35 delete_with_reparent（spec §5.5 D2）补测：自身不存在分支 + 正常路径契约."""

    async def test_delete_with_reparent_missing_setting_returns_false(self, db_session, project):
        """自身不存在 → 子改挂 UPDATE 影响 0 行 + 回查无行 → commit + 返回 False（不报错）.
        # F35 coverage-gap 补测（非 RED）：repo L380-381 未覆盖.
        """
        repo = SQLiteWorldRepository(db_session)
        target = await repo.add(_setting(project, "东大陆"))

        result = await repo.delete_with_reparent(99999, target.id.int)

        assert result is False
        # 子改挂未执行：目标父下无新增子级
        children, _ = await repo.list(project.id, parent_id=target.id.int)
        assert children == []

    async def test_delete_with_reparent_moves_children_and_deletes_self(self, db_session, project):
        """正常路径：直接子改挂新父 + 自身真删（单事务，返回 True）."""
        repo = SQLiteWorldRepository(db_session)
        root = await repo.add(_setting(project, "大陆"))
        old_parent = await repo.add(_setting(project, "青州", parent_id=root.id))
        new_parent = await repo.add(_setting(project, "东大陆", parent_id=root.id))
        child = await repo.add(_setting(project, "清河县城", parent_id=old_parent.id))

        result = await repo.delete_with_reparent(old_parent.id.int, new_parent.id.int)

        assert result is True
        assert await repo.get(old_parent.id.int) is None  # 自身真删
        moved = await repo.get(child.id.int)
        assert moved is not None and moved.parent_id == new_parent.id


# ── F37 跨书复制（#175）：list_all_active（copy 缺省起点全量查询，spec §8）──


@pytest.mark.integration
class TestListAllActive:
    """F37 list_all_active 契约（spec §8：copy 缺省起点全量查询）.

    统一契约签名（父侧定稿，GREEN 按此实现）:
    world_repository.py 新增（Protocol 层）:
      async def list_all_active(self, project_id: int) -> builtins.list[WorldSetting]:
          '''项目内全部条目（v1.1 真删无软删过滤），按 created_at ASC 稳定排序。'''
    world_repo.py 新增（实现层）:
      SELECT WHERE project_id=? ORDER BY created_at ASC

    RED 阶段预期: SQLiteWorldRepository 尚无 list_all_active → AttributeError
    （FAILED 非收集错误）；既有用例保持 PASS。
    """

    async def test_filters_cross_project(self, db_session, project):
        """混合造数: 本项目 + 跨项目 → 只返回本项目条目（真删条目不返回）.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "大越国"))
        s2 = await repo.add(_setting(project, "青州", parent_id=s1.id))
        s_del = await repo.add(_setting(project, "古神禁地", parent_id=s1.id))
        await repo.hard_delete(s_del.id.int)  # 真删 → 不返回

        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        await repo.add(_setting(other, "他书条目"))

        active = await repo.list_all_active(project.id)
        assert [s.id for s in active] == [s1.id, s2.id]

    async def test_sorted_by_created_at_asc(self, db_session, project):
        """排序确定性: 直插两条显式不同 created_at → created_at ASC（repo.add 不保留
        created_at——F36 1l 教训，排序断言必须 core insert 显式时间）.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        t = _now() - timedelta(minutes=10)
        # 早条目 = 根（created_at=t，显式时间戳）；晚条目 = 其子级（created_at=t+5）
        res1 = await db_session.execute(
            insert(WorldSettingORM).values(
                project_id=project.id,
                name="早条目",
                created_at=t,
                updated_at=t,
            )
        )
        root_id = res1.inserted_primary_key[0]
        await db_session.execute(
            insert(WorldSettingORM).values(
                project_id=project.id,
                name="晚条目",
                parent_id=root_id,
                created_at=t + timedelta(minutes=5),
                updated_at=t + timedelta(minutes=5),
            )
        )
        await db_session.commit()

        active = await repo.list_all_active(project.id)
        assert [s.name for s in active] == ["早条目", "晚条目"]

    async def test_empty_project_returns_empty_list(self, db_session, project):
        """空项目（无任何条目）→ 空列表.
        RED: 方法不存在 → AttributeError.
        """
        repo = SQLiteWorldRepository(db_session)
        assert await repo.list_all_active(project.id) == []


@pytest.mark.integration
class TestWorldCategoryRepository:
    """SQLiteWorldRepository 分类 CRUD 集成测试（v1.2，issue #389）.

    GREEN 契约：WorldCategoryORM（world_categories 表）+ repo 分类方法：
      create_category(project_id, name) -> WorldCategory
      get_category(category_id) -> WorldCategory | None
      get_category_by_name(project_id, name) -> WorldCategory | None
      list_world_categories(project_id) -> list[tuple[WorldCategory, int]]
      rename_category(category_id, name) -> WorldCategory | None（反向同步条目 category）
      delete_category(category_id) -> bool（反向清空条目 category）

    RED: 方法不存在 → AttributeError（WorldCategoryORM 缺失仅影响 create_all，
    分类方法调用即 AttributeError）。
    """

    async def test_create_and_get_category_roundtrip(self, db_session, project):
        """create_category 落库 + get_category 读回（name/UUID 映射正确；kind 缺省 geo）."""
        repo = SQLiteWorldRepository(db_session)
        created = await repo.create_category(project.id, "势力")
        assert created.name == "势力"
        assert created.kind == "geo"
        assert created.project_id == uuid.UUID(int=project.id)
        fetched = await repo.get_category(created.id.int)
        assert fetched is not None
        assert fetched.name == "势力"
        assert fetched.kind == "geo"

    async def test_create_category_with_kind_roundtrip(self, db_session, project):
        """create_category 显式 kind='abstract' → 落库 + 读回 kind='abstract'."""
        repo = SQLiteWorldRepository(db_session)
        created = await repo.create_category(project.id, "势力", "abstract")
        assert created.kind == "abstract"
        fetched = await repo.get_category(created.id.int)
        assert fetched is not None
        assert fetched.kind == "abstract"

    async def test_get_category_by_name_hit_and_miss(self, db_session, project):
        """get_category_by_name 命中 / 未命中."""
        repo = SQLiteWorldRepository(db_session)
        await repo.create_category(project.id, "势力")
        hit = await repo.get_category_by_name(project.id, "势力")
        assert hit is not None
        assert hit.name == "势力"
        miss = await repo.get_category_by_name(project.id, "不存在")
        assert miss is None

    async def test_create_duplicate_name_integrity_error(self, db_session, project):
        """同名分类 → IntegrityError（(project_id, name) 全唯一索引）."""
        repo = SQLiteWorldRepository(db_session)
        await repo.create_category(project.id, "势力")
        with pytest.raises(IntegrityError):
            await repo.create_category(project.id, "势力")

    async def test_list_world_categories_with_count(self, db_session, project):
        """list_world_categories 返回 (实体, 条目数)；空类别条目不计数."""
        repo = SQLiteWorldRepository(db_session)
        await repo.create_category(project.id, "势力")
        # 造两条 category=势力 + 一条未分类条目
        s1 = await repo.add(_setting(project, "宗门体系", category="势力"))
        await repo.add(_setting(project, "功法等级", category="势力", parent_id=s1.id))
        await repo.add(_setting(project, "未分类条目", category="", parent_id=s1.id))
        result = await repo.list_world_categories(project.id)
        assert len(result) == 1
        cat, count = result[0]
        assert cat.name == "势力"
        assert count == 2

    async def test_rename_category_syncs_entry_category(self, db_session, project):
        """重命名分类 → 同名字符串条目 category 同步改新名（D2=A 重命名侧）."""
        repo = SQLiteWorldRepository(db_session)
        created = await repo.create_category(project.id, "势力")
        entry = await repo.add(_setting(project, "宗门体系", category="势力"))
        renamed = await repo.rename_category(created.id.int, "宗门")
        assert renamed is not None
        assert renamed.name == "宗门"
        # 条目 category 同步
        fetched_entry = await repo.get(entry.id.int)
        assert fetched_entry is not None
        assert fetched_entry.category == "宗门"

    async def test_delete_category_clears_entry_category(self, db_session, project):
        """删除分类 → 同名字符串条目 category 置空（D2=A 删除侧）."""
        repo = SQLiteWorldRepository(db_session)
        created = await repo.create_category(project.id, "势力")
        entry = await repo.add(_setting(project, "宗门体系", category="势力"))
        ok = await repo.delete_category(created.id.int)
        assert ok is True
        # 分类实体已删
        assert await repo.get_category(created.id.int) is None
        # 条目 category 置空
        fetched_entry = await repo.get(entry.id.int)
        assert fetched_entry is not None
        assert fetched_entry.category == ""

    async def test_rename_category_not_found_returns_none(self, db_session, project):
        """重命名不存在的分类 → None（覆盖率：不存在分支）."""
        repo = SQLiteWorldRepository(db_session)
        assert await repo.rename_category(999999, "宗门") is None

    async def test_delete_category_not_found_returns_false(self, db_session, project):
        """删除不存在的分类 → False（覆盖率：不存在分支）."""
        repo = SQLiteWorldRepository(db_session)
        assert await repo.delete_category(999999) is False
