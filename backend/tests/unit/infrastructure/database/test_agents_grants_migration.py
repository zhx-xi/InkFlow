"""#954 F58 grants 数据面 — agents.grants 列迁移契约测试（RED-3，新建）.

被测模块：``inkflow.core.database.ensure_agents_grants_column`` +
``inkflow.api.app.lifespan`` + ``inkflow.infrastructure.database.models.agent_entity.AgentORM``。
契约节引用：specs/f58-agent-tool-scope/spec.md §5（迁移契约，存量数据资产保护）
+ .hermes/plans/contract-954.md §6（持久化与迁移）/§9 RED-3。

背景：F58 grants 授权模型（domain × CRUD matrix）替换 tool_ids 白名单。spec §5.1：
``agents.tool_ids`` 列保留（不删），新增 ``grants`` JSON 列（默认 []/NULL），轻量幂等迁移
（create_all + 幂等 ALTER 先例——镜像源 ``core/database.py:188-199 ensure_agent_role_key_column``）。
既有库（create_all 不重建表）无 grants 列 → 物化/回显读取 grants 即缺列。本测试钉住迁移函数
``ensure_agents_grants_column``（签名 SQLAlchemy Connection——同步 create_engine + engine.connect()
传参，与 run_sync 路径一致）：

- 旧库（agents 表存在但无 grants 列）→ 调用后列存在（ALTER TABLE ADD COLUMN）且存量行
  tool_ids 数据完好（SELECT 断言——存量数据资产保护 spec §5）。
- 新库（create_all 已含列）→ 幂等 no-op，列集不变。
- 表不存在 → no-op 不抛错（全新环境等 create_all 建新表）。
- lifespan wiring：读 ``inkflow.api.app`` **真模块**源码（importlib 取真模块，勿
  ``from inkflow.api import app``——包属性遮蔽），断言 ``ensure_agents_grants_column`` 出现在
  lifespan 调用集中（防「注册了没接线」链级缺陷，sqlite-schema-migration 教训）。
- 真实 DB roundtrip（异步）：create_async_engine sqlite+aiosqlite tmp 文件 + create_all →
  INSERT AgentORM(grants=[...]) → 新 session 读回 grants 等值 + tool_ids 独立读回不受影响。

════════════════════════════════════════════════════════════════════
RED 预期形态（当前实现 ensure_agents_grants_column 不存在 / lifespan 未接线 /
AgentORM 无 grants 列 / Agent 实体无 grants 字段——本文件全部用例【R】）
════════════════════════════════════════════════════════════════════
- 迁移三式：``ensure_agents_grants_column`` 于函数体内 import（cannot import name
  ImportError）→ 各用例 FAILED。
- lifespan wiring：inspect.getsource(lifespan) 不含 'ensure_agents_grants_column' →
  AssertionError FAILED。
- 真实 DB roundtrip：AgentORM(grants=[...]) → TypeError（无 grants 参数）→ FAILED。

【G】= 零（本文件为新建，无既有用例）。
"""

