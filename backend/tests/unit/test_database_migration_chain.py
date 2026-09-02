"""S3d 数据库迁移回归（issue #869 非功能补测第四批）：完整迁移链 / 失败回滚 / wiring 门禁.

锁定三层此前无测试的现状（设计定稿 .hermes/plans/s3d-design.md §0-2，scratch 实证）：

D1 完整迁移链：v0.11 / v1.1 / v1.2 三版本旧库 → ``app.lifespan`` 全量迁移链
   （create_tables + 26 个 ensure_* + run_character_group_members_migration + seed）→
   最终 schema 列集 / 存量行数保全 / 软删清除 / FK 完好（foreign_key_check 空）/
   seed 计数 / 重启幂等。既有 test_database_migrations_coverage.py 只锁单 helper，
   链内交互（#831/#856 分组重建与 is_deleted 真删链式执行、chat_messages 回填依赖
   create_all 先建的 conversations 表）单测锁不住。用真实 SQLite 文件库（非
   :memory:，文件级迁移动作 + WAL/FK pragma 语义）。
D2 迁移中途失败回滚：_rebuild_characters_without_group_id 的 DROP→RENAME 窗口注入
   崩溃（before_cursor_execute 事件）→ 断言不留 _characters_new / 空 characters、
   characters 数据完好、新连接 FK=ON、重启整段重试成功（#856 WARN-1 语义的
   崩溃注入实证——既有测试只模拟『残留 _characters_new 后重试』，未证事务真回滚）。
D3 迁移 wiring 门禁：lifespan 实际调用的 ensure_* 集合（AST 提取，禁 substring——
   ensure_world_categories 是 ensure_world_categories_kind_column 的子串会假绿）
   必须等于 core/database.py 注册集合（含经 run_character_group_members_migration
   间接接线）。⚠️ RED 锚点：当前 ensure_world_categories 未接线 → 必 FAIL。

依据: specs/f10-world-settings/spec.md §8.3（数据迁移约定）+ issue #831/#856/#869。
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models  # noqa: F401  # Base.metadata 注册
from inkflow.core import database as db_module
from inkflow.core.config import config

app_module = importlib.import_module("inkflow.api.app")


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _tables(conn) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {row[0] for row in rows}


def _scalar(conn, sql: str) -> int:
    row = conn.execute(text(sql)).fetchone()
    assert row is not None
    return int(row[0])


# ── 旧库建造器（v0.11 / v1.1 / v1.2 代表列集 + 携带数据） ──


def _create_v011(db: Path) -> dict[str, int]:
    """v0.11：软删语义 + characters.group_id FK + chat_messages 无 conversation_id.

    world_settings 取 #173 前形态（无 parent_id 列、旧全局唯一 partial 索引）——
    该版本升级路径上 ensure_world_root_unique_index 与软删清理的顺序存在真缺陷
    （.hermes/scratch/s3d_world_root_probe.py 实证 IntegrityError），由
    test_d1_world_legacy_root_ordering 单独锁定，此处不触发。

    ⚠️ 真实形态护栏（fixture 保真）：
    - projects 行必备——chat 回填 INSERT 出的 conversations.project_id 受 FK 约束，
      真实库有消息必有项目（issue #869 S3d D1）；
    - 多根 + 软删根行——锁定 #849 根单例索引升级对 #173/#211 前存量库的降级
      与清理顺序（缺陷 A）。
    """
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE projects ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
            )
        )
        conn.execute(
            text("INSERT INTO projects (id, name) VALUES (1, '蜀山'), (2, '他项目')")
        )
        conn.execute(
            text(
                "CREATE TABLE character_groups ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, is_deleted BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE characters ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, group_id INTEGER, "
                "is_deleted BOOLEAN NOT NULL DEFAULT 0, "
                "FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL)"
            )
        )
        conn.execute(text("CREATE INDEX ix_characters_group_id ON characters(group_id)"))
        conn.execute(
            text(
                "CREATE TABLE character_relations ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "from_character_id INTEGER NOT NULL, to_character_id INTEGER NOT NULL, "
                "relation_type TEXT NOT NULL, "
                "FOREIGN KEY(from_character_id) REFERENCES characters(id) ON DELETE CASCADE, "
                "FOREIGN KEY(to_character_id) REFERENCES characters(id) ON DELETE CASCADE)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE world_settings ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL, "
                "is_deleted BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_world_settings_active_name ON world_settings"
                "(project_id, name) WHERE is_deleted = 0"
            )
        )
        # v0.11 真实形态：world 条目按 category 多行（同项目多根）——旧版本无根单例
        # 约束。#849 根唯一索引迁移若在 is_deleted 清理之前执行（当前 lifespan 接线
        # 顺序），本库升级即 IntegrityError（test_d1_full_lifespan_migration_chain
        # [v0.11] 锁定的链级顺序缺陷）。
        conn.execute(
            text(
                "CREATE TABLE chat_messages ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "role TEXT NOT NULL, content TEXT NOT NULL)"
            )
        )
        conn.execute(
            text("INSERT INTO character_groups (id, project_id, name) VALUES (1, 1, '蜀山')")
        )
        conn.execute(
            text(
                "INSERT INTO characters (id, project_id, name, group_id) "
                "VALUES (1, 1, '玄明', 1), (2, 1, '宁晚', 1), (3, 1, '路人', NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO character_relations "
                "(project_id, from_character_id, to_character_id, relation_type) "
                "VALUES (1, 1, 2, '师妹')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO world_settings (project_id, name, category, content) "
                "VALUES (1, '剑峰', 'geo', '蜀山主峰')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO world_settings (project_id, name, category, content) "
                "VALUES (1, '灵兽宗', 'sect', '盟友宗门')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO world_settings (project_id, name, category, content, is_deleted) "
                "VALUES (1, '废弃条目', 'misc', '旧软删数据', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO chat_messages (project_id, role, content) "
                "VALUES (1, 'user', '开篇'), (1, 'assistant', '好的'), (2, 'user', '他项目')"
            )
        )
    engine.dispose()
    return {"characters": 3, "relations": 1, "members": 2, "world": 2, "messages": 3}


def _create_v11(db: Path) -> dict[str, int]:
    """v1.1（#211 真删后）：无 is_deleted、characters 仍带 group_id FK。"""
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE character_groups ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE characters ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, group_id INTEGER, "
                "FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL)"
            )
        )
        conn.execute(text("CREATE INDEX ix_characters_group_id ON characters(group_id)"))
        conn.execute(
            text("INSERT INTO character_groups (id, project_id, name) VALUES (1, 1, '蜀山')")
        )
        conn.execute(
            text(
                "INSERT INTO characters (id, project_id, name, group_id) "
                "VALUES (1, 1, '玄明', 1), (2, 1, '宁晚', NULL)"
            )
        )
    engine.dispose()
    return {"characters": 2, "relations": 0, "members": 1, "world": 0, "messages": 0}


