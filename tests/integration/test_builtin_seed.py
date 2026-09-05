"""#522 Skill 存储架构重构（DB → 文件系统真源）— 内置 seed 契约测试（TDD RED 阶段）。

背景：skill 从 DB 表（int id、source 列）改为 `data_dir/skills/<name>/SKILL.md`
文件真源（#522）。skill_service 的 `seed_builtin_skills(session)` 拆分为两个
新函数：`ensure_builtin_skills(skills_root)`（同步纯文件操作）与
`migrate_skills_from_db(session, skills_root)`（async 存量迁移）；内置 Skill
出厂名从中文改为英文 slug（N2 合规）；`seed_builtin_agents` 保留但 skill_ids
语义从「DB 主键字符串化」改为「目录名列表」。本文件锁定上述新契约，当前旧
实现下确定性 FAIL（TDD RED）。

权威来源：父侧统一契约 2026-08-20（#522 定稿，跨文件漂移将导致 GREEN 失败）；
同一批契约见 tests/api/test_skills_api.py（路径标识 / 404「Skill 不存在」/
上传 422 等 API 面契约）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【函数形态——契约锁定语义，位置固定 skill_service】`ensure_builtin_skills(
   skills_root: Path) -> int` 为【同步】纯文件操作（无 session 参数）；
   `migrate_skills_from_db(session, skills_root: Path) -> int` 为 async，
   session 显式注入（禁止内部取全局 async_session_factory）。二者均位于
   `inkflow.domain.services.skill_service` 模块级。RED 期二者未实现 → 顶部
   try/except ImportError stub 生效（收集成功 + 用例 FAILED ImportError，
   非收集期 ERROR）；GREEN 后真实函数覆盖 stub。

2. 【内置 Skill 英文 slug——契约常量逐字】实现侧 `BUILTIN_SKILL_NAMES`
   （skill_service 模块级）必须与本文件逐字一致（顺序 = 出厂序）：
   architecture-methodology / writing-methodology / audit-methodology /
   revision-methodology / worldview-methodology / polishing-methodology，
   每个 slug 满足 N2 `^[a-z0-9]+(-[a-z0-9]+)*$`（RED 期旧实现为中文名 →
   断言 FAIL）。

3. 【ensure_builtin_skills 幂等语义】目录缺失/内置缺失 → 写出 6 个英文 slug
   内置 SKILL.md；返回本次写入数：首次 6、重复调用 0、删 1 个内置目录后回补
   1。每个 SKILL.md frontmatter name=目录名，可被 parse_skill_metadata 校验
   （N2 name=目录名规则，镜像 cli/skills_parser.py）。

4. 【migrate_skills_from_db 语义】旧 skills 表（可能存在于存量库）读
   source="user_upload" 行 → 写出 `skills_root/<name>/SKILL.md`（content
   原样）→ 清表（全部行删除/删表，含 builtin 行）；返回迁移条数；表不存在
   → 0（不抛错，且不得重建旧表）。【迁移函数不得依赖 SkillORM】——#522 去表
   后 SkillORM 删除，GREEN 实现必须用 raw SQL / sqlalchemy.text 读旧表；
   本文件模拟旧表同样用 raw SQL（CREATE TABLE skills + INSERT + SELECT
   COUNT），全程不 import SkillORM。

5. 【Agent.skill_ids 目录名语义】seed_builtin_agents 保留（async，session
   注入）：出厂 6 Agent 的 skill_ids = [对应英文 slug]（不再 DB 主键字符串
   化）；tool_ids 集合不变。WHITELIST_MAP = {Agent 名: (tool_ids 集合,
   slug)}；内置 Agent 出厂 name 保持中文（架构师/写手/审校员/修订师/世界观
   顾问/润色师）。

6. 【内置只读 API 409】目录名 ∈ BUILTIN slug → source="builtin"；PATCH/DELETE
   → 409 detail「内置 skill 只读」。经 API 验证：skills_root 用 tmp，ensure
   写出后打 API（设计假设 #8）。404 detail「Skill 不存在」由
   tests/api/test_skills_api.py 承载（本文件无 404 用例）。

7. 【db_session fixture 本地定义】in-memory SQLite + `PRAGMA foreign_keys=ON`
   （#327 生产同口径）+ Base.metadata.create_all，函数级全新库（覆盖
   tests/conftest.py 的 db_session——顶层 tests/ 惯例的 test_engine 无
   PRAGMA）。client / override_get_db 本地定义（镜像 tests/api/conftest.py：
   get_db → 本文件 db_session 同库）。

8. 【skills_root fixture】tmp_path/skills + monkeypatch
   `inkflow.core.config.config.data_dir` → tmp_path（镜像
   cli/commands/skills.py::_skills_root「动态读取，测试可 monkeypatch 实例
   属性」惯例；GREEN 经 config.data_dir/"skills" 解析真源根）。

════════════════════════════════════════════════════════════════════
RED 阶段预期（旧实现：DB 形态 + int id + 中文内置名，src 未改）
════════════════════════════════════════════════════════════════════
- TestEnsureBuiltinSkills 3 用例：ensure_builtin_skills 未实现 → stub
  ImportError → FAILED
- TestMigrateSkillsFromDb 3 用例：migrate_skills_from_db 未实现 → stub
  ImportError → FAILED
- TestWhitelistSync 2 用例：① 实现侧 BUILTIN_SKILL_NAMES 为中文名 → 断言
  AssertionError FAILED；② seed 后 skill_ids=["1"]..["6"]（DB 主键字符串化）
  ≠ [slug] → AssertionError FAILED
- TestBuiltinReadonly 2 用例：ensure stub ImportError → FAILED（旧 API 即使
  绕过 ensure 手工造目录，name 路径经旧 _parse_id 对非整数 → 404「Skill 不
  存在」≠ 409，同样 FAIL）
- TestSeedAgents 2 用例：两态不变契约锁（seed_builtin_agents 首写 6 / 幂等
  0，旧实现已满足）→ PASS
预期形态：10 failed / 2 passed（collected 12，无收集期 ERROR）。
"""

