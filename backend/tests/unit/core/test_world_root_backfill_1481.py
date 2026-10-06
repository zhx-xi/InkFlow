"""#1481 存量项目补根幂等迁移 RED 契约测试（`ensure_world_root_for_projects`）.

锁定契约（当前实现无 ensure_world_root_for_projects → 惰性 import 抛 ImportError → FAILED）:

1. world_settings / projects 表不存在（全新环境）→ no-op 不抛错（create_all 负责）
2. 表在但无项目 → 不插入任何行
3. 无根项目（world_settings 空）→ 补默认根「世界观总纲」（parent_id NULL / category ''）
4. 破损态：项目有子条目但无根行 → 补根；**既有行零改动**（不 UPDATE / 不 DELETE）
5. 已有根的项目 → 零副作用 + 重复调用幂等（不重复建、不产生第二根、不改既有根名）
6. 软删项目（is_deleted=1）→ 跳过
7. 旧库 projects 表无 is_deleted 列 → 仍能补根（列存在性自适应）

依据: issue #1481 + specs/f35-world-tree/spec.md §2.1 规则 7 / §5.7 / §7 边界 17-20 / §13 M10。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.services.world_service import WorldService
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository
from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository

# 默认根名（与 domain/models/world.py DEFAULT_WORLD_ROOT_NAME 一致；此处独立字面量，
# 避免自引用弱断言——实现改错常量必须让本文件红）
ROOT_NAME = "世界观总纲"


@pytest.fixture
def sync_conn():
    """独立 in-memory SQLite（同步轨）— 迁移函数测试用（signature: conn: Connection）."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        yield conn
    engine.dispose()


def _create_projects_table(conn, *, with_is_deleted: bool = True) -> None:
    """建 projects 表（is_deleted 列可选，模拟旧库升级前形态）."""
    extra = ", is_deleted BOOLEAN NOT NULL DEFAULT 0" if with_is_deleted else ""
    conn.execute(text(f"CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT{extra})"))


def _create_world_settings_table(conn) -> None:
    """建 world_settings 表（F10 v1.1 真删 + F35 parent_id 形态）."""
    conn.execute(
        text(
            "CREATE TABLE world_settings ("
            "id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, parent_id INTEGER, "
            "category TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '', "
            "extra JSON NOT NULL DEFAULT '{}', created_at TEXT, updated_at TEXT, uuid TEXT)"
        )
    )


def _add_project(conn, name: str, *, is_deleted: int = 0) -> int:
    """插入项目（须已建含 is_deleted 列的 projects 表）并返回 id."""
    conn.execute(
        text("INSERT INTO projects (name, is_deleted) VALUES (:n, :d)"),
        {"n": name, "d": is_deleted},
    )
    return int(conn.execute(text("SELECT max(id) FROM projects")).scalar_one())


def _add_setting(
    conn, project_id: int, name: str, parent_id: int | None, *, category: str = ""
) -> int:
    """插入世界观条目并返回 id."""
    conn.execute(
        text(
            "INSERT INTO world_settings "
            "(project_id, name, parent_id, category, content, extra, created_at, updated_at) "
            "VALUES (:pid, :name, :parent, :cat, '', '{}', '2026-01-01', '2026-01-01')"
        ),
        {"pid": project_id, "name": name, "parent": parent_id, "cat": category},
    )
    return int(conn.execute(text("SELECT max(id) FROM world_settings")).scalar_one())


def _roots(conn, project_id: int | None = None) -> list[tuple[int, str]]:
    """取 (project_id, name) 根行集合（parent_id IS NULL）."""
    sql = "SELECT project_id, name FROM world_settings WHERE parent_id IS NULL"
    params: dict[str, int] = {}
    if project_id is not None:
        sql += " AND project_id = :pid"
        params["pid"] = project_id
    return [(int(r[0]), str(r[1])) for r in conn.execute(text(sql), params).fetchall()]


def _all_rows(conn) -> list[tuple]:
    """取全部行（id, project_id, name, parent_id, category）——用于「既有行零改动」断言."""
    return [
        (int(r[0]), int(r[1]), str(r[2]), r[3], str(r[4]))
        for r in conn.execute(
            text("SELECT id, project_id, name, parent_id, category FROM world_settings ORDER BY id")
        ).fetchall()
    ]