def _create_v12(db: Path) -> dict[str, int]:
    """v1.2（#701 后）：characters 已无 group_id，world_categories 缺 kind，会话缺 title。"""
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE characters ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE character_group_members ("
                "character_id INTEGER NOT NULL, group_id INTEGER NOT NULL, "
                "PRIMARY KEY(character_id, group_id))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE world_categories ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE conversations ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "created_at DATETIME NOT NULL, is_deleted BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(text("INSERT INTO characters (id, project_id, name) VALUES (1, 1, '玄明')"))
        conn.execute(
            text("INSERT INTO character_group_members (character_id, group_id) VALUES (1, 1)")
        )
        conn.execute(text("INSERT INTO world_categories (project_id, name) VALUES (1, 'geo')"))
    engine.dispose()
    return {"characters": 1, "relations": 0, "members": 1, "world": 0, "messages": 0}


BUILDERS = {"v0.11": _create_v011, "v1.1": _create_v11, "v1.2": _create_v12}


def _create_world_legacy(db: Path) -> dict[str, int]:
    """#211 后、#849 前专项旧库：world_settings 同项目多根（无软删列）。

    lifespan 顺序缺陷的最小复现面：ensure_world_root_unique_index 建根单例唯一
    索引时存量多根行（parent_id 全 NULL）→ IntegrityError，启动崩溃。
    修复前该库形态所有存量用户（#211 后建的多条目项目）升级到 #849 均受影响。
    """
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_settings ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL, "
                "parent_id INTEGER)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO world_settings (project_id, name, category, content) "
                "VALUES (1, '剑峰', 'geo', '蜀山主峰'), (1, '灵兽宗', 'sect', '盟友宗门')"
            )
        )
    engine.dispose()
    return {"characters": 0, "relations": 0, "members": 0, "world": 2, "messages": 0}


