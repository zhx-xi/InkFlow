"""F39 SQLiteSkillRepository coverage 缺口补测 — in-memory SQLite（规则 1j，非 RED）。

coverage report 2026-08-16 实测 skill_repo.py 行覆盖 64%，本文件补测全部
miss 行（规则 1j：代码已存在，测试直接通过；不写任何 src/ 实现）:

- L78-79: get 不存在 → None（scalar_one_or_none 的 None 分支）
- L92: list 空列表
- L111-112: update 的 (id, data) 双参形态（data.model_dump exclude_unset）
- L114: update target_id None → 返回 None
- L116-121: update 不存在 → None + 成功路径（exclude_unset 合并 + updated_at 刷新）
- L124, 129-131, 133: delete 不存在 → False + 成功 → True

另按镜像样板 test_agent_template_repo.py / test_provider_config_repo.py
形态补 CRUD 往返:
- add/get/get_by_name/list（content 原样存储 / source 两值 roundtrip）
- update 双形态：完整实体单参 + (id, data) 双参
- 转换函数 _orm_to_domain / _domain_to_orm
- name 唯一 → IntegrityError
- 时间戳断言只用 is not None / >=（SQLite 读回 naive，不做精确相等）

依据: specs/f39-multi-agent/spec.md §2.2；fixture 形态镜像
tests/unit/test_provider_config_repo.py（in-memory SQLite + PRAGMA
foreign_keys=ON + Base.metadata.create_all）。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.skill import Skill, SkillUpdate
from inkflow.infrastructure.database.models.skill import SkillORM
from inkflow.infrastructure.database.repositories.skill_repo import (
    SQLiteSkillRepository,
    _domain_to_orm,
    _orm_to_domain,
)

_SKILL_MD = """---
name: 示例技能
description: 测试用技能
---

# 正文

- 要点一
- 要点二
"""


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像 F13 仓储测试 fixture）."""
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


def _skill(name: str, **kw) -> Skill:
    """构造待持久化的 Skill 领域对象.

    id/created_at/updated_at 默认 None：id 由 DB 自增分配，时间戳由 ORM
    default 填充（落库读回后为 naive datetime，断言只用 is not None）。
    可通过 kw 覆盖 description/content/source 等字段.
    """
    return Skill(name=name, **kw)


