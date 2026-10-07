"""#1439：writing_plans.tasklist 列迁移（supervisor 任务清单落库）契约。

背景：#1439 = supervisor 产出任务清单（拍板 2026-10-06 与 supervisor 合并）。
落点 = ``writing_plans`` 新增 ``tasklist`` JSON 列（NOT NULL + SQL DEFAULT '[]'），
走本仓 ``ensure_*`` 幂等迁移三件套（ADR-054：create_all + ensure_* 幂等补列）。

本测试钉住 ``ensure_writing_plan_tasklist_column`` 三形态：

- 旧库（writing_plans 存在但无 tasklist + 1 行存量）→ ALTER 补列，存量行取 SQL
  DEFAULT ``'[]'``（**不隐式建表、不改既有列**）
- 幂等：连续两次调用不抛错、列不重复、存量行不被改写
- 新库（create_all 已含列）→ no-op，列集不变
- 表不存在（全新环境）→ no-op 且不隐式建表

RED 形态：``inkflow.core.migrations_writing_plan`` 不存在 → 函数体惰性 import
ImportError → 各用例 FAIL（module 缺失）。

依据: ADR-054（create_all + ensure_* 幂等迁移）+ issue #1439。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

# 旧库形态：#1439 之前（无 tasklist 列），携带 1 行存量计划。
OLD_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL
);
CREATE TABLE writing_plans (
    id VARCHAR(36) PRIMARY KEY,
    project_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'drafting'
);
INSERT INTO projects (name) VALUES ('旧项目');
INSERT INTO writing_plans (id, project_id, title, status)
VALUES ('01920000-0000-7000-8000-00000000f143', 1, '旧计划', 'running');
"""

# 新库形态：create_all 已按 ORM 建出带 tasklist 的表。
NEW_SCHEMA = OLD_SCHEMA.replace(
    "    status VARCHAR(30) NOT NULL DEFAULT 'drafting'\n",
    "    status VARCHAR(30) NOT NULL DEFAULT 'drafting',\n"
    "    tasklist JSON NOT NULL DEFAULT '[]'\n",
)


def _ensure(conn) -> None:
    """惰性 import 目标迁移函数（RED 期模块不存在 → 用例 FAIL）。"""
    from inkflow.core.migrations_writing_plan import ensure_writing_plan_tasklist_column

    ensure_writing_plan_tasklist_column(conn)


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _tables(conn) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {row[0] for row in rows}


def _run(conn, schema: str) -> None:
    for stmt in schema.strip().split(";"):
        if stmt.strip():
            conn.execute(text(stmt))


def test_old_db_adds_tasklist_column_with_empty_default(tmp_path):
    """旧库：补 tasklist 列；存量行取 SQL DEFAULT '[]'（零回填成假清单）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        _run(conn, OLD_SCHEMA)
    with engine.connect() as conn:
        assert "tasklist" not in _columns(conn, "writing_plans")

        _ensure(conn)
        assert "tasklist" in _columns(conn, "writing_plans")

        rows = conn.execute(text("SELECT tasklist FROM writing_plans")).fetchall()
        assert [r[0] for r in rows] == ["[]"]
    engine.dispose()


def test_old_db_idempotent_second_call(tmp_path):
    """幂等：连续两次调用不抛错、列不重复、存量行仍 '[]'。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'idem.db'}")
    with engine.begin() as conn:
        _run(conn, OLD_SCHEMA)
    with engine.connect() as conn:
        _ensure(conn)
        after_first = _columns(conn, "writing_plans")
        _ensure(conn)
        assert _columns(conn, "writing_plans") == after_first
        rows = conn.execute(text("SELECT tasklist FROM writing_plans")).fetchall()
        assert [r[0] for r in rows] == ["[]"]
    engine.dispose()


def test_new_db_noop(tmp_path):
    """新库：create_all 已含列 → no-op，列集不变。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    with engine.begin() as conn:
        _run(conn, NEW_SCHEMA)
    with engine.connect() as conn:
        before = _columns(conn, "writing_plans")
        assert "tasklist" in before

        _ensure(conn)
        assert _columns(conn, "writing_plans") == before
    engine.dispose()


def test_missing_table_noop(tmp_path):
    """表不存在（全新环境）→ no-op 不抛错，也不隐式建表（等 create_all）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with engine.connect() as conn:
        _ensure(conn)
        assert _tables(conn) == set()
    engine.dispose()
