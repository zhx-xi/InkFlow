"""#831 回归锁定：旧库升级 DROP character.group_id 被 FK 引用拒止（#820 残留回归）.

旧 schema（v0.11.0 等）characters 表含 ``group_id`` 列，且被外键
``FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL`` 引用。
``ensure_character_group_members_migration``（core/database.py #701）只枚举 DROP 了依赖
group_id 的**索引**，遗漏了 FK 约束 → SQLite ``DROP COLUMN group_id`` 抛
``OperationalError: unknown column "group_id" in foreign key definition`` → 启动失败。

本文件锁定两层缺陷：
A. **FK 拒止**：迁移须用重建表路径安全移除 group_id 列（旧列被 FK 引用）。
B. **FK=ON 主事务内无法安全重建**：app lifespan 在主迁移事务（FK=ON）内调用时
   ``PRAGMA foreign_keys=OFF`` 是 no-op，直接 ``DROP TABLE characters`` 会沿 FK CASCADE
   清空 ``character_relations`` 与回填后的 ``character_group_members``（数据丢失）。
   修复 = 独立 AUTOCOMMIT 连接 + FK=OFF + 主事务提交后执行
   （``run_character_group_members_migration``）。

依据: specs/f10-world-settings/spec.md §8.3（数据迁移约定）+ issue #831。
"""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import create_async_engine

from inkflow.core import database as db_module
from inkflow.core.database import (
    ensure_character_group_members_migration,
    run_character_group_members_migration,
)


def _tables(conn) -> list[str]:
    """返回库内所有用户表名。"""
    return [
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).fetchall()
    ]


def _columns(conn, table: str) -> list[str]:
    """返回表当前列名列表（按位置序）。"""
    return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]


def _create_old_schema(conn) -> None:
    """建造 v0.11.0 旧 schema：characters 含 group_id 列 + FK + 索引 + 关联关系表。"""
    conn.execute(
        text(
            "CREATE TABLE character_groups ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project_id INTEGER NOT NULL, "
            "name TEXT NOT NULL)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE characters ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project_id INTEGER NOT NULL, "
            "name TEXT NOT NULL, "
            "group_id INTEGER, "
            "FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL)"
        )
    )
    conn.execute(text("CREATE INDEX ix_characters_group_id ON characters(group_id)"))
    conn.execute(
        text(
            "CREATE TABLE character_relations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "from_character_id INTEGER NOT NULL, "
            "to_character_id INTEGER NOT NULL, "
            "FOREIGN KEY(from_character_id) REFERENCES characters(id) ON DELETE CASCADE, "
            "FOREIGN KEY(to_character_id) REFERENCES characters(id) ON DELETE CASCADE)"
        )
    )
    conn.execute(
        text("INSERT INTO character_groups (id, project_id, name) VALUES (1, 1, 'g')")
    )
    conn.execute(
        text("INSERT INTO character_groups (id, project_id, name) VALUES (2, 1, 'g2')")
    )
    conn.execute(
        text("INSERT INTO characters (id, project_id, name, group_id) VALUES (1, 1, 'c1', 1)")
    )
    conn.execute(
        text("INSERT INTO characters (id, project_id, name, group_id) VALUES (2, 1, 'c2', 1)")
    )
    conn.execute(
        text("INSERT INTO characters (id, project_id, name, group_id) VALUES (3, 1, 'c3', NULL)")
    )
    conn.execute(
        text(
            "INSERT INTO character_relations (id, from_character_id, to_character_id) "
            "VALUES (1, 1, 2)"
        )
    )


# ── 类 A：迁移函数（FK=OFF 调用者上下文，由 run_character_group_members_migration 提供）──


