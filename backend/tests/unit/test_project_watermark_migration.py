"""#617 F49 Q1=A 活跃基准迁移函数契约测试（ensure_project_watermark_column）.

覆盖 core/database.py 的 ensure_project_watermark_column 三形态：旧库补列 /
新库 no-op / 无表 no-op。真 SQLite 同步轨（in-memory）。

依据: specs/f49-memory-decay/spec.md §2.1/§14 Q1=A（projects 表新列）.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


# ── ensure_project_watermark_column 三形态 ──────────────────────────────


def test_ensure_project_watermark_old_db_adds_column() -> None:
    """旧库（projects 表存在但无 active_watermark 列）→ ALTER 补列（默认 0.0）."""
    from inkflow.core.database import ensure_project_watermark_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
        )
        conn.execute(text("INSERT INTO projects (name) VALUES ('test')"))
        conn.commit()

        ensure_project_watermark_column(conn)
        conn.commit()

        assert "active_watermark" in _cols(conn, "projects")
        # 存量行默认 0.0（首迁水位=0 初始化，Q1=A 拍板）
        val = conn.execute(text("SELECT active_watermark FROM projects")).scalar_one()
        assert val == 0.0


def test_ensure_project_watermark_fresh_schema_noop() -> None:
    """新库（projects 表已含 active_watermark 列）→ no-op 不抛错."""
    from inkflow.core.database import ensure_project_watermark_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, "
                "active_watermark FLOAT NOT NULL DEFAULT 0.0, "
                "created_at TEXT, updated_at TEXT)"
            )
        )
        conn.commit()

        ensure_project_watermark_column(conn)  # no-op 不抛错
        assert "active_watermark" in _cols(conn, "projects")


def test_ensure_project_watermark_missing_table_noop() -> None:
    """无 projects 表 → no-op 不抛错（等 create_all 建新表自动含列）."""
    from inkflow.core.database import ensure_project_watermark_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        ensure_project_watermark_column(conn)  # no-op 不抛错
