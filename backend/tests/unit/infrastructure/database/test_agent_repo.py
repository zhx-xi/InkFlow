"""F39 SQLiteAgentRepository coverage 缺口补测 — in-memory SQLite（规则 1j，非 RED）。

coverage report 2026-08-16 实测 agent_repo.py 行覆盖 72%，本文件补测全部
miss 行（规则 1j：代码已存在，测试直接通过；不写任何 src/ 实现）:

- L91-92: get 不存在 → None（scalar_one_or_none 的 None 分支）
- L105: list 空列表
- L124-125: update 的 (id, data) 双参形态（data.model_dump exclude_unset）
- L127: update target_id None → 返回 None
- L130, 137: update 不存在 → None + 成功路径（exclude_unset 合并 + updated_at 刷新）
- L143, 146: delete 不存在 → False + 成功 → True
- list_agents_by_skill 反查（命中/未命中/精确 str 匹配/name 升序）

另按镜像样板 test_agent_template_repo.py 形态补 CRUD 往返:
- add/get/get_by_name/list（tool_ids/skill_ids JSON 列 roundtrip）
- update 双形态：完整实体单参 + (id, data) 双参
- 转换函数 _orm_to_domain / _domain_to_orm
- name 唯一 → IntegrityError
- 时间戳断言只用 is not None / >=（SQLite 读回 naive，不做精确相等）

依据: specs/f39-multi-agent/spec.md §2.1；fixture 形态镜像
tests/unit/test_agent_template_repo.py（in-memory SQLite + PRAGMA
foreign_keys=ON + Base.metadata.create_all）。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.agent import Agent, AgentUpdate
from inkflow.infrastructure.database.models.agent_entity import AgentORM
from inkflow.infrastructure.database.repositories.agent_repo import (
    SQLiteAgentRepository,
    _domain_to_orm,
    _orm_to_domain,
)


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


def _agent(name: str, **kw) -> Agent:
    """构造待持久化的 Agent 领域对象.

    id/created_at/updated_at 默认 None：id 由 DB 自增分配，时间戳由 ORM
    default 填充（落库读回后为 naive datetime，断言只用 is not None）。
    可通过 kw 覆盖 description/icon/system_prompt/tool_ids/skill_ids 等字段.
    """
    return Agent(name=name, **kw)


@pytest.mark.integration
class TestAgentRepository:
    """SQLiteAgentRepository 集成测试 — coverage 缺口补测（规则 1j）."""

    # ── CRUD 往返 ──

    async def test_add_and_get_roundtrip(self, db_session):
        """add 落库并返回领域对象（id 分配、默认字段）；get 按 int 主键读回."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(
            _agent(
                "写手",
                description="desc",
                icon="✍️",
                system_prompt="你是一个写手",
                tool_ids=["web_search", "write"],
                skill_ids=["1", "2"],
                model_override="openai/gpt-4o",
                temperature_override=0.8,
                builtin=True,
            )
        )

        assert isinstance(saved.id, int)
        assert saved.id > 0
        assert saved.name == "写手"
        assert saved.description == "desc"
        assert saved.icon == "✍️"
        assert saved.system_prompt == "你是一个写手"
        assert saved.tool_ids == ["web_search", "write"]
        assert saved.skill_ids == ["1", "2"]
        assert saved.model_override == "openai/gpt-4o"
        assert saved.temperature_override == 0.8
        assert saved.builtin is True
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # 持久化验证：直接查表
        row = await db_session.execute(select(AgentORM).where(AgentORM.id == saved.id))
        assert row.scalar_one().name == "写手"

        got = await repo.get(saved.id)
        assert got is not None
        assert got.id == saved.id
        assert got.name == "写手"
        assert got.tool_ids == ["web_search", "write"]
        assert got.skill_ids == ["1", "2"]
        assert got.created_at == saved.created_at

    async def test_get_returns_none_for_missing(self, db_session):
        """get 对不存在的 id 返回 None（L91-92 scalar_one_or_none None 分支）."""
        repo = SQLiteAgentRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_and_miss(self, db_session):
        """get_by_name 精确匹配命中；未命中返回 None."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(_agent("助手"))
        hit = await repo.get_by_name("助手")
        assert hit is not None
        assert hit.id == saved.id
        assert await repo.get_by_name("助手 ") is None  # 不做去空白
        assert await repo.get_by_name("ghost") is None

    async def test_name_unique_conflict(self, db_session):
        """name 唯一：插入第二个同名 → IntegrityError，回滚后可继续."""
        repo = SQLiteAgentRepository(db_session)
        await repo.add(_agent("重复名"))
        with pytest.raises(IntegrityError):
            await repo.add(_agent("重复名"))
        await db_session.rollback()  # 事务回滚，恢复可用

        items = await repo.list()
        assert len(items) == 1
        assert items[0].name == "重复名"

    # ── list ──

    async def test_list_empty(self, db_session):
        """空表 list 返回空列表（L105）."""
        repo = SQLiteAgentRepository(db_session)
        assert await repo.list() == []

    async def test_list_sorted_by_name(self, db_session):
        """list 按 name 升序."""
        repo = SQLiteAgentRepository(db_session)
        await repo.add(_agent("z-agent"))
        await repo.add(_agent("a-agent"))
        await repo.add(_agent("m-agent"))

        items = await repo.list()
        assert [a.name for a in items] == ["a-agent", "m-agent", "z-agent"]

    # ── tool_ids / skill_ids JSON 存取 ──

    async def test_tool_skill_ids_json_roundtrip(self, db_session):
        """tool_ids/skill_ids 经 JSON 列落库读回（L48-49 转换透传 list）."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(_agent("t", tool_ids=["web_search", "code"], skill_ids=["1", "3"]))

        got = await repo.get(saved.id)
        assert got is not None
        assert got.tool_ids == ["web_search", "code"]
        assert got.skill_ids == ["1", "3"]

        # DB 行存 JSON 列表（非字符串）
        row = await db_session.execute(select(AgentORM).where(AgentORM.id == saved.id))
        orm_row = row.scalar_one()
        assert orm_row.tool_ids == ["web_search", "code"]
        assert orm_row.skill_ids == ["1", "3"]

    # ── update ──

    async def test_update_entity_single_arg(self, db_session):
        """update 完整实体单参（服务层契约形态）：exclude_unset 合并、
        updated_at 刷新、created_at 保留."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(_agent("旧名", description="old"))
        updated = await repo.update(
            saved.model_copy(
                update={
                    "name": "新名",
                    "description": "new",
                    "icon": "🤖",
                    "tool_ids": ["web_search"],
                    "skill_ids": ["5"],
                    "temperature_override": 1.1,
                }
            )
        )

        assert updated.id == saved.id
        assert updated.name == "新名"
        assert updated.description == "new"
        assert updated.icon == "🤖"
        assert updated.tool_ids == ["web_search"]
        assert updated.skill_ids == ["5"]
        assert updated.temperature_override == 1.1
        assert updated.created_at == saved.created_at
        assert updated.updated_at >= saved.updated_at

        # 持久化验证
        got = await repo.get(saved.id)
        assert got is not None
        assert got.name == "新名"
        assert got.skill_ids == ["5"]

    async def test_update_id_and_data_two_args(self, db_session):
        """update (id, data) 双参形态（Protocol 契约，L124-125）:
        data.model_dump(exclude_unset=True) 只更新显式字段."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(_agent("a", description="old", icon=""))
        updated = await repo.update(saved.id, AgentUpdate(description="新描述", icon="🤖"))

        assert updated is not None
        assert updated.id == saved.id
        assert updated.description == "新描述"
        assert updated.icon == "🤖"
        assert updated.name == "a"  # 未在 data 中 → 不修改
        assert updated.created_at == saved.created_at
        assert updated.updated_at >= saved.updated_at

    async def test_update_explicit_none_not_modified(self, db_session):
        """双参形态显式 None = 不修改（L132 跳过 setattr）."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(_agent("a", description="old"))
        updated = await repo.update(saved.id, AgentUpdate(description=None))

        assert updated is not None
        assert updated.description == "old"
        assert updated.updated_at >= saved.updated_at

    async def test_update_without_data_refreshes_timestamp(self, db_session):
        """双参形态 data=None → changes={}，仅刷新 updated_at（L125 分支）."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(_agent("a", description="old"))
        updated = await repo.update(saved.id)

        assert updated is not None
        assert updated.description == "old"
        assert updated.updated_at >= saved.updated_at

    async def test_update_entity_without_id_returns_none(self, db_session):
        """单参实体 id=None（未落库）→ 返回 None（L127 target_id None 分支）."""
        repo = SQLiteAgentRepository(db_session)
        assert await repo.update(Agent(name="无主键")) is None

    async def test_update_missing_returns_none(self, db_session):
        """update 不存在的 id → None：双参形态 + 单参形态（L130 分支）."""
        repo = SQLiteAgentRepository(db_session)
        assert await repo.update(99999, AgentUpdate(description="x")) is None
        assert await repo.update(Agent(id=99999, name="ghost")) is None

    # ── delete ──

    async def test_delete_existing_and_missing(self, db_session):
        """delete 命中返回 True 且 get 不可见；不存在返回 False（L143/146）."""
        repo = SQLiteAgentRepository(db_session)
        saved = await repo.add(_agent("临时"))

        assert await repo.delete(saved.id) is True
        assert await repo.get(saved.id) is None
        assert await repo.delete(saved.id) is False  # 已删除 → 不存在
        assert await repo.delete(99999) is False

    # ── list_agents_by_skill 反查 ──

    async def test_list_agents_by_skill_hit_and_sort(self, db_session):
        """Skill_ids exact directory-name match (#522 fs source)."""
        repo = SQLiteAgentRepository(db_session)
        await repo.add(_agent("c-调试", skill_ids=["web-research", "revision-methodology"]))
        await repo.add(_agent("a-写作", skill_ids=["writing-methodology"]))
        await repo.add(_agent("b-综合", skill_ids=["writing-methodology", "web-research"]))

        refs = await repo.list_agents_by_skill("web-research")
        assert [a.name for a in refs] == ["b-综合", "c-调试"]
        assert all(isinstance(a, Agent) for a in refs)

    async def test_list_agents_by_skill_exact_match_and_miss(self, db_session):
        """Exact match semantics: substring/partial names miss (#522)."""
        repo = SQLiteAgentRepository(db_session)
        await repo.add(_agent("长号", skill_ids=["writing-methodology"]))
        await repo.add(_agent("空", skill_ids=[]))

        assert await repo.list_agents_by_skill("audit-methodology") == []
        assert [a.name for a in await repo.list_agents_by_skill("writing-methodology")] == ["长号"]

    async def test_list_agents_by_skill_empty_table(self, db_session):
        """空表 → 空列表."""
        repo = SQLiteAgentRepository(db_session)
        assert await repo.list_agents_by_skill(1) == []