@contextlib.asynccontextmanager
async def _migration_chain_env(tmp_path: Path, build: object):
    """建造旧库文件 + 重定向 lifespan 全局（engine/factory/data_dir），退出还原。

    ⚠️ 双换：``db_module.engine``（create_tables / run_character_group_members_migration
    运行时解析模块全局）与 ``app_module.engine`` / ``app_module.async_session_factory``
    （app.py from-import 独立绑定）。缺一则 lifespan 打到真实数据目录。
    """
    db_file = tmp_path / "inkflow.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    expected = build(db_file)  # type: ignore[misc]  # 建造旧库，返回期望行数

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    event.listen(engine.sync_engine, "connect", db_module._set_sqlite_pragma)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    saved = (
        db_module.engine,
        db_module.async_session_factory,
        app_module.engine,
        app_module.async_session_factory,
        config.data_dir,
    )
    db_module.engine = engine
    db_module.async_session_factory = factory
    app_module.engine = engine
    app_module.async_session_factory = factory
    config.data_dir = data_dir
    try:
        yield engine, expected
    finally:
        await engine.dispose()
        (
            db_module.engine,
            db_module.async_session_factory,
            app_module.engine,
            app_module.async_session_factory,
            config.data_dir,
        ) = saved


async def _run_lifespan(engine) -> None:
    """完整驱动一次 app lifespan（启动迁移链 + seed + 优雅关闭 scheduler）。"""
    fake_app = SimpleNamespace(state=SimpleNamespace())
    async with app_module.lifespan(fake_app):
        pass