@pytest.mark.integration
class TestSkillRepository:
    """SQLiteSkillRepository 集成测试 — coverage 缺口补测（规则 1j）."""

    # ── CRUD 往返 ──

    async def test_add_and_get_roundtrip(self, db_session):
        """add 落库并返回领域对象（id 分配、content 原样）；get 按 int 主键读回."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("写手", description="desc", content=_SKILL_MD))

        assert isinstance(saved.id, int)
        assert saved.id > 0
        assert saved.name == "写手"
        assert saved.description == "desc"
        assert saved.content == _SKILL_MD
        assert saved.source == "user_upload"  # 默认来源
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # 持久化验证：直接查表
        row = await db_session.execute(select(SkillORM).where(SkillORM.id == saved.id))
        assert row.scalar_one().content == _SKILL_MD

        got = await repo.get(saved.id)
        assert got is not None
        assert got.id == saved.id
        assert got.name == "写手"
        assert got.content == _SKILL_MD
        assert got.created_at == saved.created_at

    async def test_add_builtin_source_roundtrip(self, db_session):
        """source=\"builtin\" 落库读回（内置只读保护在服务层，本层仅存储）."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("内置技能", source="builtin"))

        got = await repo.get(saved.id)
        assert got is not None
        assert got.source == "builtin"

    async def test_get_returns_none_for_missing(self, db_session):
        """get 对不存在的 id 返回 None（L78-79 scalar_one_or_none None 分支）."""
        repo = SQLiteSkillRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_and_miss(self, db_session):
        """get_by_name 精确匹配命中；未命中返回 None."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("速记"))
        hit = await repo.get_by_name("速记")
        assert hit is not None
        assert hit.id == saved.id
        assert await repo.get_by_name("速记 ") is None  # 不做去空白
        assert await repo.get_by_name("ghost") is None

    async def test_name_unique_conflict(self, db_session):
        """name 唯一：插入第二个同名 → IntegrityError，回滚后可继续."""
        repo = SQLiteSkillRepository(db_session)
        await repo.add(_skill("重复名"))
        with pytest.raises(IntegrityError):
            await repo.add(_skill("重复名"))
        await db_session.rollback()  # 事务回滚，恢复可用

        items = await repo.list()
        assert len(items) == 1
        assert items[0].name == "重复名"

    # ── list ──

    async def test_list_empty(self, db_session):
        """空表 list 返回空列表（L92）."""
        repo = SQLiteSkillRepository(db_session)
        assert await repo.list() == []

    async def test_list_sorted_by_name(self, db_session):
        """list 按 name 升序."""
        repo = SQLiteSkillRepository(db_session)
        await repo.add(_skill("z-skill"))
        await repo.add(_skill("a-skill"))
        await repo.add(_skill("m-skill"))

        items = await repo.list()
        assert [s.name for s in items] == ["a-skill", "m-skill", "z-skill"]

    # ── update ──

    async def test_update_entity_single_arg(self, db_session):
        """update 完整实体单参（服务层契约形态）：exclude_unset 合并、
        updated_at 刷新、created_at 保留."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("旧名", description="old", content="旧内容"))
        updated = await repo.update(
            saved.model_copy(update={"name": "新名", "description": "new", "content": "新内容"})
        )

        assert updated.id == saved.id
        assert updated.name == "新名"
        assert updated.description == "new"
        assert updated.content == "新内容"
        assert updated.created_at == saved.created_at
        assert updated.updated_at >= saved.updated_at

        # 持久化验证
        got = await repo.get(saved.id)
        assert got is not None
        assert got.name == "新名"
        assert got.content == "新内容"

    async def test_update_id_and_data_two_args(self, db_session):
        """update (id, data) 双参形态（Protocol 契约，L111-112）:
        data.model_dump(exclude_unset=True) 只更新显式字段."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("a", description="old", content="旧内容"))
        updated = await repo.update(saved.id, SkillUpdate(description="新描述", content="新内容"))

        assert updated is not None
        assert updated.id == saved.id
        assert updated.description == "新描述"
        assert updated.content == "新内容"
        assert updated.name == "a"  # 未在 data 中 → 不修改
        assert updated.created_at == saved.created_at
        assert updated.updated_at >= saved.updated_at

    async def test_update_explicit_none_not_modified(self, db_session):
        """双参形态显式 None = 不修改（L119 跳过 setattr）."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("a", content="旧内容"))
        updated = await repo.update(saved.id, SkillUpdate(content=None))

        assert updated is not None
        assert updated.content == "旧内容"
        assert updated.updated_at >= saved.updated_at

    async def test_update_without_data_refreshes_timestamp(self, db_session):
        """双参形态 data=None → changes={}，仅刷新 updated_at（L112 分支）."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("a", description="old"))
        updated = await repo.update(saved.id)

        assert updated is not None
        assert updated.description == "old"
        assert updated.updated_at >= saved.updated_at

    async def test_update_entity_without_id_returns_none(self, db_session):
        """单参实体 id=None（未落库）→ 返回 None（L114 target_id None 分支）."""
        repo = SQLiteSkillRepository(db_session)
        assert await repo.update(Skill(name="无主键")) is None

    async def test_update_missing_returns_none(self, db_session):
        """update 不存在的 id → None：双参形态 + 单参形态（L116-117 分支）."""
        repo = SQLiteSkillRepository(db_session)
        assert await repo.update(99999, SkillUpdate(description="x")) is None
        assert await repo.update(Skill(id=99999, name="ghost")) is None

    # ── delete ──

    async def test_delete_existing_and_missing(self, db_session):
        """delete 命中返回 True 且 get 不可见；不存在返回 False（L124/129-133）."""
        repo = SQLiteSkillRepository(db_session)
        saved = await repo.add(_skill("临时"))

        assert await repo.delete(saved.id) is True
        assert await repo.get(saved.id) is None
        assert await repo.delete(saved.id) is False  # 已删除 → 不存在
        assert await repo.delete(99999) is False


class TestSkillConversionFunctions:
    """_orm_to_domain / _domain_to_orm 纯函数转换（无 DB，L37-57）."""

    def test_orm_to_domain(self):
        """ORM 行 → 领域实体：content/source 原样透传."""
        orm = SkillORM(
            id=9,
            name="n",
            description="d",
            content="c",
            source="builtin",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 2),
        )
        domain = _orm_to_domain(orm)

        assert domain.id == 9
        assert domain.name == "n"
        assert domain.description == "d"
        assert domain.content == "c"
        assert domain.source == "builtin"
        assert domain.created_at == datetime(2026, 1, 1)
        assert domain.updated_at == datetime(2026, 1, 2)

    def test_domain_to_orm(self):
        """领域实体 → ORM 行：id/时间戳不携带（DB 自增 + ORM default 填充）."""
        domain = Skill(id=9, name="n", description="d", content="c", source="builtin")
        orm = _domain_to_orm(domain)

        assert orm.id is None
        assert orm.name == "n"
        assert orm.description == "d"
        assert orm.content == "c"
        assert orm.source == "builtin"
        assert orm.created_at is None
        assert orm.updated_at is None