from __future__ import annotations

import importlib
import re
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.app import app
from inkflow.cli.skills_parser import parse_skill_metadata
from inkflow.core.database import Base

# ── #522 新函数惰性 import（RED 阶段 stub，GREEN 后真实实现命中）──

try:
    from inkflow.domain.services.skill_service import ensure_builtin_skills
except ImportError:  # pragma: no cover - RED 阶段 stub

    def ensure_builtin_skills(skills_root, *args, **kwargs):  # type: ignore[no-redef]  # RED stub 与真实 import 同名重定义（GREEN 后真实函数覆盖）
        raise ImportError("ensure_builtin_skills 未实现（#522 RED 阶段预期）")


try:
    from inkflow.domain.services.skill_service import migrate_skills_from_db
except ImportError:  # pragma: no cover - RED 阶段 stub

    async def migrate_skills_from_db(session, skills_root, *args, **kwargs):  # type: ignore[no-redef]  # RED stub 与真实 import 同名重定义（GREEN 后真实函数覆盖）
        raise ImportError("migrate_skills_from_db 未实现（#522 RED 阶段预期）")


try:
    from inkflow.domain.services.agent_entity_service import seed_builtin_agents
except ImportError:  # pragma: no cover - RED 阶段 stub

    async def seed_builtin_agents(session, *args, **kwargs):  # type: ignore[no-redef]  # RED stub 与真实 import 同名重定义（GREEN 后真实函数覆盖）
        raise ImportError("seed_builtin_agents 未实现（#522 RED 阶段预期）")


# ── 契约常量 ──

SKILL_ENDPOINT = "/api/v1/skills"
"""Skill 端点前缀（内置只读 API 用例用，#522 契约：路径标识 = 目录名）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 中间件直通。"""