# ────────────────────────────────────────────────────────────────────
# 三形态：表缺失 / 无项目（no-op）· 无根项目（补根）· 有根项目（零副作用）
# ────────────────────────────────────────────────────────────────────


class TestEnsureWorldRootForProjects:
    """ensure_world_root_for_projects 幂等迁移契约."""

    def test_missing_tables_noop(self, sync_conn) -> None:
        """无 world_settings / projects 表（全新环境）→ no-op 不抛错（spec §5.7）."""
        from inkflow.core.database import ensure_world_root_for_projects  # 惰性 import（F23）

        ensure_world_root_for_projects(sync_conn)  # no-op 不抛错

    def test_world_settings_missing_but_projects_present_noop(self, sync_conn) -> None:
        """projects 在、world_settings 缺（极端旧库）→ no-op 不抛错."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        _add_project(sync_conn, "遗留项目")
        ensure_world_root_for_projects(sync_conn)

    def test_no_projects_noop(self, sync_conn) -> None:
        """表齐但无项目 → 不插入任何行."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        _create_world_settings_table(sync_conn)
        ensure_world_root_for_projects(sync_conn)
        assert _all_rows(sync_conn) == []

    def test_project_without_root_gets_default_root(self, sync_conn) -> None:
        """无根项目 → 补默认根「世界观总纲」（parent_id NULL / category ''）."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        _create_world_settings_table(sync_conn)
        pid = _add_project(sync_conn, "新书")

        ensure_world_root_for_projects(sync_conn)

        roots = _roots(sync_conn, pid)
        assert roots == [(pid, ROOT_NAME)]
        # 形态断言：category 空（根无分类，不触发 #1321/#834 分类前置）
        row = sync_conn.execute(
            text("SELECT category, content, parent_id FROM world_settings WHERE project_id = :pid"),
            {"pid": pid},
        ).one()
        assert row[0] == ""
        assert row[1] == ""
        assert row[2] is None

    def test_orphan_children_project_gets_root_and_rows_untouched(self, sync_conn) -> None:
        """破损态：项目有子条目但无根行 → 补根；既有行零改动（只 INSERT）."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        _create_world_settings_table(sync_conn)
        pid = _add_project(sync_conn, "破损项目")
        # 两条「有父无根」历史行（父指向不存在的 999）
        _add_setting(sync_conn, pid, "门派甲", 999, category="门派设定")
        _add_setting(sync_conn, pid, "门派乙", 998, category="门派设定")
        before = _all_rows(sync_conn)
        assert len(before) == 2

        ensure_world_root_for_projects(sync_conn)

        after = _all_rows(sync_conn)
        assert len(after) == 3, "应恰好新增 1 行根"
        assert after[:2] == before, "既有两行必须零改动（不 UPDATE / 不 DELETE）"
        assert _roots(sync_conn, pid) == [(pid, ROOT_NAME)]

    def test_existing_root_untouched_and_idempotent(self, sync_conn) -> None:
        """已有根项目 → 零副作用；重复调用幂等（不重复建、不改根名、不产生第二根）."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        _create_world_settings_table(sync_conn)
        pid = _add_project(sync_conn, "老项目")
        _add_setting(sync_conn, pid, "我的自定义根", None)
        _add_setting(sync_conn, pid, "子条目", 1, category="地理")
        before = _all_rows(sync_conn)

        ensure_world_root_for_projects(sync_conn)
        ensure_world_root_for_projects(sync_conn)  # 幂等：第二次 no-op

        assert _all_rows(sync_conn) == before
        assert _roots(sync_conn, pid) == [(pid, "我的自定义根")], "既有根不得被改名/替换"

    def test_soft_deleted_project_skipped(self, sync_conn) -> None:
        """软删项目（is_deleted=1）→ 跳过（不为回收站项目建根）."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        _create_world_settings_table(sync_conn)
        alive = _add_project(sync_conn, "在架")
        trashed = _add_project(sync_conn, "回收站", is_deleted=1)

        ensure_world_root_for_projects(sync_conn)

        assert _roots(sync_conn, alive) == [(alive, ROOT_NAME)]
        assert _roots(sync_conn, trashed) == []

    def test_legacy_projects_table_without_is_deleted_still_backfills(self, sync_conn) -> None:
        """旧库 projects 表无 is_deleted 列 → 仍能补根（列存在性自适应，不抛 no such column）."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn, with_is_deleted=False)
        _create_world_settings_table(sync_conn)
        sync_conn.execute(text("INSERT INTO projects (name) VALUES ('远古项目')"))
        pid = int(sync_conn.execute(text("SELECT max(id) FROM projects")).scalar_one())

        ensure_world_root_for_projects(sync_conn)

        assert _roots(sync_conn, pid) == [(pid, ROOT_NAME)]

    def test_multi_project_backfill_is_per_project(self, sync_conn) -> None:
        """多项目混合（1 有根 + 2 无根）→ 各补各的，互不串根."""
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        _create_world_settings_table(sync_conn)
        p1 = _add_project(sync_conn, "有根")
        p2 = _add_project(sync_conn, "无根甲")
        p3 = _add_project(sync_conn, "无根乙")
        _add_setting(sync_conn, p1, "既有根", None)

        ensure_world_root_for_projects(sync_conn)

        assert _roots(sync_conn, p1) == [(p1, "既有根")]
        assert _roots(sync_conn, p2) == [(p2, ROOT_NAME)]
        assert _roots(sync_conn, p3) == [(p3, ROOT_NAME)]

    def test_v011_schema_without_extra_or_timestamps_still_backfills(self, sync_conn) -> None:
        """极旧库（world_settings 无 extra / created_at / updated_at 列）→ 仍能补根.

        实测缺陷守护：硬编码列名时 SQLite 在 prepare 阶段即报
        「table world_settings has no column named extra」——即便 projects 为空也会失败
        （test_database_migration_chain.py v0.11 全链用例捕获）。
        """
        from inkflow.core.database import ensure_world_root_for_projects

        _create_projects_table(sync_conn)
        sync_conn.execute(
            text(
                "CREATE TABLE world_settings ("
                "id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, parent_id INTEGER, "
                "category TEXT NOT NULL, content TEXT NOT NULL, is_deleted BOOLEAN DEFAULT 0)"
            )
        )
        pid = _add_project(sync_conn, "远古项目")

        ensure_world_root_for_projects(sync_conn)

        assert _roots(sync_conn, pid) == [(pid, ROOT_NAME)]


# ────────────────────────────────────────────────────────────────────
# 端到端：迁移写入的行必须能被 ORM / 领域层读回
# （CURRENT_TIMESTAMP 存储格式 + extra JSON 兼容 + uuid 身份列可回填）
# ────────────────────────────────────────────────────────────────────


@pytest.fixture
async def async_engine():
    """真实 in-memory SQLite（async 轨）—— ORM 读回验证用."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def test_backfilled_root_readable_through_orm(async_engine) -> None:
    """迁移补的根行可被 WorldService 正常读回（时间戳格式 / 领域映射 / extra JSON 全兼容）."""
    from inkflow.core.database import ensure_world_root_for_projects

    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # 造「旧库破损态」：项目有子条目但无根（项目经 ORM 落库 → 该路径不建根；
        # 子条目 raw SQL 落库，确保确实无根）
        orm = ProjectORM(name="旧书")
        session.add(orm)
        await session.commit()
        await session.refresh(orm)
        pid = int(orm.id)
        await session.execute(
            text(
                "INSERT INTO world_settings "
                "(project_id, name, parent_id, category, content, extra, created_at, updated_at) "
                "VALUES (:pid, '门派甲', 999, '门派设定', '', '{}', '2026-01-01', '2026-01-01')"
            ),
            {"pid": pid},
        )
        await session.commit()

    async with async_engine.begin() as conn:
        await conn.run_sync(ensure_world_root_for_projects)

    async with factory() as session:
        svc = WorldService(
            repository=SQLiteWorldRepository(session),
            project_repo=SQLiteProjectRepository(session),
        )
        roots, total = await svc.list_settings(uuid.UUID(int=pid), top_level_only=True)

        assert total == 1
        assert roots[0].name == ROOT_NAME
        assert roots[0].category == ""
        assert roots[0].parent_id is None
        assert roots[0].extra == {}
        assert roots[0].created_at is not None