@pytest.mark.parametrize("version", sorted(BUILDERS))
async def test_d1_full_lifespan_migration_chain(tmp_path: Path, version: str) -> None:
    """旧库 → lifespan 全量链 → schema/行数/FK 完好 + 重启幂等（回归锁定）。"""
    build = BUILDERS[version]
    async with _migration_chain_env(tmp_path, build) as (engine, expect):
        await _run_lifespan(engine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(_tables)
            cols = await conn.run_sync(_columns, "characters")
            ws_cols = await conn.run_sync(_columns, "world_settings")
            wm_cols = await conn.run_sync(_columns, "chat_messages")
            conv_cols = await conn.run_sync(_columns, "conversations")
            wc_cols = await conn.run_sync(_columns, "world_categories")

            assert "character_group_members" in tables
            assert "world_categories" in tables
            # 旧列移除 + 新列补齐（全链终点 = 当前 ORM schema 形态）
            assert "group_id" not in cols
            assert "is_deleted" not in cols
            assert "brief" in cols
            assert "is_deleted" not in ws_cols
            assert "parent_id" in ws_cols
            assert "conversation_id" in wm_cols and "is_deleted" in wm_cols
            assert "title" in conv_cols and "delete_permission" in conv_cols
            assert "kind" in wc_cols
            assert "_characters_new" not in tables  # 无临时表残留

            # 存量数据保全 / 链内交互（软删清除 + 回填 + FK 不级联清空）
            assert (
                await conn.run_sync(_scalar, "SELECT COUNT(*) FROM characters")
                == (expect["characters"])
            )
            assert (
                await conn.run_sync(_scalar, "SELECT COUNT(*) FROM character_relations")
                == (expect["relations"])
            )
            assert (
                await conn.run_sync(_scalar, "SELECT COUNT(*) FROM character_group_members")
                == (expect["members"])
            )
            # 软删行清除（is_deleted 列已删，行数即活行数）+ 存量保全
            assert (
                await conn.run_sync(_scalar, "SELECT COUNT(*) FROM world_settings")
                == (expect["world"])
            )
            # chat_messages 回填（create_all 先建 conversations → ensure 链式回填，
            # 单 helper 测不到的链内交互）
            nulls = await conn.run_sync(
                _scalar,
                "SELECT COUNT(*) FROM chat_messages WHERE conversation_id IS NULL",
            )
            assert nulls == 0

            # FK 完好：违例为空 + 新连接 pragma 生效
            violations = (await conn.execute(text("PRAGMA foreign_key_check"))).fetchall()
            assert violations == []
            fk = (await conn.execute(text("PRAGMA foreign_keys"))).fetchone()
            assert fk is not None and int(fk[0]) == 1

            # seed 幂等接线（链尾）
            assert await conn.run_sync(_scalar, "SELECT COUNT(*) FROM provider_configs") == 4
            assert await conn.run_sync(_scalar, "SELECT COUNT(*) FROM agents") == 6

            # v0.11 专属：#849 根单例索引升级不得崩（修复前 IntegrityError——
            # RED 锚点 2）；存量多根降级 = 每项目至多一个根，其余挂首根（#834 模型）
            if version == "v0.11":
                roots = await conn.run_sync(
                    _scalar, "SELECT COUNT(*) FROM world_settings WHERE parent_id IS NULL"
                )
                assert roots == 1
                demoted = await conn.run_sync(
                    _scalar,
                    "SELECT COUNT(*) FROM world_settings "
                    "WHERE parent_id IS NOT NULL AND name = '灵兽宗'",
                )
                assert demoted == 1  # 存量顶层条目降级挂根，数据零丢失

        # 重启幂等：二次 lifespan 行数/表集稳定
        await _run_lifespan(engine)
        async with engine.connect() as conn:
            assert (
                await conn.run_sync(_scalar, "SELECT COUNT(*) FROM characters")
                == (expect["characters"])
            )
            assert await conn.run_sync(_scalar, "SELECT COUNT(*) FROM provider_configs") == 4
            assert await conn.run_sync(_scalar, "SELECT COUNT(*) FROM agents") == 6
            assert await conn.run_sync(_scalar, "SELECT COUNT(*) FROM conversations") == (
                2 if version == "v0.11" else 0
            )


async def test_d2_migration_crash_rolls_back_and_retry_succeeds(tmp_path: Path) -> None:
    """DROP→RENAME 窗口注入崩溃 → 事务回滚不留残骸、FK 恢复、重启整段重试成功。"""
    build = _create_v11
    async with _migration_chain_env(tmp_path, build) as (engine, expect):
        state = {"inject": True}

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _boom(dbapi_conn, cursor, statement, parameters, context, executemany):
            if state["inject"] and statement.strip().upper().startswith("DROP TABLE CHARACTERS"):
                raise RuntimeError("injected mid-migration crash")

        try:
            with pytest.raises(RuntimeError, match="injected mid-migration crash"):
                await db_module.run_character_group_members_migration()

            async with engine.connect() as conn:
                tables = await conn.run_sync(_tables)
                cols = await conn.run_sync(_columns, "characters")
                # 原子回滚：不留 _characters_new / 空 characters，数据原样（迁移前态）
                assert "_characters_new" not in tables
                assert "characters" in tables
                assert "group_id" in cols
                assert (
                    await conn.run_sync(_scalar, "SELECT COUNT(*) FROM characters")
                    == (expect["characters"])
                )
                # finally 恢复 FK=ON（新连接观察默认 pragma 语义完好）
                fk = (await conn.execute(text("PRAGMA foreign_keys"))).fetchone()
                assert fk is not None and int(fk[0]) == 1

            # 修复 → 重启整段重试成功（幂等自愈）
            state["inject"] = False
            await db_module.run_character_group_members_migration()
            async with engine.connect() as conn:
                cols = await conn.run_sync(_columns, "characters")
                assert "group_id" not in cols
                assert (
                    await conn.run_sync(_scalar, "SELECT COUNT(*) FROM characters")
                    == (expect["characters"])
                )
                assert (
                    await conn.run_sync(_scalar, "SELECT COUNT(*) FROM character_group_members")
                    == expect["members"]
                )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _boom)