DETAIL_BUILTIN = "内置 skill 只读"
"""内置 skill PATCH/DELETE 的 409 detail（父侧定稿文案，设计假设 #6）。"""

BUILTIN_AGENT_NAMES = ["架构师", "写手", "审校员", "修订师", "世界观顾问", "润色师"]
"""内置 6 Agent 出厂名称（保持中文，设计假设 #5）。"""

BUILTIN_SKILL_NAMES = [
    "architecture-methodology",
    "writing-methodology",
    "audit-methodology",
    "revision-methodology",
    "worldview-methodology",
    "polishing-methodology",
]
"""内置 6 Skill 英文 slug（设计假设 #2；顺序 = 出厂序）。"""

WHITELIST_MAP = {
    "架构师": (
        {"search_characters", "check_foreshadowing", "get_prior_summary"},
        "architecture-methodology",
    ),
    "写手": (
        {
            "search_characters",
            "check_foreshadowing",
            "get_prior_summary",
            "save_draft",
        },
        "writing-methodology",
    ),
    "审校员": (
        {"audit_chapter", "count_words", "search_characters"},
        "audit-methodology",
    ),
    "修订师": (
        {"get_prior_summary", "count_words", "save_draft"},
        "revision-methodology",
    ),
    "世界观顾问": (
        {"search_characters", "check_foreshadowing"},
        "worldview-methodology",
    ),
    "润色师": ({"count_words", "get_prior_summary"}, "polishing-methodology"),
}
"""出厂表白名单映射：Agent 名 → (tool_ids 集合, 内置 skill slug)（设计假设 #5）。"""

_N2_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
"""N2 名称规则：小写字母数字 + 单连字符（设计假设 #2）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（设计假设 #7）。

    镜像 test_provider_config_repo.py：create_all + PRAGMA foreign_keys=ON
    （#327 生产同口径；覆盖 tests/conftest.py 的 db_session）。
    """
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
    """将 FastAPI 的 get_db 替换为本文件 db_session（设计假设 #7），

    API 只读用例与 seed 共享同一 in-memory 库（镜像 tests/api/conftest.py）。
    """
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


@pytest.fixture
def skills_root(monkeypatch, tmp_path) -> Path:
    """文件系统 skill 真源根 = tmp_path/skills + config.data_dir 重定向（设计假设 #8）。

    monkeypatch `inkflow.core.config.config.data_dir` → tmp_path（镜像
    cli/commands/skills.py::_skills_root「测试可 monkeypatch 实例属性」惯例）；
    GREEN 的 ensure/migrate/API 层经 `config.data_dir / "skills"` 解析真源根。
    """
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── 迁移用例辅助（raw SQL 模拟旧 skills 表，设计假设 #4：不 import SkillORM）──


async def _create_legacy_skills_table(db_session, rows: list[dict]) -> None:
    """raw SQL 重建旧 skills 表并插入 rows（[{name, description, content, source}]）。

    DROP + CREATE + INSERT + COMMIT——与 GREEN 迁移实现同口径（sqlalchemy.text），
    全程不触碰 SkillORM（#522 去表后该 ORM 删除）。
    """
    await db_session.execute(text("DROP TABLE IF EXISTS skills"))
    await db_session.execute(
        text(
            "CREATE TABLE skills ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "name VARCHAR(64) NOT NULL,"
            "description TEXT NOT NULL,"
            "content TEXT NOT NULL,"
            "source VARCHAR(20) NOT NULL"
            ")"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO skills (name, description, content, source) "
            "VALUES (:n, :d, :c, :s)"
        ),
        [
            {"n": r["name"], "d": r["description"], "c": r["content"], "s": r["source"]}
            for r in rows
        ],
    )
    await db_session.commit()


async def _count_skills_rows(db_session) -> int:
    """raw SQL 统计旧 skills 表行数（表不存在时调用方保证已建/已删语义）。"""
    row = (await db_session.execute(text("SELECT COUNT(*) FROM skills"))).scalar_one()
    return int(row)