def test_migration_function_removes_group_id_backfills_and_preserves_relations() -> None:
    """旧库（FK=OFF 调用者）→ 迁移成功：group_id 移除 + 关联表回填 + 关系保全（不级联清空）。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_old_schema(conn)

    with engine.connect() as conn:
        ensure_character_group_members_migration(conn)

        assert "character_group_members" in _tables(conn)
        assert "group_id" not in _columns(conn, "characters")
        members = conn.execute(
            text("SELECT character_id, group_id FROM character_group_members ORDER BY character_id")
        ).fetchall()
        assert members == [(1, 1), (2, 1)]  # c3 未分组不写关联表
        # 关系表不被级联清空（FK=OFF 下 DROP 不触发 CASCADE）
        rels = conn.execute(text("SELECT COUNT(*) FROM character_relations")).fetchone()
        assert rels is not None and rels[0] == 1
    engine.dispose()


def test_migration_function_idempotent() -> None:
    """ensure_* 幂等：旧库迁移后可反复执行不报错，关联表不重复回填。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_old_schema(conn)

    with engine.connect() as conn:
        ensure_character_group_members_migration(conn)
        ensure_character_group_members_migration(conn)  # 列已移除 → no-op
        ensure_character_group_members_migration(conn)

        assert "group_id" not in _columns(conn, "characters")
        members = conn.execute(
            text("SELECT COUNT(*) FROM character_group_members")
        ).fetchone()
        assert members is not None and members[0] == 2
    engine.dispose()


def test_fresh_schema_noop_without_group_id() -> None:
    """全新库（create_all 已建关联表，characters 无 group_id 列）→ no-op 正常启动。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE character_groups ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE characters ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE character_group_members ("
                "character_id INTEGER NOT NULL, "
                "group_id INTEGER NOT NULL, "
                "PRIMARY KEY(character_id, group_id))"
            )
        )
        conn.execute(
            text("INSERT INTO character_groups (id, project_id, name) VALUES (1, 1, 'g')")
        )
        conn.execute(
            text("INSERT INTO characters (id, project_id, name) VALUES (1, 1, 'c1')")
        )

    with engine.connect() as conn:
        ensure_character_group_members_migration(conn)  # no-op 不抛错
        assert "group_id" not in _columns(conn, "characters")
    engine.dispose()


# ── 类 B：app 启动接线（FK=ON + 独立 AUTOCOMMIT FK=OFF helper，锁定第二层缺陷）──


def _async_engine(tmp_path):
    """构造 aiosqlite async 引擎 + 注册真实 FK=ON/WAL connect 事件（模拟 app 启动）。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upg.db'}")
    event.listen(engine.sync_engine, "connect", db_module._set_sqlite_pragma)
    return engine


async def _run_helper_via_app_path(engine):
    """模拟 app lifespan：主迁移事务提交后调用 run_character_group_members_migration。"""
    old = db_module.engine
    db_module.engine = engine
    try:
        await run_character_group_members_migration()
    finally:
        db_module.engine = old


async def test_upgrade_helper_startup_removes_group_id_and_preserves_data(tmp_path):
    """真实启动路径（FK=ON connect + 主事务后 helper）→ 旧库升级成功、数据保全。"""
    engine = _async_engine(tmp_path)
    try:
        # 建旧 schema（FK=ON 生效）
        async with engine.begin() as conn:
            await conn.run_sync(_create_old_schema)

        await _run_helper_via_app_path(engine)

        async with engine.connect() as conn:
            cols = await conn.run_sync(lambda c: _columns(c, "characters"))
            rels = (await conn.execute(text("SELECT COUNT(*) FROM character_relations"))).fetchone()
            members = (
                await conn.execute(text("SELECT COUNT(*) FROM character_group_members"))
            ).fetchone()
            # FK=ON 主事务内无法重建，必须走独立 FK=OFF helper：#831 回归断言
            assert "group_id" not in cols
            assert rels is not None and rels[0] == 1  # 关系保全，未级联清空
            assert members is not None and members[0] == 2  # 存量分组归属回填
    finally:
        await engine.dispose()


async def test_upgrade_helper_idempotent(tmp_path):
    """helper 幂等：旧库升级后可反复执行不报错，关联表不重复回填。"""
    engine = _async_engine(tmp_path)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_create_old_schema)

        await _run_helper_via_app_path(engine)
        await _run_helper_via_app_path(engine)  # 幂等重跑

        async with engine.connect() as conn:
            members = (
                await conn.execute(text("SELECT COUNT(*) FROM character_group_members"))
            ).fetchone()
            assert members is not None and members[0] == 2
    finally:
        await engine.dispose()
