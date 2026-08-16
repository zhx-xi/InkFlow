"""#258 F39 后端核心 — 内置 seed 幂等测试契约（TDD RED 阶段，spec §13 M4）。

覆盖 `api/app.py` lifespan 内调用的 `seed_builtin_agents()` /
`seed_builtin_skills()` 出厂 seed（spec §5.3 镜像 seed_builtin_providers
幂等模式：同名跳过、重复启动不重复插入）：

- seed_builtin_agents()：首次返回 6（架构师/写手/审校员/修订师/世界观顾问/
  润色师，builtin=True），重复调用返回 0
- seed_builtin_skills()：首次返回 6（架构方法论/写作方法论/审校方法论/
  修订方法论/世界观方法论/润色方法论，source="builtin"），重复调用返回 0
- 白名单映射逐字 = spec §5.3 出厂表（6 Agent 的 tool_ids/skill_ids）
- 内置只读：PATCH/DELETE 内置 Agent/Skill → 409（§5.6）

权威来源：specs/f39-multi-agent/spec.md §5.3（出厂配置表 + 幂等语义）、§5.6
（内置只读 409）、§13 M4/M5（验收）。测试方式镜像 backend/tests/unit/
test_provider_config_repo.py（#106：in-memory SQLite + PRAGMA foreign_keys=ON
+ seed 返回插入数 + 重复 seed 返回 0），API 只读用例镜像 tests/api/conftest.py
（override_get_db 同库）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【seed 函数形态——契约锁定语义，实现位置由 GREEN 决定】本文件以模块级
   async 函数形态调用：`await seed_builtin_agents(session)` /
   `await seed_builtin_skills(session)`（session 为 AsyncSession，显式注入
   保证测试落在 in-memory 库）。若 GREEN 设计为 service/repo 方法而非独立
   模块函数，则相应工厂/构造必须暴露同名 async 方法（如
   `get_agent_service(session).seed_builtin_agents()`）——契约锁定 seed
   语义（幂等/映射/只读），实现位置由 GREEN 决定。当前约定 import 路径：
   `inkflow.domain.services.agent_entity_service` / `inkflow.domain.services.
   skill_service`（F39 新模块；agent_service 为既有 F4 编排服务文件，F39
   实体 CRUD + seed 全部放 agent_entity_service.py，父侧裁定 2026-08-16）。
   【session 注入——硬性契约】seed 必须接受外部 session（禁止内部取全局
   async_session_factory），否则测试无法控制落库目标。

2. 【幂等语义（镜像 provider seed）】按 name 判重（get_by_name 命中跳过）：
   首次调用返回本次实际插入条数（6/6）；重复调用返回 0；表内行数恒为
   6/6（重复启动不重复插入，§5.3「同名跳过」）。

3. 【内置 Agent 出厂配置（spec §5.3 出厂表，逐字）】6 个，builtin=True：

   | Agent     | tool_ids                                      | 出厂 skill  |
   |-----------|-----------------------------------------------|-------------|
   | 架构师     | search_characters, check_foreshadowing,       | 架构方法论  |
   |           |   get_prior_summary                           |             |
   | 写手       | search_characters, check_foreshadowing,       | 写作方法论  |
   |           |   get_prior_summary, save_draft               |             |
   | 审校员     | audit_chapter, count_words, search_characters | 审校方法论  |
   | 修订师     | get_prior_summary, count_words, save_draft    | 修订方法论  |
   | 世界观顾问 | search_characters, check_foreshadowing        | 世界观方法论 |
   | 润色师     | count_words, get_prior_summary                | 润色方法论  |

   tool_ids 为集合契约（不锁顺序）；skill_ids 存 `str(skill_id)`（spec §2.1
   id 字符串化惯例），与 seed 的 6 个内置 Skill 主键一一对应。

4. 【内置 Skill 出厂配置（spec §5.3）】6 个，source="builtin"：架构方法论 /
   写作方法论 / 审校方法论 / 修订方法论 / 世界观方法论 / 润色方法论。content
   为含 frontmatter + 正文的完整 SKILL.md（非空即契约；具体文案实现期编写，
   非契约字段）。出厂 prompt 与 skill 正文为 seed 内容（§5.3「契约只定
   6 Agent + 6 Skill + 上表白名单映射」）。

5. 【内置只读（§5.6）】PATCH/DELETE builtin=True 的 Agent 或
   source="builtin" 的 Skill → 409（AgentBuiltinError / SkillBuiltinError），
   记录原样保留。经 API 验证（override_get_db 与 seed 同库）。

6. 【ORM 契约（查询辅助）】`AgentORM`（agents 表；tool_ids/skill_ids 存
   LenientJSON，spec §8.1）与 `SkillORM`（skills 表；name 唯一）——GREEN
   加入 `infrastructure/database/models/`（AgentORM 可并入既有 agent.py
   同文件，该文件当前仅 AgentExecutionORM），且必须在
   `infrastructure/database/models/__init__.py` 导出（注册进 Base.metadata，
   本文件 db_session fixture 的 create_all 才会建表）。

7. 【db_session fixture 本地定义】镜像 test_provider_config_repo.py：
   in-memory SQLite + `PRAGMA foreign_keys=ON`（#327 生产同口径）+
   Base.metadata.create_all，函数级全新库。本文件内定义同名 fixture 覆盖
   tests/conftest.py 的 db_session（顶层 tests/ 惯例的 test_engine 无
   PRAGMA，seed 测试需要镜像生产的外键开关）。client / override_get_db
   本地定义（镜像 tests/api/conftest.py：get_db → 本文件 db_session 同库）。

8. 【ORM 查询导入形态】`AgentORM`（agents 表；tool_ids/skill_ids 存
   LenientJSON，spec §8.1）与 `SkillORM`（skills 表；name 唯一）经
   `from inkflow.infrastructure.database.models import AgentORM[, SkillORM]`
   惰性导入（models 包存在、当前未导出二者 → RED 期 ImportError：
   cannot import name；GREEN 必须在 `infrastructure/database/models/
   __init__.py` 导出（spec §8.2 MODIFY「import 注册 AgentORM/SkillORM
   （触发 Base.metadata）」），AgentORM 可并入既有 agent.py 同文件（该文件
   当前仅 AgentExecutionORM）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：seed 函数未实现 → 模块级 try/except ImportError stub 生效
（agent_entity_service 缺 seed_builtin_agents → cannot import name；skill_service
模块不存在 → ModuleNotFoundError）→ 本文件【收集成功】+ 全部用例 FAILED
（ImportError: seed_builtin_agents/seed_builtin_skills 未实现）——非收集期
错误形态，便于逐用例核对。GREEN 实现后全绿。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.app import app
from inkflow.core.database import Base

# ── seed 函数惰性 import（RED 阶段 stub，GREEN 后真实实现命中）──

try:
    from inkflow.domain.services.agent_entity_service import seed_builtin_agents
except ImportError:  # pragma: no cover - RED 阶段 stub

    async def seed_builtin_agents(session, *args, **kwargs):  # type: ignore[no-redef]  # RED stub 与真实 import 同名重定义（GREEN 后真实函数覆盖）
        raise ImportError("seed_builtin_agents 未实现（F39 RED 阶段预期）")


try:
    from inkflow.domain.services.skill_service import seed_builtin_skills
except ImportError:  # pragma: no cover - RED 阶段 stub

    async def seed_builtin_skills(session, *args, **kwargs):  # type: ignore[no-redef]  # RED stub 与真实 import 同名重定义（GREEN 后真实函数覆盖）
        raise ImportError("seed_builtin_skills 未实现（F39 RED 阶段预期）")


# ── 契约常量 ──

AGENT_ENDPOINT = "/api/v1/agents"
"""Agent 端点前缀（内置只读 API 用例用，spec §3.1）。"""

SKILL_ENDPOINT = "/api/v1/skills"
"""Skill 端点前缀（内置只读 API 用例用，spec §3.1）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 中间件直通。"""

BUILTIN_AGENT_NAMES = ["架构师", "写手", "审校员", "修订师", "世界观顾问", "润色师"]
"""内置 6 Agent 出厂名称（spec §5.3 出厂表）。"""

BUILTIN_SKILL_NAMES = [
    "架构方法论",
    "写作方法论",
    "审校方法论",
    "修订方法论",
    "世界观方法论",
    "润色方法论",
]
"""内置 6 Skill 出厂名称（spec §5.3 出厂表）。"""

WHITELIST_MAP = {
    "架构师": (
        {"search_characters", "check_foreshadowing", "get_prior_summary"},
        "架构方法论",
    ),
    "写手": (
        {
            "search_characters",
            "check_foreshadowing",
            "get_prior_summary",
            "save_draft",
        },
        "写作方法论",
    ),
    "审校员": ({"audit_chapter", "count_words", "search_characters"}, "审校方法论"),
    "修订师": ({"get_prior_summary", "count_words", "save_draft"}, "修订方法论"),
    "世界观顾问": (
        {"search_characters", "check_foreshadowing"},
        "世界观方法论",
    ),
    "润色师": ({"count_words", "get_prior_summary"}, "润色方法论"),
}
"""spec §5.3 出厂表白名单映射：Agent 名 → (tool_ids 集合, 出厂 skill 名)。