# ── ensure_builtin_skills（设计假设 #1/#2/#3，同步纯文件操作）──


@pytest.mark.integration
class TestEnsureBuiltinSkills:
    """ensure_builtin_skills 契约：同步 + 幂等（首次 6 / 重复 0 / 删 1 回补 1）

    + 每个 SKILL.md frontmatter name=目录名（可被 parse_skill_metadata 校验）。
    """

    def test_first_write_creates_6(self, skills_root):
        """目录缺失/内置缺失 → 写出 6 个英文 slug 内置 SKILL.md，返回 6（#1/#2/#3）。"""
        n = ensure_builtin_skills(skills_root)
        assert n == 6, f"首次写出应返回 6: {n}"

        for slug in BUILTIN_SKILL_NAMES:
            assert (
                skills_root / slug / "SKILL.md"
            ).is_file(), f"缺失内置 skill 文件: {slug}"
        md_files = sorted(p for p in skills_root.rglob("SKILL.md"))
        assert len(md_files) == 6, f"SKILL.md 总数应为 6: {md_files}"

    def test_idempotent_second_call_returns_0(self, skills_root):
        """重复调用返回 0，文件不重复写（#3 幂等）。"""
        assert ensure_builtin_skills(skills_root) == 6
        assert ensure_builtin_skills(skills_root) == 0, "幂等：重复调用必须返回 0"
        assert len(list(skills_root.rglob("SKILL.md"))) == 6

    def test_replenish_deleted_builtin(self, skills_root):
        """删 1 个内置目录后回补 1；全部 SKILL.md frontmatter name=目录名（#3）。"""
        assert ensure_builtin_skills(skills_root) == 6

        removed = "audit-methodology"
        shutil.rmtree(skills_root / removed)
        assert not (skills_root / removed).exists()

        n = ensure_builtin_skills(skills_root)
        assert n == 1, f"删 1 个内置后应回补 1: {n}"
        assert (
            skills_root / removed / "SKILL.md"
        ).is_file(), "删除的内置 skill 必须回补"
        assert len(list(skills_root.rglob("SKILL.md"))) == 6

        for slug in BUILTIN_SKILL_NAMES:
            content = (skills_root / slug / "SKILL.md").read_text(encoding="utf-8")
            meta = parse_skill_metadata(content, slug)
            assert meta.name == slug, f"frontmatter name 必须 = 目录名: {slug}"


# ── migrate_skills_from_db（设计假设 #4，raw SQL 模拟旧表）──