async def test_d1_world_legacy_multi_root_upgrade(tmp_path: Path) -> None:
    """#211→#849 区间专项：多根存量库升级不崩、首根保留、其余降级挂根（零删除）。

    RED 锚点 2 的最小复现面：修复前 lifespan 中 ensure_world_root_unique_index
    先于 is_deleted 清理执行，且无多根降级步骤 → CREATE UNIQUE INDEX 撞多根
    IntegrityError（scratch s3d_world_root_probe.py 实证）。
    """
    build = _create_world_legacy
    async with _migration_chain_env(tmp_path, build) as (engine, expect):
        await _run_lifespan(engine)
        async with engine.connect() as conn:
            assert (
                await conn.run_sync(_scalar, "SELECT COUNT(*) FROM world_settings")
                == (expect["world"])
            )
            roots = await conn.run_sync(
                _scalar, "SELECT COUNT(*) FROM world_settings WHERE parent_id IS NULL"
            )
            assert roots == 1
            demoted = await conn.run_sync(
                _scalar,
                "SELECT COUNT(*) FROM world_settings "
                "WHERE parent_id IS NOT NULL AND name = '灵兽宗'",
            )
            assert demoted == 1


# ── D3 wiring 门禁 ──


def _registered_ensure_fns() -> set[str]:
    """core/database.py 模块级公开 ensure_* 注册集合（迁移助手单一事实源）。"""
    return {
        name
        for name, obj in vars(db_module).items()
        if name.startswith("ensure_")
        and callable(obj)
        and getattr(obj, "__module__", "") == db_module.__name__
    }


def _lifespan_called_names() -> set[str]:
    """AST 精确提取 lifespan 函数体引用的名字集合。

    ⚠️ 禁 substring 匹配：ensure_world_categories 是 ensure_world_categories_kind_column
    的子串，文本包含判断会假绿（scratch 实证该门禁形态本身必须 AST 化）。
    """
    spec = importlib.util.find_spec("inkflow.api.app")
    assert spec is not None and spec.origin is not None
    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source)
    lifespan_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        ),
        None,
    )
    assert lifespan_node is not None, "lifespan 函数未找到（门禁形态失效，非迁移缺陷）"
    names: set[str] = set()
    for node in ast.walk(lifespan_node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _indirect_via_group_migration() -> set[str]:
    """run_character_group_members_migration 内部转接的 ensure_*（间接接线）。"""
    import inspect

    source = inspect.getsource(db_module.run_character_group_members_migration)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("ensure_"):
            names.add(node.id)
    return names


def test_d3_lifespan_wiring_covers_all_registered_migrations() -> None:
    """门禁：注册集合 == lifespan 直接接线 ∪ 间接接线（漏接线/幻影注册都红）。"""
    registered = _registered_ensure_fns()
    wired = _lifespan_called_names() & registered
    indirect = _indirect_via_group_migration() & registered

    # 提取器健全性护栏（防恒真断言：registered 非空、lifespan 至少接一大半）
    assert len(registered) >= 20, f"注册集提取异常: {sorted(registered)}"
    assert len(wired) >= 20, f"lifespan 接线提取异常: {sorted(wired)}"

    missing = registered - wired - indirect
    assert missing == set(), (
        "以下迁移助手已注册但未被 lifespan 接线（新迁移忘接 = 存量库静默不迁移）: "
        f"{sorted(missing)}"
    )
