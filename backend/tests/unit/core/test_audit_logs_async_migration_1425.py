"""#1425 RED 契约 —— audit_logs 异步语义三列迁移（run_status / error / content_hash）.

来源: issue #1425「审计异步语义」方案 B（202 + 后台执行 + 轮询）。

契约（GREEN 实现必须满足）:
- 迁移助手 `ensure_audit_logs_async_columns(conn)` 落点
  `inkflow.core.migrations_chapter_audit`（**不经 `inkflow.core.database` re-export**——
  该文件已触 900 行护栏，`api/app.py` 直接导入并 lifespan 接线，同 `ensure_timeline_era_columns`
  #1410 先例；D3 注册集门禁以 `core.database` 命名空间为准，故本迁移不在其中）。
- 三形态（镜像 `ensure_audit_logs_findings_column` 契约）:
  ① 旧库（audit_logs 表在、无新列）→ ALTER 补三列，存量行
     `run_status='completed'`（v1.5 前均为同步执行完成）、`error=''`、`content_hash=''`
  ② 新库（create_all 已含三列）→ no-op 不抛错
  ③ 无 audit_logs 表 → no-op 不抛错（等 create_all 建新表）
- ORM 三列须为**软列**（带 `server_default`）——旧库 raw INSERT / 旧行读取不炸
  （#1006 漂移门禁口径：Python-side default 不算）。

依据: issue #1425 + specs/f34-chapter-audit/spec.md §2.3/§7 E23/§8.1（v1.5 演进留痕）。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from inkflow.core.migrations_chapter_audit import ensure_audit_logs_async_columns


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _new_engine():
    """独立 in-memory 同步 SQLite 引擎（每用例一个全新库）."""
    return create_engine("sqlite:///:memory:")


def test_migration_helper_lives_in_migrations_module() -> None:
    """助手模块归属：`inkflow.core.migrations*` 前缀（D3 wiring 门禁注册集口径）."""
    assert callable(ensure_audit_logs_async_columns)
    assert ensure_audit_logs_async_columns.__module__.startswith("inkflow.core.migrations"), (
        "迁移助手须落在 inkflow.core.migrations* 模块，否则数据库迁移 wiring 门禁"
        f"（test_database_migration_chain.py::test_d3）不设防；实际: "
        f"{ensure_audit_logs_async_columns.__module__}"
    )


def test_orm_declares_async_columns_as_soft_columns() -> None:
    """ORM 三列须带 `server_default`（软列）——旧库升级/raw INSERT 不炸（#1006 门禁）."""
    from inkflow.infrastructure.database.models.audit_log import AuditLogORM

    cols = AuditLogORM.__table__.columns
    for name in ("content_hash", "run_status", "error"):
        assert name in cols, f"audit_logs 须声明 {name} 列"
        assert cols[name].server_default is not None, (
            f"audit_logs.{name} 须带 server_default（软列）——旧库升级后 raw INSERT 不炸"
        )


def test_ensure_audit_logs_async_old_db_adds_columns() -> None:
    """旧库（audit_logs 表存在、无新列）→ ALTER 补三列，存量行取默认值."""
    engine = _new_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE audit_logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, chapter_id INTEGER, "
                "chapter_title TEXT, status TEXT, severity_summary TEXT, summary TEXT, "
                "degraded BOOLEAN DEFAULT 0, note TEXT, created_at DATETIME, "
                "confirmed_at DATETIME, findings TEXT NOT NULL DEFAULT '[]')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO audit_logs (project_id, chapter_id, chapter_title, status, "
                "severity_summary) VALUES (1, 2, '第 3 章 龙的苏醒', 'pending', "
                "'2 error, 4 warnings, 2 info')"
            )
        )
        conn.commit()
        assert "run_status" not in _cols(conn, "audit_logs")

        ensure_audit_logs_async_columns(conn)
        conn.commit()

        names = _cols(conn, "audit_logs")
        assert {"content_hash", "run_status", "error"} <= names
        row = conn.execute(text("SELECT content_hash, run_status, error FROM audit_logs")).one()
        assert row[0] == "", f"存量行 content_hash 默认应为空串，实际: {row[0]!r}"
        assert row[1] == "completed", f"存量行 run_status 默认应为 completed，实际: {row[1]!r}"
        assert row[2] == "", f"存量行 error 默认应为空串，实际: {row[2]!r}"
        # 既有字段零变化
        assert (
            conn.execute(text("SELECT severity_summary FROM audit_logs")).scalar_one()
            == "2 error, 4 warnings, 2 info"
        )


def test_ensure_audit_logs_async_idempotent() -> None:
    """同一库二次调用 → no-op（幂等，重复启动不抛错）."""
    engine = _new_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, project_id INTEGER)"))
        conn.commit()

        ensure_audit_logs_async_columns(conn)
        conn.commit()
        ensure_audit_logs_async_columns(conn)
        conn.commit()

        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(audit_logs)")).fetchall()]
        for name in ("content_hash", "run_status", "error"):
            assert cols.count(name) == 1


def test_ensure_audit_logs_async_fresh_schema_noop() -> None:
    """新库（audit_logs 已含三列）→ no-op 不抛错."""
    engine = _new_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "project_id INTEGER, content_hash VARCHAR(64) NOT NULL DEFAULT '', "
                "run_status VARCHAR(10) NOT NULL DEFAULT 'completed', "
                "error TEXT NOT NULL DEFAULT '')"
            )
        )
        conn.commit()

        ensure_audit_logs_async_columns(conn)
        conn.commit()

        assert {"content_hash", "run_status", "error"} <= _cols(conn, "audit_logs")


def test_ensure_audit_logs_async_missing_table_noop() -> None:
    """无 audit_logs 表 → no-op 不抛错（等 create_all 建新表自动含列）."""
    engine = _new_engine()
    with engine.connect() as conn:
        ensure_audit_logs_async_columns(conn)
        conn.commit()
        assert _cols(conn, "audit_logs") == set()