@pytest.mark.asyncio
@pytest.mark.integration
class TestMigrateSkillsFromDb:
    """migrate_skills_from_db 契约：只迁 user_upload 行 → 写出文件 → 清表。

    表不存在 → 0（不抛错、不重建旧表）；迁移实现与测试均不得依赖 SkillORM。
    """

    async def test_user_upload_rows_migrated_and_table_cleared(
        self, db_session, skills_root
    ):
        """user_upload 2 行 → 返回 2；content 原样写出为 <name>/SKILL.md；表清空（#4）。"""
        content_a = "---\nname: legacy-a\ndescription: 旧技能 A\n---\n# A\n"
        content_b = "---\nname: legacy-b\ndescription: 旧技能 B\n---\n# B\n"
        await _create_legacy_skills_table(
            db_session,
            [
                {
                    "name": "legacy-a",
                    "description": "旧技能 A",
                    "content": content_a,
                    "source": "user_upload",
                },
                {
                    "name": "legacy-b",
                    "description": "旧技能 B",
                    "content": content_b,
                    "source": "user_upload",
                },
            ],
        )

        n = await migrate_skills_from_db(db_session, skills_root)
        assert n == 2, f"应迁移 2 条 user_upload 行: {n}"

        f_a = skills_root / "legacy-a" / "SKILL.md"
        f_b = skills_root / "legacy-b" / "SKILL.md"
        assert f_a.read_text(encoding="utf-8") == content_a, "content 必须原样写出"
        assert f_b.read_text(encoding="utf-8") == content_b, "content 必须原样写出"

        assert (
            await _count_skills_rows(db_session) == 0
        ), "迁移后旧表必须清空（含 builtin 行）"

    async def test_builtin_rows_not_migrated(self, db_session, skills_root):
        """旧表仅 builtin 行 → 返回 0；目录空；表仍清空（清表含 builtin 行，#4）。"""
        await _create_legacy_skills_table(
            db_session,
            [
                {
                    "name": "架构方法论",
                    "description": "架构",
                    "content": "---\nname: 架构方法论\n---\n正文",
                    "source": "builtin",
                },
                {
                    "name": "写作方法论",
                    "description": "写作",
                    "content": "---\nname: 写作方法论\n---\n正文",
                    "source": "builtin",
                },
            ],
        )

        n = await migrate_skills_from_db(db_session, skills_root)
        assert n == 0, f"builtin 行不得迁移: {n}"
        assert list(skills_root.iterdir()) == [], "builtin 行不得写出任何 skill 目录"
        assert await _count_skills_rows(db_session) == 0, "清表语义：builtin 行同样被清"

    async def test_table_missing_returns_0(self, db_session, skills_root):
        """旧表不存在 → 返回 0（不抛错）；不写文件；不得重建旧表（#4）。"""
        await db_session.execute(text("DROP TABLE IF EXISTS skills"))
        await db_session.commit()

        n = await migrate_skills_from_db(db_session, skills_root)
        assert n == 0, f"表不存在应返回 0: {n}"
        assert list(skills_root.iterdir()) == [], "表不存在时不得写出任何文件"

        row = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='skills'"
                )
            )
        ).scalar_one()
        assert int(row) == 0, "GREEN 迁移实现不得重建旧 skills 表"


# ── WHITELIST 同步（设计假设 #2/#5：内置 slug 常量 + Agent.skill_ids 目录名）──


@pytest.mark.asyncio
@pytest.mark.integration
class TestWhitelistSync:
    """Agent↔skill 白名单同步契约：#2 实现侧 slug 常量 + #5 skill_ids 目录名语义。"""

    async def test_impl_builtin_skill_names_are_english_slugs(self):
        """实现侧 BUILTIN_SKILL_NAMES 必须 = 6 英文 slug 逐字（#2）。

        RED 期旧实现为中文名（架构方法论…）→ AssertionError FAILED。
        """
        from inkflow.domain.services.skill_service import (
            BUILTIN_SKILL_NAMES as IMPL_NAMES,
        )

        assert (
            IMPL_NAMES == BUILTIN_SKILL_NAMES
        ), f"实现侧 BUILTIN_SKILL_NAMES 必须为英文 slug: {IMPL_NAMES}"
        assert len(BUILTIN_SKILL_NAMES) == 6
        assert len(set(BUILTIN_SKILL_NAMES)) == 6, "slug 必须唯一"
        for slug in BUILTIN_SKILL_NAMES:
            assert _N2_PATTERN.fullmatch(slug), f"slug 必须满足 N2: {slug!r}"

    async def test_skill_ids_are_directory_names(self, db_session):
        """seed_builtin_agents 后：tool_ids 集合不变；skill_ids == [对应 slug]（#5）。

        RED 期旧实现存 DB 主键字符串化 ["1"]..["6"] → AssertionError FAILED。
        """
        assert await seed_builtin_agents(db_session) == 6

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        by_name = {a.name: a for a in rows}
        assert set(by_name) == set(BUILTIN_AGENT_NAMES)
        for name, (tool_ids, slug) in WHITELIST_MAP.items():
            agent = by_name[name]
            assert (
                set(agent.tool_ids) == tool_ids
            ), f"{name} tool_ids 不符: {agent.tool_ids}"
            assert agent.skill_ids == [
                slug
            ], f"{name} skill_ids 必须为 [目录名 slug]: {agent.skill_ids}"