与设计假设 #3 逐字一致（写手 tool_ids 含 save_draft；架构师含
search_characters/check_foreshadowing/get_prior_summary 等）。
"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像
    test_provider_config_repo.py：create_all + PRAGMA foreign_keys=ON，
    #327 生产同口径；覆盖 tests/conftest.py 的 db_session，设计假设 #7）。"""
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
def override_get_db(db_session):
    """将 FastAPI 的 get_db 替换为本文件 db_session（镜像 tests/api/conftest.py），
    API 只读用例与 seed 共享同一 in-memory 库。"""
    from inkflow.api.deps import get_db

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式：delenv INKFLOW_SERVER_TOKEN）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── seed_builtin_agents（spec §5.3 内置 Agent 出厂 seed）──


@pytest.mark.asyncio
@pytest.mark.integration
class TestSeedAgents:
    """内置 Agent seed 契约（设计假设 #1/#2/#3）。"""

    async def test_seed_agents_first_call_returns_6(self, db_session):
        """首次调用返回 6；6 行落库（builtin=True，名称 = 出厂表）（#2/#3）。"""
        n = await seed_builtin_agents(db_session)
        assert n == 6

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        assert len(rows) == 6
        assert {r.name for r in rows} == set(BUILTIN_AGENT_NAMES)
        assert all(r.builtin is True for r in rows)

    async def test_seed_agents_idempotent(self, db_session):
        """重复调用返回 0；表内行数恒为 6（同名跳过，不重复插入）（#2）。"""
        assert await seed_builtin_agents(db_session) == 6
        assert await seed_builtin_agents(db_session) == 0

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        assert len(rows) == 6

    async def test_seed_agents_whitelist_mapping(self, db_session):
        """白名单映射 = spec §5.3 出厂表逐字：tool_ids 集合 + skill_ids 指向
        对应出厂 skill（skill 主键字符串化）（#3）。"""
        assert await seed_builtin_agents(db_session) == 6
        assert await seed_builtin_skills(db_session) == 6

        from inkflow.infrastructure.database.models import AgentORM, SkillORM

        skill_rows = (await db_session.execute(select(SkillORM))).scalars().all()
        skill_id_by_name = {s.name: str(s.id) for s in skill_rows}
        assert set(skill_id_by_name) == set(BUILTIN_SKILL_NAMES)

        agent_rows = (await db_session.execute(select(AgentORM))).scalars().all()
        by_name = {a.name: a for a in agent_rows}
        assert set(by_name) == set(BUILTIN_AGENT_NAMES)
        for name, (tool_ids, skill_name) in WHITELIST_MAP.items():
            agent = by_name[name]
            assert (
                set(agent.tool_ids) == tool_ids
            ), f"{name} tool_ids 不符: {agent.tool_ids}"
            assert agent.skill_ids == [
                skill_id_by_name[skill_name]
            ], f"{name} skill_ids 不符: {agent.skill_ids}"


