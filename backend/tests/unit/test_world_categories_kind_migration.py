"""#699 世界观分类 kind 列迁移函数契约测试（ensure_world_categories_kind_column）.

覆盖 core/database.py 的 ensure_world_categories_kind_column 三形态：旧库补列 /
新库 no-op / 无表 no-op。真 SQLite 同步轨（in-memory）。

依据: specs/f10-world-service/spec.md v1.2 §2.6（world_categories 表）+#699（加 kind 列）.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def test_ensure_world_categories_kind_old_db_adds_column() -> None:
    """旧库（world_categories 存在但无 kind 列）→ ALTER 补列（默认 'geo'）."""
    from inkflow.core.database import ensure_world_categories_kind_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_categories (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "name TEXT, created_at TEXT, updated_at TEXT)"
            )
        )
        conn.execute(text("INSERT INTO world_categories (project_id, name) VALUES (1, '势力')"))
        conn.commit()

        ensure_world_categories_kind_column(conn)
        conn.commit()

        assert "kind" in _cols(conn, "world_categories")
        # 存量行默认 geo
        val = conn.execute(text("SELECT kind FROM world_categories")).scalar_one()
        assert val == "geo"


def test_ensure_world_categories_kind_fresh_schema_noop() -> None:
    """新库（world_categories 已含 kind 列）→ no-op 不抛错."""
    from inkflow.core.database import ensure_world_categories_kind_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_categories (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "name TEXT, kind TEXT NOT NULL DEFAULT 'geo', created_at TEXT, updated_at TEXT)"
            )
        )
        conn.commit()

        ensure_world_categories_kind_column(conn)  # no-op 不抛错
        assert "kind" in _cols(conn, "world_categories")


def test_ensure_world_categories_kind_missing_table_noop() -> None:
    """无 world_categories 表 → no-op 不抛错（等 create_all 建新表自动含列）."""
    from inkflow.core.database import ensure_world_categories_kind_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        ensure_world_categories_kind_column(conn)  # no-op 不抛错
