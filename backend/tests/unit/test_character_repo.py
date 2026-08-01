"""SQLiteCharacterRepository 集成测试 — in-memory SQLite（F9 B2 RED→GREEN）.

覆盖 CharacterRepositoryProtocol 全部 23 个方法（spec §8.1 / §9 仓储测试）:
- Character / CharacterGroup / CharacterRelation CRUD 往返
- partial unique: 活动同名唯一；软删后可重建同名；恢复旧记录 → IntegrityError
- 级联软删/恢复（角色 ↔ 关系双向）、分组删除后成员 group_id 置 NULL
- list_relations 双向查询、分页与搜索排序
- 硬删除 FK 级联（角色/项目物理删除后关联行消失）

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
from inkflow.domain.models.character import Character, CharacterGroup, CharacterRelation
from inkflow.infrastructure.database.models.character import (
    CharacterGroupORM,
    CharacterORM,
    CharacterRelationORM,
)
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.character_repo import SQLiteCharacterRepository


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
    """一个基础项目（角色/分组/关系的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _char(project: ProjectORM, name: str, **kw) -> Character:
    """构造待持久化的角色领域对象.

    领域 id 为随机 UUID；落库时由 DB 自增分配 int 主键，
    读回时以 uuid.UUID(int=orm.id) 还原（F1 映射惯例）。
    """
    return Character(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _group(project: ProjectORM, name: str, **kw) -> CharacterGroup:
    """构造待持久化的分组领域对象."""
    return CharacterGroup(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _relation(
    project: ProjectORM, from_char: Character, to_char: Character, rtype: str, **kw
) -> CharacterRelation:
    """构造待持久化的关系领域对象."""
    return CharacterRelation(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        from_character_id=from_char.id,
        to_character_id=to_char.id,
        relation_type=rtype,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


@pytest.mark.integration
class TestCharacterRepository:
    """SQLiteCharacterRepository 集成测试."""

    # ── Character CRUD ──

    async def test_add_and_get_character_roundtrip(self, db_session, project):
        """add 落库并返回领域对象；get 按 int 主键读回，字段与 UUID 映射正确."""
        repo = SQLiteCharacterRepository(db_session)
        saved = await repo.add(
            _char(
                project,
                "林尘",
                personality="沉稳",
                background="青云宗弟子",
                goals="成仙",
                extra={"外貌": "青衫"},
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.id == uuid.UUID(int=saved.id.int)
        assert saved.name == "林尘"
        assert saved.personality == "沉稳"
        assert saved.background == "青云宗弟子"
        assert saved.goals == "成仙"
        assert saved.group_id is None
        assert saved.extra == {"外貌": "青衫"}
        assert saved.is_deleted is False

        # 持久化验证：直接查表
        row = await db_session.execute(select(CharacterORM).where(CharacterORM.id == saved.id.int))
        assert row.scalar_one().name == "林尘"

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.project_id == uuid.UUID(int=project.id)
        assert got.created_at == saved.created_at
        assert got.updated_at == saved.updated_at

    async def test_get_returns_none_for_missing(self, db_session, project):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteCharacterRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_miss_and_excludes_soft_deleted(self, db_session, project):
        """get_by_name 命中活动角色；未命中/跨项目/软删后均返回 None."""
        repo = SQLiteCharacterRepository(db_session)
        c = await repo.add(_char(project, "林尘"))

        hit = await repo.get_by_name(project.id, "林尘")
        assert hit is not None and hit.id == c.id
        assert await repo.get_by_name(project.id, "不存在") is None

        # 项目隔离
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.get_by_name(other.id, "林尘") is None

        # 软删后不再命中
        await repo.soft_delete(c.id.int)
        assert await repo.get_by_name(project.id, "林尘") is None

    async def test_list_returns_active_characters_with_total(self, db_session, project):
        """list 排除软删与其他项目，返回 (列表, 总数)."""
        repo = SQLiteCharacterRepository(db_session)
        c1 = await repo.add(_char(project, "林尘"))
        c2 = await repo.add(_char(project, "阿澈"))
        c3 = await repo.add(_char(project, "青云真人"))
        await repo.soft_delete(c3.id.int)

        chars, total = await repo.list(project.id)
        assert total == 2
        assert {c.id for c in chars} == {c1.id, c2.id}

    async def test_list_search_icontains(self, db_session, project):
        """search 对 name 不区分大小写子串匹配."""
        repo = SQLiteCharacterRepository(db_session)
        await repo.add(_char(project, "林尘"))
        await repo.add(_char(project, "林晚"))
        await repo.add(_char(project, "阿澈"))

        chars, total = await repo.list(project.id, search="林")
        assert total == 2
        assert {c.name for c in chars} == {"林尘", "林晚"}

        chars2, total2 = await repo.list(project.id, search="不存在")
        assert total2 == 0
        assert chars2 == []

    async def test_list_group_filter(self, db_session, project):
        """group_id 过滤仅返回该分组内的活动角色."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c1 = await repo.add(_char(project, "林尘", group_id=g.id))
        await repo.add(_char(project, "阿澈"))

        chars, total = await repo.list(project.id, group_id=g.id.int)
        assert total == 1
        assert [c.id for c in chars] == [c1.id]

    async def test_list_sort_by_name_and_created_at(self, db_session, project):
        """sort_by=name/created_at 与 sort_desc 生效."""
        repo = SQLiteCharacterRepository(db_session)
        await repo.add(_char(project, "charlie"))
        await repo.add(_char(project, "alpha"))
        await repo.add(_char(project, "bravo"))

        asc, _ = await repo.list(project.id, sort_by="name", sort_desc=False)
        assert [c.name for c in asc] == ["alpha", "bravo", "charlie"]

        desc, _ = await repo.list(project.id, sort_by="name", sort_desc=True)
        assert [c.name for c in desc] == ["charlie", "bravo", "alpha"]

        by_created, _ = await repo.list(project.id, sort_by="created_at", sort_desc=False)
        assert [c.name for c in by_created] == ["charlie", "alpha", "bravo"]

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数."""
        repo = SQLiteCharacterRepository(db_session)
        for i in range(5):
            await repo.add(_char(project, f"角色{i}"))

        page1, total = await repo.list(
            project.id, sort_by="name", sort_desc=False, offset=0, limit=2
        )
        page2, _ = await repo.list(project.id, sort_by="name", sort_desc=False, offset=2, limit=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {c.id for c in page1}.isdisjoint({c.id for c in page2})
        # 分页越界 → 空列表（同 F1）
        page3, _ = await repo.list(project.id, offset=99, limit=2)
        assert page3 == []

    async def test_update_character(self, db_session, project):
        """update 按 id 定位更新字段并返回最新领域对象."""
        repo = SQLiteCharacterRepository(db_session)
        c = await repo.add(_char(project, "林尘", personality="旧性格"))

        updated = await repo.update(
            c.model_copy(update={"name": "林尘·改", "personality": "新性格", "goals": "变强"})
        )
        assert updated.id == c.id
        assert updated.name == "林尘·改"
        assert updated.personality == "新性格"
        assert updated.goals == "变强"
        assert updated.updated_at >= c.updated_at

        got = await repo.get(c.id.int)
        assert got is not None and got.name == "林尘·改"

    async def test_soft_delete_character_then_get_returns_none(self, db_session, project):
        """软删除后 get/get_by_name/list 均不可见；重复软删返回 False."""
        repo = SQLiteCharacterRepository(db_session)
        c = await repo.add(_char(project, "林尘"))

        assert await repo.soft_delete(c.id.int) is True
        assert await repo.get(c.id.int) is None
        assert await repo.get_by_name(project.id, "林尘") is None
        chars, total = await repo.list(project.id)
        assert chars == [] and total == 0

        # 已删除/不存在 → False
        assert await repo.soft_delete(c.id.int) is False
        assert await repo.soft_delete(99999) is False

    async def test_restore_character(self, db_session, project):
        """restore 恢复软删角色；恢复未删除/不存在的角色返回 None（重复操作无毒）."""
        repo = SQLiteCharacterRepository(db_session)
        c = await repo.add(_char(project, "林尘"))
        await repo.soft_delete(c.id.int)

        restored = await repo.restore(c.id.int)
        assert restored is not None
        assert restored.id == c.id
        assert restored.is_deleted is False
        assert await repo.get(c.id.int) is not None

        assert await repo.restore(c.id.int) is None
        assert await repo.restore(99999) is None

    async def test_hard_delete_character(self, db_session, project):
        """hard_delete 物理删除角色行；重复删除返回 False."""
        repo = SQLiteCharacterRepository(db_session)
        c = await repo.add(_char(project, "林尘"))

        assert await repo.hard_delete(c.id.int) is True
        assert await repo.get(c.id.int) is None
        assert await repo.hard_delete(c.id.int) is False

    # ── partial unique ──

    async def test_duplicate_active_name_raises_integrity_error(self, db_session, project):
        """插入第二个活动同名角色 → IntegrityError（partial unique）."""
        repo = SQLiteCharacterRepository(db_session)
        await repo.add(_char(project, "林尘"))

        with pytest.raises(IntegrityError):
            await repo.add(_char(project, "林尘"))
        await db_session.rollback()

    async def test_soft_deleted_name_reusable_but_restore_conflicts(self, db_session, project):
        """软删后可重建同名；恢复旧角色与活动同名冲突 → IntegrityError."""
        repo = SQLiteCharacterRepository(db_session)
        first = await repo.add(_char(project, "林尘"))
        await repo.soft_delete(first.id.int)

        # partial unique 排除已删除行 → 同名可复用
        second = await repo.add(_char(project, "林尘"))
        assert second.id != first.id
        assert second.name == "林尘"

        # 恢复旧角色 → 项目内出现两个活动同名 → IntegrityError
        with pytest.raises(IntegrityError):
            await repo.restore(first.id.int)
        await db_session.rollback()

    # ── CharacterGroup ──

    async def test_group_crud_roundtrip(self, db_session, project):
        """分组 add/get/list（sort_order 升序）/update/软删全流程."""
        repo = SQLiteCharacterRepository(db_session)
        g1 = await repo.add_group(_group(project, "主角团", sort_order=2))
        g2 = await repo.add_group(_group(project, "反派", sort_order=1))

        got = await repo.get_group(g1.id.int)
        assert got is not None and got.name == "主角团"
        assert await repo.get_group(99999) is None

        groups = await repo.list_groups(project.id)
        assert [g.name for g in groups] == ["反派", "主角团"]

        updated = await repo.update_group(
            g1.model_copy(update={"name": "主角团·改", "sort_order": 0})
        )
        assert updated.name == "主角团·改"
        assert updated.sort_order == 0

        assert await repo.soft_delete_group(g2.id.int) is True
        assert await repo.get_group(g2.id.int) is None
        assert [g.name for g in await repo.list_groups(project.id)] == ["主角团·改"]

    async def test_soft_delete_group_sets_member_group_id_null(self, db_session, project):
        """分组软删后，成员角色 group_id 置 NULL（角色本身保留）."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c1 = await repo.add(_char(project, "林尘", group_id=g.id))
        c2 = await repo.add(_char(project, "阿澈", group_id=g.id))

        assert await repo.soft_delete_group(g.id.int) is True
        assert await repo.get_group(g.id.int) is None

        got1 = await repo.get(c1.id.int)
        got2 = await repo.get(c2.id.int)
        assert got1 is not None and got1.group_id is None
        assert got2 is not None and got2.group_id is None
        # 角色仍活动
        assert got1.name == "林尘"

    async def test_hard_delete_group_sets_member_group_id_null(self, db_session, project):
        """分组硬删后，成员角色 group_id 置 NULL，分组行物理消失."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c = await repo.add(_char(project, "林尘", group_id=g.id))

        assert await repo.hard_delete_group(g.id.int) is True
        assert await repo.get_group(g.id.int) is None
        got = await repo.get(c.id.int)
        assert got is not None and got.group_id is None
        assert await repo.hard_delete_group(g.id.int) is False

    # ── CharacterRelation ──

    async def test_relation_crud_roundtrip(self, db_session, project):
        """关系 add/get/get_relation_by_key/update 全流程."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        rel = await repo.add_relation(_relation(project, a, b, "师徒", description="旧说明"))

        got = await repo.get_relation(rel.id.int)
        assert got is not None
        assert got.from_character_id == a.id
        assert got.to_character_id == b.id
        assert got.relation_type == "师徒"
        assert got.description == "旧说明"

        by_key = await repo.get_relation_by_key(a.id.int, b.id.int, "师徒")
        assert by_key is not None and by_key.id == rel.id
        assert await repo.get_relation_by_key(a.id.int, b.id.int, "宿敌") is None

        updated = await repo.update_relation(
            rel.model_copy(update={"description": "新说明", "relation_type": "亦师亦友"})
        )
        assert updated.description == "新说明"
        assert updated.relation_type == "亦师亦友"

    async def test_list_relations_bidirectional(self, db_session, project):
        """list_relations 返回角色作为 from 或 to 的全部活动关系（双向）."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        c = await repo.add(_char(project, "青云真人"))
        r1 = await repo.add_relation(_relation(project, a, b, "师徒"))
        r2 = await repo.add_relation(_relation(project, c, a, "宿敌"))

        rels = await repo.list_relations(project.id, character_id=a.id.int)
        assert {r.id for r in rels} == {r1.id, r2.id}

        # 不传 character_id → 项目内全部活动关系
        all_rels = await repo.list_relations(project.id)
        assert len(all_rels) == 2

    async def test_duplicate_active_relation_raises_integrity_error(self, db_session, project):
        """同 (from, to, relation_type) 活动关系重复插入 → IntegrityError."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        await repo.add_relation(_relation(project, a, b, "师徒"))

        with pytest.raises(IntegrityError):
            await repo.add_relation(_relation(project, a, b, "师徒"))
        await db_session.rollback()

    async def test_soft_delete_and_hard_delete_relation(self, db_session, project):
        """关系软删后不可见；硬删后物理消失."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        r = await repo.add_relation(_relation(project, a, b, "师徒"))

        assert await repo.soft_delete_relation(r.id.int) is True
        assert await repo.get_relation(r.id.int) is None
        assert await repo.list_relations(project.id) == []
        assert await repo.soft_delete_relation(r.id.int) is False

        assert await repo.hard_delete_relation(r.id.int) is True
        count = await db_session.execute(select(func.count()).select_from(CharacterRelationORM))
        assert count.scalar_one() == 0
        assert await repo.hard_delete_relation(r.id.int) is False

    # ── 级联软删/恢复/硬删 ──

    async def test_soft_delete_character_cascades_relations_bidirectional(
        self, db_session, project
    ):
        """角色软删 → 其作为 from 或 to 的关系全部级联软删."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        c = await repo.add(_char(project, "青云真人"))
        r_out = await repo.add_relation(_relation(project, a, b, "师徒"))
        r_in = await repo.add_relation(_relation(project, c, a, "宿敌"))
        d = await repo.add(_char(project, "路人"))
        r_other = await repo.add_relation(_relation(project, b, d, "朋友"))

        assert await repo.soft_delete(a.id.int) is True
        assert await repo.get(a.id.int) is None

        # 双向关系均被级联软删
        assert await repo.get_relation(r_out.id.int) is None
        assert await repo.get_relation(r_in.id.int) is None
        assert await repo.list_relations(project.id, character_id=a.id.int) == []

        # 未涉及的关系不受影响
        assert await repo.get_relation(r_other.id.int) is not None

    async def test_restore_character_cascades_relations(self, db_session, project):
        """角色恢复 → 其双向关系级联恢复（restore_relations_of）."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        r = await repo.add_relation(_relation(project, a, b, "师徒"))

        await repo.soft_delete(a.id.int)
        assert await repo.get_relation(r.id.int) is None

        restored = await repo.restore(a.id.int)
        assert restored is not None and restored.id == a.id
        rel = await repo.get_relation(r.id.int)
        assert rel is not None
        assert rel.relation_type == "师徒"
        assert rel.is_deleted is False

    async def test_hard_delete_character_cascades_relations_physically(self, db_session, project):
        """角色硬删 → 关联关系行物理删除（DB FK CASCADE）."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        await repo.add_relation(_relation(project, a, b, "师徒"))
        await repo.add_relation(_relation(project, b, a, "宿敌"))

        assert await repo.hard_delete(a.id.int) is True

        count = await db_session.execute(select(func.count()).select_from(CharacterRelationORM))
        assert count.scalar_one() == 0

    async def test_project_hard_delete_cascades_characters_and_groups(self, db_session, project):
        """项目硬删 → 角色/分组/关系行物理删除（DB FK CASCADE）."""
        repo = SQLiteCharacterRepository(db_session)
        await repo.add(_char(project, "林尘"))
        g = await repo.add_group(_group(project, "主角团"))
        await repo.add(_char(project, "阿澈", group_id=g.id))

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count_c = await db_session.execute(select(func.count()).select_from(CharacterORM))
        count_g = await db_session.execute(select(func.count()).select_from(CharacterGroupORM))
        count_r = await db_session.execute(select(func.count()).select_from(CharacterRelationORM))
        assert count_c.scalar_one() == 0
        assert count_g.scalar_one() == 0
        assert count_r.scalar_one() == 0