# ── 内置只读 API 409（设计假设 #6，经 tmp skills_root + ensure 后打 API）──


@pytest.mark.asyncio
@pytest.mark.integration
class TestBuiltinReadonly:
    """内置 skill 只读保护契约：PATCH/DELETE 内置 slug → 409 detail「内置 skill 只读」。

    RED 期 ensure stub ImportError 先行 FAIL；GREEN 后 ensure 写出 → 旧 API 的
    name 路径语义（_parse_id 404 ≠ 409）同样被本类锁定。
    """

    async def test_patch_builtin_skill_409(
        self, client, db_session, override_get_db, skills_root
    ):
        """PATCH 内置 slug → 409 + detail「内置 skill 只读」；目录与文件原样保留（#6）。"""
        assert ensure_builtin_skills(skills_root) == 6

        slug = BUILTIN_SKILL_NAMES[0]
        skill_file = skills_root / slug / "SKILL.md"
        original = skill_file.read_text(encoding="utf-8")

        resp = await client.patch(
            f"{SKILL_ENDPOINT}/{slug}", json={"description": "篡改"}
        )
        assert resp.status_code == 409, f"内置 skill PATCH 必须 409: {resp.status_code}"
        assert resp.json()["detail"] == DETAIL_BUILTIN

        assert (skills_root / slug).is_dir(), "内置目录不得被删除"
        assert skill_file.read_text(encoding="utf-8") == original, "内置文件不得被改写"

    async def test_delete_builtin_skill_409(
        self, client, db_session, override_get_db, skills_root
    ):
        """DELETE 内置 slug → 409 + detail「内置 skill 只读」；目录保留（#6）。"""
        assert ensure_builtin_skills(skills_root) == 6

        slug = BUILTIN_SKILL_NAMES[0]
        resp = await client.delete(f"{SKILL_ENDPOINT}/{slug}")
        assert (
            resp.status_code == 409
        ), f"内置 skill DELETE 必须 409: {resp.status_code}"
        assert resp.json()["detail"] == DETAIL_BUILTIN

        assert (skills_root / slug).is_dir(), "内置目录不得被删除"


# ── seed_builtin_agents 保留契约（两态不变锁：旧实现已满足，RED 期 PASS）──


@pytest.mark.asyncio
@pytest.mark.integration
class TestSeedAgents:
    """seed_builtin_agents 保留契约（设计假设 #1/#5 的不变部分，两态皆绿）。

    本类锁定「GREEN 不得改变」的既有语义：async + session 显式注入 + 首写 6 /
    幂等 0 + 出厂中文名 + builtin=True——与 TestWhitelistSync 的 slug 断言互补。
    """

    async def test_seed_agents_first_call_returns_6(self, db_session):
        """首次调用返回 6；6 行落库（builtin=True，名称 = 出厂表）。"""
        n = await seed_builtin_agents(db_session)
        assert n == 6

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        assert len(rows) == 6
        assert {r.name for r in rows} == set(BUILTIN_AGENT_NAMES)
        assert all(r.builtin is True for r in rows)

    async def test_seed_agents_idempotent(self, db_session):
        """重复调用返回 0；表内行数恒为 6（同名跳过，不重复插入）。"""
        assert await seed_builtin_agents(db_session) == 6
        assert await seed_builtin_agents(db_session) == 0

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        assert len(rows) == 6


# ── #954 F58 grants 数据面 — 内置 Agent grants 出厂字面值契约（RED-3，contract §3/§9）──────
#
# 依据：contract-954 §3 表格逐字（内置 6 Agent grants 出厂字面值 = §2.3 反查推断）+ §9 RED-3。
# spec §5.1（tool_ids 列保留不删，双写）——本段【G】守护 tool_ids 旧集合

