"""SQLiteCharacterRepository 集成测试 — in-memory SQLite（F9 B2 RED→GREEN）.

覆盖 CharacterRepositoryProtocol 方法（spec §8.1 / §9 仓储测试）:
- Character / CharacterGroup / CharacterRelation CRUD 往返
- 全唯一索引: 同名唯一；真删后重建同名
- 真删后 get 返回 None
- 分组删除后成员关联行消失（角色本身保留）
- list_relations 双向查询、分页与搜索排序
- 硬删除 FK 级联（角色/项目物理删除后关联行消失）

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK CASCADE / SET NULL 语义才生效。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest import mock

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
        assert saved.group_ids == []
        assert saved.extra == {"外貌": "青衫"}

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

    async def test_get_by_name_hit_miss(self, db_session, project):
        """get_by_name 命中角色；未命中/跨项目/真删后均返回 None."""
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

        # 真删后不再命中
        await repo.hard_delete(c.id.int)
        assert await repo.get_by_name(project.id, "林尘") is None

    async def test_list_returns_characters_with_total(self, db_session, project):
        """list 返回 (列表, 总数)."""
        repo = SQLiteCharacterRepository(db_session)
        c1 = await repo.add(_char(project, "林尘"))
        c2 = await repo.add(_char(project, "阿澈"))
        c3 = await repo.add(_char(project, "青云真人"))

        chars, total = await repo.list(project.id)
        assert total == 3
        assert {c.id for c in chars} == {c1.id, c2.id, c3.id}

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
        c1 = await repo.add(_char(project, "林尘", group_ids=[g.id]))
        await repo.add(_char(project, "阿澈"))

        chars, total = await repo.list(project.id, group_id=g.id.int)
        assert total == 1
        assert [c.id for c in chars] == [c1.id]
        assert c1.group_ids == [g.id]

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

    async def test_hard_delete_character(self, db_session, project):
        """hard_delete 物理删除角色行；重复删除返回 False."""
        repo = SQLiteCharacterRepository(db_session)
        c = await repo.add(_char(project, "林尘"))

        assert await repo.hard_delete(c.id.int) is True
        assert await repo.get(c.id.int) is None
        assert await repo.hard_delete(c.id.int) is False

    # ── 全唯一索引 ──

    async def test_duplicate_active_name_raises_integrity_error(self, db_session, project):
        """插入第二个同名角色 → IntegrityError（全唯一索引）."""
        repo = SQLiteCharacterRepository(db_session)
        await repo.add(_char(project, "林尘"))

        with pytest.raises(IntegrityError):
            await repo.add(_char(project, "林尘"))
        await db_session.rollback()

    async def test_deleted_name_reusable(self, db_session, project):
        """真删后可重建同名（v1.1 全唯一索引仅约束现存行）."""
        repo = SQLiteCharacterRepository(db_session)
        first = await repo.add(_char(project, "林尘"))
        await repo.hard_delete(first.id.int)

        # 全唯一索引仅约束现存行 → 同名可复用
        second = await repo.add(_char(project, "林尘"))
        assert second.name == "林尘"

    # ── CharacterGroup ──

    async def test_group_crud_roundtrip(self, db_session, project):
        """分组 add/get/list（sort_order 升序）/update/真删全流程."""
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

        assert await repo.hard_delete_group(g2.id.int) is True
        assert await repo.get_group(g2.id.int) is None
        assert [g.name for g in await repo.list_groups(project.id)] == ["主角团·改"]

    async def test_hard_delete_group_removes_memberships(self, db_session, project):
        """分组硬删后，关联行消失（成员角色 group_ids 清空），分组行物理消失."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c = await repo.add(_char(project, "林尘", group_ids=[g.id]))
        assert c.group_ids == [g.id]

        assert await repo.hard_delete_group(g.id.int) is True
        assert await repo.get_group(g.id.int) is None
        got = await repo.get(c.id.int)
        assert got is not None and got.group_ids == []
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

    async def test_hard_delete_relation(self, db_session, project):
        """关系真删后物理消失；重复删除返回 False."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        r = await repo.add_relation(_relation(project, a, b, "师徒"))

        assert await repo.hard_delete_relation(r.id.int) is True
        count = await db_session.execute(select(func.count()).select_from(CharacterRelationORM))
        assert count.scalar_one() == 0
        assert await repo.hard_delete_relation(r.id.int) is False

    # ── 级联真删 ──

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
        await repo.add(_char(project, "阿澈", group_ids=[g.id]))

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count_c = await db_session.execute(select(func.count()).select_from(CharacterORM))
        count_g = await db_session.execute(select(func.count()).select_from(CharacterGroupORM))
        count_r = await db_session.execute(select(func.count()).select_from(CharacterRelationORM))
        assert count_c.scalar_one() == 0
        assert count_g.scalar_one() == 0
        assert count_r.scalar_one() == 0


# ── Phase 3 覆盖率补齐（#104）：update 缺失/防御分支 + 分组软删 None 分支 + ORM __repr__ ──


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


class TestCharacterRepositoryCoverageGaps:
    """character_repo 剩余未覆盖行（Issue #104 Phase 3）."""

    # ── update 不存在 → ValueError ──

    async def test_update_character_missing_raises_value_error(self, db_session, project):
        """update 不存在的 id（rowcount=0）→ ValueError."""
        repo = SQLiteCharacterRepository(db_session)
        ghost = _char(project, "幽灵")
        ghost.id = uuid.UUID(int=99999)  # 仓储层 int id：不存在但落在 SQLite 64 位范围内
        with pytest.raises(ValueError, match="Character 99999 not found"):
            await repo.update(ghost)

    async def test_update_group_missing_raises_value_error(self, db_session, project):
        """update_group 不存在的 id（rowcount=0）→ ValueError."""
        repo = SQLiteCharacterRepository(db_session)
        ghost = _group(project, "幽灵组")
        ghost.id = uuid.UUID(int=99999)
        with pytest.raises(ValueError, match="CharacterGroup 99999 not found"):
            await repo.update_group(ghost)

    async def test_update_relation_missing_raises_value_error(self, db_session, project):
        """update_relation 不存在的 id（rowcount=0）→ ValueError."""
        repo = SQLiteCharacterRepository(db_session)
        # from/to 用小整数 UUID（避免 128 位 int 超出 SQLite INTEGER 绑定范围）
        ghost = CharacterRelation(
            id=uuid.UUID(int=99999),
            project_id=uuid.UUID(int=project.id),
            from_character_id=uuid.UUID(int=1),
            to_character_id=uuid.UUID(int=2),
            relation_type="师徒",
            created_at=_now(),
            updated_at=_now(),
        )
        with pytest.raises(ValueError, match="CharacterRelation 99999 not found"):
            await repo.update_relation(ghost)

    # ── update 后回查无行 → ValueError（防御分支，模拟并发删除） ──

    async def test_update_character_missing_after_update_raises(self, db_session, project):
        """UPDATE 生效（rowcount>0）但回查不到行 → ValueError「not found after update」."""
        repo = SQLiteCharacterRepository(db_session)
        c = await repo.add(_char(project, "林尘"))

        real_execute = _patch_execute_returning_none_on_requery(db_session)
        try:
            with pytest.raises(ValueError, match="not found after update"):
                await repo.update(c.model_copy(update={"name": "改名"}))
        finally:
            db_session.execute = real_execute

    async def test_update_group_missing_after_update_raises(self, db_session, project):
        """update_group：UPDATE 生效但回查无行 → ValueError."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))

        real_execute = _patch_execute_returning_none_on_requery(db_session)
        try:
            with pytest.raises(ValueError, match="not found after update"):
                await repo.update_group(g.model_copy(update={"name": "改名"}))
        finally:
            db_session.execute = real_execute

    async def test_update_relation_missing_after_update_raises(self, db_session, project):
        """update_relation：UPDATE 生效但回查无行 → ValueError."""
        repo = SQLiteCharacterRepository(db_session)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        rel = await repo.add_relation(_relation(project, a, b, "师徒"))

        real_execute = _patch_execute_returning_none_on_requery(db_session)
        try:
            with pytest.raises(ValueError, match="not found after update"):
                await repo.update_relation(rel.model_copy(update={"description": "新说明"}))
        finally:
            db_session.execute = real_execute

    # ── hard_delete_group 不存在 → False（rowcount=0 分支） ──

    async def test_hard_delete_group_missing_returns_false(self, db_session, project):
        """hard_delete_group 不存在的分组 → False."""
        repo = SQLiteCharacterRepository(db_session)
        assert await repo.hard_delete_group(99999) is False

    # ── ORM __repr__ ──

    def test_orm_repr(self):
        """三个 ORM 模型的 __repr__ 输出（无需落库）."""
        c = CharacterORM(id=1, name="林尘")
        assert repr(c) == "<CharacterORM id=1 name='林尘'>"
        g = CharacterGroupORM(id=2, name="主角团")
        assert repr(g) == "<CharacterGroupORM id=2 name='主角团'>"
        r = CharacterRelationORM(id=3, from_character_id=1, to_character_id=2, relation_type="师徒")
        assert repr(r) == "<CharacterRelationORM id=3 1->2 '师徒'>"


# ══ P5 删除引用残留清理（#284 最后一批，spec §2.10/§5.18）══
#
# 设计背景：生产环境 SQLite PRAGMA foreign_keys=OFF（core/database.py 仅设
# WAL + busy_timeout）→ ORM ondelete 声明为休眠，删除父行后引用残留。本段用
# **OFF fixture**（镜像生产）契约「hard_delete 显式清理 character_relations」。
# 注意：本文件顶部 db_session fixture 显式 PRAGMA foreign_keys=ON（FK 级联
# 生效 → 掩盖残留，假绿）——P5 契约必须用独立 OFF fixture。


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


class TestP5HardDeleteCleansRelations:
    """P5：hard_delete 显式清理 character_relations（生产 foreign_keys=OFF 下
    不依赖 FK CASCADE）——RED 预期 FAIL（现实现无显式清理，关系行残留）。"""

    async def test_hard_delete_removes_incoming_and_outgoing_relations(
        self, db_session_off_fk, project
    ):
        """删除角色 → from/to 双向关系行全部物理删除（不依赖 FK）."""
        repo = SQLiteCharacterRepository(db_session_off_fk)
        a = await repo.add(_char(project, "林尘"))
        b = await repo.add(_char(project, "阿澈"))
        await repo.add_relation(_relation(project, a, b, "师徒"))
        await repo.add_relation(_relation(project, b, a, "宿敌"))

        assert await repo.hard_delete(a.id.int) is True

        count = await db_session_off_fk.execute(
            select(func.count()).select_from(CharacterRelationORM)
        )
        assert count.scalar_one() == 0