from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 旧库 schema：照 agent_entity.py 现有 AgentORM 列集手写（无 grants 列，tool_ids TEXT）。
OLD_SCHEMA = """
CREATE TABLE agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    icon VARCHAR(50) NOT NULL,
    system_prompt TEXT NOT NULL,
    tool_ids TEXT NOT NULL,
    skill_ids TEXT NOT NULL,
    model_override VARCHAR(200),
    temperature_override FLOAT,
    builtin BOOLEAN NOT NULL,
    role_key VARCHAR(100),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""

# 新库 schema：已含 grants 列（GREEN create_all 形态）。
NEW_SCHEMA = OLD_SCHEMA.replace(
    "role_key VARCHAR(100)",
    "role_key VARCHAR(100), grants JSON",
)


def _columns(conn, table: str = "agents") -> set[str]:
    """PRAGMA 读列名集合."""
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def test_old_db_gets_grants_column(tmp_path):
    """旧库：agents 无 grants → 迁移后补列（幂等可重跑）+ 存量行 tool_ids 数据完好.

    存量数据资产保护（spec §5.1）：迁移只加列、不回填、不损坏既有 tool_ids 数据。
    """
    from inkflow.core.database import ensure_agents_grants_column  # 【R】

    db = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text(OLD_SCHEMA))
        conn.execute(
            text(
                "INSERT INTO agents (name, description, icon, system_prompt, tool_ids, "
                "skill_ids, builtin, role_key, created_at, updated_at) "
                "VALUES ('存量', '', '', '', '[\"search_characters\",\"get_prior_summary\"]', "
                "'[\"writing-methodology\"]', 1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    with engine.connect() as conn:
        assert "grants" not in _columns(conn)

        ensure_agents_grants_column(conn)
        assert "grants" in _columns(conn)

        # 存量行 tool_ids 数据完好（spec §5 存量数据资产保护）
        row = conn.execute(text("SELECT tool_ids FROM agents WHERE name='存量'")).fetchone()
        assert row is not None
        assert row[0] == '["search_characters","get_prior_summary"]'

        # 幂等重跑：不抛错、列不重复
        ensure_agents_grants_column(conn)
        assert "grants" in _columns(conn)
    engine.dispose()


def test_new_db_noop(tmp_path):
    """新库：create_all 已含 grants → no-op 不改变列集."""
    from inkflow.core.database import ensure_agents_grants_column  # 【R】

    db = tmp_path / "new.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text(NEW_SCHEMA))
    with engine.connect() as conn:
        before = _columns(conn)

        ensure_agents_grants_column(conn)
        assert _columns(conn) == before
    engine.dispose()


def test_missing_table_noop(tmp_path):
    """表不存在（全新环境）→ no-op 不抛错，等 create_all 建新表."""
    from inkflow.core.database import ensure_agents_grants_column  # 【R】

    db = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        ensure_agents_grants_column(conn)  # 不应抛错
    # 未建任何表（函数不应隐式建表）
    with engine.connect() as conn:
        tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        assert tables == []
    engine.dispose()


def test_lifespan_wires_ensure_agents_grants_column():
    """lifespan 启动链必须调用 ensure_agents_grants_column（防「注册了没接线」链级缺陷）.

    读 inkflow.api.app 真模块源码（importlib 取真模块，勿 from inkflow.api import app——
    包属性遮蔽），断言函数名出现在 lifespan 调用集中。
    """
    import importlib
    import inspect

    app_mod = importlib.import_module("inkflow.api.app")
    source = inspect.getsource(app_mod.lifespan)
    assert "ensure_agents_grants_column" in source  # 【R】：RED 期 lifespan 未接线 → AssertionError


async def test_real_db_roundtrip_grants(tmp_path):
    """真实 DB roundtrip（异步，GREEN 契约）：create_all → INSERT AgentORM(grants=[...]).

    新 session 读回 grants 等值 + tool_ids 独立读回不受影响（双列解耦，spec §5.1）。
    """
    from inkflow.core.database import Base
    from inkflow.infrastructure.database.models.agent_entity import (
        AgentORM,  # 【R】import 带 grants kwarg
    )

    db = tmp_path / "rt.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        orm = AgentORM(
            name="grants-rt",
            grants=[{"domain": "writing", "ops": ["read"]}],
            tool_ids=["count_words"],
        )
        session.add(orm)
        await session.commit()
        await session.refresh(orm)
        assert orm.grants == [{"domain": "writing", "ops": ["read"]}]
        assert orm.tool_ids == ["count_words"]

    # 新 session 读回（独立事务）
    async with session_factory() as session:
        stmt = select(AgentORM).where(AgentORM.name == "grants-rt")
        row = (await session.execute(stmt)).scalar_one()
        assert row.grants == [{"domain": "writing", "ops": ["read"]}]
        assert row.tool_ids == ["count_words"]
    await engine.dispose()
