"""SQLiteWorldRepository 集成测试 — in-memory SQLite（F10 仓储层 RED→GREEN）.

覆盖 WorldRepositoryProtocol 全部 11 个方法（spec §8.1 / §9 仓储测试）:
- 条目 CRUD 往返（add/get/list/update/soft_delete/restore/hard_delete）
- get_by_name 命中与未命中（跨项目隔离、软删后不命中）
- partial unique: 活动同名唯一；软删后可重建同名；恢复旧记录 → IntegrityError
- 软删除后 get 返回 None
- list 搜索（name icontains）/category 过滤（含空串 = 未分类）
- list_categories 聚合（计数、排除空类别、count 降序 + category 升序）
- 分页（offset/limit，越界返回空列表）
- 硬删除 FK 级联（项目物理删除 → 条目级联物理删除）

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK CASCADE 语义才生效。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.world import WorldSetting
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldSettingORM
from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository


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
        assert saved.is_deleted is False

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

    async def test_get_by_name_hit_miss_and_excludes_soft_deleted(self, db_session, project):
        """get_by_name 命中活动条目；未命中/跨项目/软删后均返回 None."""
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

        # 软删后不再命中
        await repo.soft_delete(s.id.int)
        assert await repo.get_by_name(project.id, "灵气复苏") is None

    async def test_list_returns_active_settings_with_total(self, db_session, project):
        """list 排除软删与其他项目，返回 (列表, 总数)."""
        repo = SQLiteWorldRepository(db_session)
        s1 = await repo.add(_setting(project, "灵气复苏"))
        s2 = await repo.add(_setting(project, "宗门等级"))
        s3 = await repo.add(_setting(project, "古神禁地"))
        await repo.soft_delete(s3.id.int)

        settings, total = await repo.list(project.id)
        assert total == 2
        assert {s.id for s in settings} == {s1.id, s2.id}

    async def test_list_search_icontains(self, db_session, project):
        """search 对 name 不区分大小写子串匹配."""
        repo = SQLiteWorldRepository(db_session)
        await repo.add(_setting(project, "灵气复苏"))
        await repo.add(_setting(project, "灵气时代"))
        await repo.add(_setting(project, "宗门等级"))

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
        await repo.add(_setting(project, "宗门等级", category="规则"))
        s3 = await repo.add(_setting(project, "无主之地", category=""))

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
        await repo.add(_setting(project, "charlie"))
        await repo.add(_setting(project, "alpha"))
        await repo.add(_setting(project, "bravo"))

        asc, _ = await repo.list(project.id, sort_by="name", sort_desc=False)
        assert [s.name for s in asc] == ["alpha", "bravo", "charlie"]

        desc, _ = await repo.list(project.id, sort_by="name", sort_desc=True)
        assert [s.name for s in desc] == ["charlie", "bravo", "alpha"]

        by_created, _ = await repo.list(project.id, sort_by="created_at", sort_desc=False)
        assert [s.name for s in by_created] == ["charlie", "alpha", "bravo"]

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数；越界返回空列表."""
        repo = SQLiteWorldRepository(db_session)
        for i in range(5):
            await repo.add(_setting(project, f"条目{i}"))

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

    async def test_soft_delete_then_get_returns_none(self, db_session, project):
        """软删除后 get/get_by_name/list 均不可见；重复软删返回 False."""
        repo = SQLiteWorldRepository(db_session)
        s = await repo.add(_setting(project, "灵气复苏"))

        assert await repo.soft_delete(s.id.int) is True
        assert await repo.get(s.id.int) is None
        assert await repo.get_by_name(project.id, "灵气复苏") is None
        settings, total = await repo.list(project.id)
        assert settings == [] and total == 0

        # 已删除/不存在 → False
        assert await repo.soft_delete(s.id.int) is False
        assert await repo.soft_delete(99999) is False

    async def test_restore_setting(self, db_session, project):
        """restore 恢复软删条目；恢复未删除/不存在的条目返回 None（重复操作无毒）."""
        repo = SQLiteWorldRepository(db_session)
        s = await repo.add(_setting(project, "灵气复苏"))
        await repo.soft_delete(s.id.int)

        restored = await repo.restore(s.id.int)
        assert restored is not None
        assert restored.id == s.id
        assert restored.is_deleted is False
        assert await repo.get(s.id.int) is not None

        assert await repo.restore(s.id.int) is None
        assert await repo.restore(99999) is None

    async def test_hard_delete_setting(self, db_session, project):
        """hard_delete 物理删除条目行；重复删除返回 False."""
        repo = SQLiteWorldRepository(db_session)
        s = await repo.add(_setting(project, "灵气复苏"))

        assert await repo.hard_delete(s.id.int) is True
        assert await repo.get(s.id.int) is None
        assert await repo.hard_delete(s.id.int) is False

    # ── partial unique ──

    async def test_duplicate_active_name_raises_integrity_error(self, db_session, project):
        """插入第二个活动同名条目 → IntegrityError（partial unique）."""
        repo = SQLiteWorldRepository(db_session)
        await repo.add(_setting(project, "灵气复苏"))

        with pytest.raises(IntegrityError):
            await repo.add(_setting(project, "灵气复苏"))
        await db_session.rollback()

    async def test_soft_deleted_name_reusable_but_restore_conflicts(self, db_session, project):
        """软删后可重建同名；恢复旧条目与活动同名冲突 → IntegrityError."""
        repo = SQLiteWorldRepository(db_session)
        first = await repo.add(_setting(project, "灵气复苏"))
        await repo.soft_delete(first.id.int)

        # partial unique 排除已删除行 → 同名可复用
        second = await repo.add(_setting(project, "灵气复苏"))
        assert second.id != first.id
        assert second.name == "灵气复苏"

        # 恢复旧条目 → 项目内出现两个活动同名 → IntegrityError
        with pytest.raises(IntegrityError):
            await repo.restore(first.id.int)
        await db_session.rollback()

    # ── list_categories 聚合 ──

    async def test_list_categories_aggregates_counts(self, db_session, project):
        """list_categories 聚合活动条目类别计数：排除空类别与软删，count 降序 + category 升序."""
        repo = SQLiteWorldRepository(db_session)
        await repo.add(_setting(project, "灵气复苏", category="设定"))
        await repo.add(_setting(project, "宗门等级", category="规则"))
        await repo.add(_setting(project, "炼丹术", category="规则"))
        await repo.add(_setting(project, "无主之地", category=""))  # 未分类 → 不计入汇总
        s_del = await repo.add(_setting(project, "古神禁地", category="地理"))
        await repo.soft_delete(s_del.id.int)  # 软删 → 不计入汇总

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
        await repo.add(_setting(project, "灵气复苏"))
        await repo.add(_setting(project, "宗门等级", category="规则"))

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count = await db_session.execute(select(func.count()).select_from(WorldSettingORM))
        assert count.scalar_one() == 0