class TestAgentConversionFunctions:
    """_orm_to_domain / _domain_to_orm 纯函数转换（无 DB，L40-70）."""

    def test_orm_to_domain(self):
        """ORM 行 → 领域实体：tool_ids/skill_ids 透传 list，时间戳原样."""
        orm = AgentORM(
            id=7,
            name="n",
            description="d",
            icon="i",
            system_prompt="sp",
            tool_ids=["web_search", "code"],
            skill_ids=["1", "2"],
            model_override="openai/gpt-4o",
            temperature_override=0.7,
            builtin=True,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 2),
        )
        domain = _orm_to_domain(orm)

        assert domain.id == 7
        assert domain.name == "n"
        assert domain.tool_ids == ["web_search", "code"]
        assert domain.skill_ids == ["1", "2"]
        assert domain.model_override == "openai/gpt-4o"
        assert domain.temperature_override == 0.7
        assert domain.builtin is True
        assert domain.created_at == datetime(2026, 1, 1)

    def test_domain_to_orm(self):
        """领域实体 → ORM 行：id/时间戳不携带（DB 自增 + ORM default 填充）."""
        domain = Agent(
            id=7,
            name="n",
            description="d",
            tool_ids=["web_search"],
            skill_ids=["9"],
            builtin=True,
        )
        orm = _domain_to_orm(domain)

        assert orm.id is None
        assert orm.name == "n"
        assert orm.tool_ids == ["web_search"]
        assert orm.skill_ids == ["9"]
        assert orm.builtin is True
        assert orm.created_at is None
        assert orm.updated_at is None