# 不变，【R】聚焦 grants。
#
# RED 预期形态（当前 AgentORM 无 grants 列 / BUILTIN_AGENT_SPECS 无 grants 键 /
# GrantEntry 不存在）：
# - seed 反查：agent.grants → AttributeError（无列）→ FAILED。
# - 静态断言：GrantEntry 于函数体内 import → ImportError FAILED；且 spec 无 'grants' 键
#   → "grants" in spec AssertionError FAILED。
#
# 【G】= WHITELIST_MAP tool_ids 旧集合断言零改动；【R】= 本段全部新用例。


GRANTS_WHITELIST_MAP = {
    "架构师": {"character": {"read"}, "foreshadowing": {"read"}, "writing": {"read"}},
    "写手": {"character": {"read"}, "foreshadowing": {"read"}, "writing": {"read", "write"}},
    "审校员": {"writing": {"read"}, "character": {"read"}},
    "修订师": {"writing": {"read", "write"}},
    "世界观顾问": {"character": {"read"}, "foreshadowing": {"read"}},
    "润色师": {"writing": {"read"}},
}
"""内置 6 Agent 出厂 grants 字面值（contract-954 §3 表格逐字；

比较形态 {domain: set(ops)} 防序脆弱）。"""


def _grants_to_map(grants) -> dict:
    """grants 归一为 {domain: set(ops)}（接受 GrantEntry 对象或 dict，防序/形态脆弱）."""
    out = {}
    for entry in grants or []:
        if isinstance(entry, dict):
            dom = entry["domain"]
            ops = entry.get("ops") or []
        else:
            dom = entry.domain
            ops = entry.ops or []
        out[str(dom)] = {str(op) for op in ops}
    return out


@pytest.mark.asyncio
@pytest.mark.integration
class TestBuiltinGrants:
    """内置 Agent grants 出厂字面值契约（contract-954 §3 逐字；双写【G】tool_ids 不变）."""

    async def test_seed_grants_match_literal(self, db_session):
        """seed 后每个内置 agent.grants 归一 == GRANTS_WHITELIST_MAP[name]；

        tool_ids 旧集合不变（双写）."""
        assert await seed_builtin_agents(db_session) == 6

        from inkflow.infrastructure.database.models import AgentORM

        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        by_name = {a.name: a for a in rows}
        assert set(by_name) == set(BUILTIN_AGENT_NAMES)
        for name, (tool_ids, _slug) in WHITELIST_MAP.items():
            agent = by_name[name]
            assert (
                _grants_to_map(agent.grants) == GRANTS_WHITELIST_MAP[name]
            ), f"{name} grants 与出厂字面值不符: {agent.grants}"
            # 双写契约【G】：tool_ids 旧集合不变（spec §5.1 tool_ids 保留列）
            assert set(agent.tool_ids) == tool_ids, f"{name} tool_ids 集合被破坏: {agent.tool_ids}"

    async def test_builtin_agent_specs_have_grants(self):
        """BUILTIN_AGENT_SPECS 每项含 'grants' 键且归一值 == GRANTS_WHITELIST_MAP

        （静态断言，不经 DB）."""
        from inkflow.domain.models.agent_grants import GrantEntry  # 【R】

        from inkflow.domain.services.agent_entity_service import BUILTIN_AGENT_SPECS

        assert len(BUILTIN_AGENT_SPECS) == 6
        by_name = {s["name"]: s for s in BUILTIN_AGENT_SPECS}
        assert set(by_name) == set(GRANTS_WHITELIST_MAP)
        for name, grants_map in GRANTS_WHITELIST_MAP.items():
            spec = by_name[name]
            assert "grants" in spec, f"{name} BUILTIN_AGENT_SPECS 缺 grants 键"
            assert isinstance(spec["grants"], list), f"{name} grants 必须为 list[GrantEntry]"
            assert all(isinstance(g, GrantEntry) for g in spec["grants"]), (

                f"{name} grants 元素必须为 GrantEntry"

            )
            assert _grants_to_map(spec["grants"]) == grants_map, f"{name} spec grants 与字面值不符"
