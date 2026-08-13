"""#211 v1.1 软删→真删迁移函数契约测试（ensure_*_drop_is_deleted + _migrate_drop_is_deleted）.

覆盖 core/database.py 的 5 个迁移函数：旧库迁移（存量软删清理 + 索引重建 + 删列）、
全新 schema no-op、表缺失 no-op、无唯一索引表。真 SQLite 同步轨（in-memory）。

依据: specs/f10-world-service/spec.md §8.3（数据库迁移）。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from inkflow.core.database import (
    _migrate_drop_is_deleted,
    ensure_character_drop_is_deleted,
    ensure_foreshadowing_drop_is_deleted,
    ensure_outline_drop_is_deleted,
    ensure_timeline_drop_is_deleted,
    ensure_world_drop_is_deleted,
)


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合。"""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _names(conn, table: str) -> list[tuple]:
    """返回表内 name 列（升序）。"""
    return list(conn.execute(text(f"SELECT name FROM {table} ORDER BY name")).fetchall())


# ── _migrate_drop_is_deleted 通用逻辑（4 场景）─────────────────────────────


def test_migrate_drop_old_db_cleans_soft_deleted_and_rebuilds_unique_index():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, is_deleted INTEGER DEFAULT 0)")
        )
        conn.execute(text("INSERT INTO t (name, is_deleted) VALUES ('del', 1), ('live', 0)"))
        conn.execute(text("CREATE UNIQUE INDEX uq_t_name ON t (name) WHERE is_deleted = 0"))
        conn.commit()

        _migrate_drop_is_deleted(conn, "t", {"uq_t_name": "name"})
        conn.commit()

        assert "is_deleted" not in _cols(conn, "t")
        assert _names(conn, "t") == [("live",)]


def test_migrate_drop_fresh_schema_noop():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.commit()
        _migrate_drop_is_deleted(conn, "t", {"uq_t_name": "name"})  # no-op 不抛错
        assert "is_deleted" not in _cols(conn, "t")


def test_migrate_drop_missing_table_noop():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _migrate_drop_is_deleted(conn, "nonexistent")  # no-op 不抛错


def test_migrate_drop_no_unique_index_table():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, is_deleted INTEGER DEFAULT 0)")
        )
        conn.execute(text("INSERT INTO t (name, is_deleted) VALUES ('del', 1), ('live', 0)"))
        conn.commit()
        _migrate_drop_is_deleted(conn, "t")  # 无 unique_indexes → 仅清理 + 删列
        conn.commit()
        assert "is_deleted" not in _cols(conn, "t")
        assert _names(conn, "t") == [("live",)]


# ── 5 个 ensure_* 包装（旧库迁移，覆盖包装 + 索引重建）────────────────────


def test_ensure_world_drop_is_deleted():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_settings (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "parent_id INTEGER, name TEXT, is_deleted INTEGER DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO world_settings (project_id, name, is_deleted) "
                "VALUES (1, 'del', 1), (1, 'live', 0)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_world_settings_active_name_parent "
                "ON world_settings (project_id, parent_id, name) WHERE is_deleted = 0"
            )
        )
        conn.commit()
        ensure_world_drop_is_deleted(conn)
        conn.commit()
        assert "is_deleted" not in _cols(conn, "world_settings")
        assert _names(conn, "world_settings") == [("live",)]


def test_ensure_world_drop_is_deleted_fresh_schema_noop():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_settings (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "parent_id INTEGER, name TEXT)"
            )
        )
        conn.commit()
        ensure_world_drop_is_deleted(conn)  # no-op 不抛错
        assert "is_deleted" not in _cols(conn, "world_settings")


def test_ensure_character_drop_is_deleted():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE characters (id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, "
                "is_deleted INTEGER DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE character_groups (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "name TEXT, "
                "is_deleted INTEGER DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE character_relations (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "from_character_id INTEGER, to_character_id INTEGER, relation_type TEXT, "
                "is_deleted INTEGER DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO characters (project_id, name, is_deleted) "
                "VALUES (1, 'del', 1), (1, 'live', 0)"
            )
        )
        conn.commit()
        ensure_character_drop_is_deleted(conn)
        conn.commit()
        assert "is_deleted" not in _cols(conn, "characters")
        assert "is_deleted" not in _cols(conn, "character_groups")
        assert "is_deleted" not in _cols(conn, "character_relations")
        assert _names(conn, "characters") == [("live",)]


def test_ensure_outline_drop_is_deleted():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        for table in ("outlines", "plot_points", "story_arcs"):
            conn.execute(
                text(
                    f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, "
                    "is_deleted INTEGER DEFAULT 0)"
                )
            )
        conn.execute(
            text(
                "INSERT INTO outlines (project_id, name, is_deleted) "
                "VALUES (1, 'del', 1), (1, 'live', 0)"
            )
        )
        conn.commit()
        ensure_outline_drop_is_deleted(conn)
        conn.commit()
        assert "is_deleted" not in _cols(conn, "outlines")
        assert "is_deleted" not in _cols(conn, "plot_points")
        assert "is_deleted" not in _cols(conn, "story_arcs")
        assert _names(conn, "outlines") == [("live",)]


def test_ensure_timeline_drop_is_deleted():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE timeline_events (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "name TEXT, "
                "is_deleted INTEGER DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO timeline_events (project_id, name, is_deleted) "
                "VALUES (1, 'del', 1), (1, 'live', 0)"
            )
        )
        conn.commit()
        ensure_timeline_drop_is_deleted(conn)
        conn.commit()
        assert "is_deleted" not in _cols(conn, "timeline_events")
        assert _names(conn, "timeline_events") == [("live",)]


def test_ensure_foreshadowing_drop_is_deleted():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE foreshadowings (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "title TEXT, "
                "is_deleted INTEGER DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO foreshadowings (project_id, title, is_deleted) "
                "VALUES (1, 'del', 1), (1, 'live', 0)"
            )
        )
        conn.commit()
        ensure_foreshadowing_drop_is_deleted(conn)
        conn.commit()
        assert "is_deleted" not in _cols(conn, "foreshadowings")
        titles = list(
            conn.execute(text("SELECT title FROM foreshadowings ORDER BY title")).fetchall()
        )
        assert titles == [("live",)]