# ── seed_builtin_skills（spec §5.3 内置 Skill 出厂 seed）──


@pytest.mark.asyncio
@pytest.mark.integration
class TestSeedSkills:
    """内置 Skill seed 契约（设计假设 #1/#2/#4）。"""

    async def test_seed_skills_first_call_returns_6(self, db_session):
        """首次调用返回 6；6 行落库（source="builtin"，名称 = 出厂表）（#2/#4）。"""
        n = await seed_builtin_skills(db_session)
        assert n == 6

        from inkflow.infrastructure.database.models import SkillORM

        rows = (await db_session.execute(select(SkillORM))).scalars().all()
        assert len(rows) == 6
        assert {r.name for r in rows} == set(BUILTIN_SKILL_NAMES)
        assert all(r.source == "builtin" for r in rows)
        assert all(r.content for r in rows)  # 完整 SKILL.md 非空（#4）

    async def test_seed_skills_idempotent(self, db_session):
        """重复调用返回 0；表内行数恒为 6（#2）。"""
        assert await seed_builtin_skills(db_session) == 6
        assert await seed_builtin_skills(db_session) == 0

        from inkflow.infrastructure.database.models import SkillORM

        rows = (await db_session.execute(select(SkillORM))).scalars().all()
        assert len(rows) == 6


# ── 内置只读（spec §5.6：PATCH/DELETE 内置 → 409）──


@pytest.mark.asyncio
@pytest.mark.integration
class TestBuiltinReadonly:
    """内置实体只读保护契约（设计假设 #5）。"""

    async def test_patch_builtin_agent_409(self, client, db_session, override_get_db):
        """PATCH builtin=True 的 Agent → 409（AgentBuiltinError）；记录原样保留。"""
        assert await seed_builtin_agents(db_session) == 6

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        agent_id = rows[0].id
        resp = await client.patch(
            f"{AGENT_ENDPOINT}/{agent_id}", json={"description": "篡改"}
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]

        resp2 = await client.get(f"{AGENT_ENDPOINT}/{agent_id}")
        assert resp2.status_code == 200
        assert resp2.json()["builtin"] is True

    async def test_delete_builtin_agent_409(self, client, db_session, override_get_db):
        """DELETE builtin=True 的 Agent → 409；记录仍存在。"""
        assert await seed_builtin_agents(db_session) == 6

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        agent_id = rows[0].id
        resp = await client.delete(f"{AGENT_ENDPOINT}/{agent_id}")
        assert resp.status_code == 409
        assert resp.json()["detail"]

        resp2 = await client.get(f"{AGENT_ENDPOINT}/{agent_id}")
        assert resp2.status_code == 200

    async def test_patch_builtin_skill_409(self, client, db_session, override_get_db):
        """PATCH source="builtin" 的 Skill → 409（SkillBuiltinError）；记录原样保留。"""
        assert await seed_builtin_skills(db_session) == 6

        from inkflow.infrastructure.database.models import SkillORM

        rows = (await db_session.execute(select(SkillORM))).scalars().all()
        skill_id = rows[0].id
        resp = await client.patch(
            f"{SKILL_ENDPOINT}/{skill_id}", json={"description": "篡改"}
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]

        resp2 = await client.get(f"{SKILL_ENDPOINT}/{skill_id}")
        assert resp2.status_code == 200
        assert resp2.json()["source"] == "builtin"

    async def test_delete_builtin_skill_409(self, client, db_session, override_get_db):
        """DELETE source="builtin" 的 Skill → 409；记录仍存在。"""
        assert await seed_builtin_skills(db_session) == 6

        from inkflow.infrastructure.database.models import SkillORM

        rows = (await db_session.execute(select(SkillORM))).scalars().all()
        skill_id = rows[0].id
        resp = await client.delete(f"{SKILL_ENDPOINT}/{skill_id}")
        assert resp.status_code == 409
        assert resp.json()["detail"]

        resp2 = await client.get(f"{SKILL_ENDPOINT}/{skill_id}")
        assert resp2.status_code == 200
