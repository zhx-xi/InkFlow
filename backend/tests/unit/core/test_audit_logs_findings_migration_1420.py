"""#1420 RED 契约 —— audit_logs.findings 列迁移（方案 2：findings 落库 + 读口）.

来源: issue #1420「客户端超时后审计明细不可恢复」。
实际采用方案（报告口径）: 方案 2（findings 落 JSON 列 + 开读口）+ 方案 1（文案对齐）。

契约（GREEN 实现必须满足）:
- 迁移助手 `ensure_audit_logs_findings_column(conn)` 落点
  `inkflow.core.migrations_chapter_audit`，并从 `inkflow.core.database` re-export
  （迁移 wiring 门禁按 `inkflow.core.migrations` 前缀纳入注册集）。
- 三形态（镜像 ensure_project_watermark_column 契约）:
  ① 旧库（audit_logs 表在、无 findings 列）→ ALTER 补列，存量行默认 '[]'
  ② 新库（create_all 已含 findings 列）→ no-op 不抛错
  ③ 无 audit_logs 表 → no-op 不抛错（等 create_all 建新表）
- 列口径镜像既有 JSON 列迁移（TEXT + NOT NULL DEFAULT '[]'）——
  `LenientJSON` 读回 []，不因空串/旧行崩溃。

依据: issue #1420 + specs/f34-chapter-audit/spec.md §2.3/§8.3（v1.4 演进留痕）。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _new_engine():
    """独立 in-memory 同步 SQLite 引擎（每用例一个全新库）."""
    return create_engine("sqlite:///:memory:")


def test_migration_helper_lives_in_migrations_module() -> None:
    """助手模块归属：`inkflow.core.migrations*` 前缀（D3 wiring 门禁注册集口径）."""
    from inkflow.core.database import ensure_audit_logs_findings_column

    assert callable(ensure_audit_logs_findings_column)
    assert ensure_audit_logs_findings_column.__module__.startswith("inkflow.core.migrations"), (
        "迁移助手须落在 inkflow.core.migrations* 模块，否则数据库迁移 wiring 门禁"
        f"（test_database_migration_chain.py::test_d3）不设防；实际: "
        f"{ensure_audit_logs_findings_column.__module__}"
    )


def test_ensure_audit_logs_findings_old_db_adds_column() -> None:
    """旧库（audit_logs 表存在、无 findings 列）→ ALTER 补列，存量行默认 '[]'."""
    from inkflow.core.database import ensure_audit_logs_findings_column

    engine = _new_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE audit_logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, chapter_id INTEGER, "
                "chapter_title TEXT, status TEXT, severity_summary TEXT, summary TEXT, "
                "degraded BOOLEAN DEFAULT 0, note TEXT, created_at DATETIME, confirmed_at DATETIME)"
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
        assert "findings" not in _cols(conn, "audit_logs")

        ensure_audit_logs_findings_column(conn)
        conn.commit()

        assert "findings" in _cols(conn, "audit_logs")
        # 存量行补列后为 '[]'（空数组 JSON → LenientJSON 读回 []，不是 NULL）
        value = conn.execute(text("SELECT findings FROM audit_logs")).scalar_one()
        assert value == "[]", f"存量行 findings 默认值应为 '[]'，实际: {value!r}"
        # 存量摘要字段零变化（Q1=C 向后兼容）
        summary = conn.execute(text("SELECT severity_summary FROM audit_logs")).scalar_one()
        assert summary == "2 error, 4 warnings, 2 info"


def test_ensure_audit_logs_findings_idempotent() -> None:
    """同一库二次调用 → no-op（幂等，重复启动不抛错）."""
    from inkflow.core.database import ensure_audit_logs_findings_column

    engine = _new_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, project_id INTEGER)"))
        conn.commit()

        ensure_audit_logs_findings_column(conn)
        conn.commit()
        ensure_audit_logs_findings_column(conn)
        conn.commit()

        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(audit_logs)")).fetchall()]
        assert cols.count("findings") == 1


def test_ensure_audit_logs_findings_fresh_schema_noop() -> None:
    """新库（audit_logs 已含 findings 列）→ no-op 不抛错."""
    from inkflow.core.database import ensure_audit_logs_findings_column

    engine = _new_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "project_id INTEGER, findings TEXT NOT NULL DEFAULT '[]')"
            )
        )
        conn.commit()

        ensure_audit_logs_findings_column(conn)
        conn.commit()

        assert "findings" in _cols(conn, "audit_logs")


def test_ensure_audit_logs_findings_missing_table_noop() -> None:
    """无 audit_logs 表 → no-op 不抛错（等 create_all 建新表自动含列）."""
    from inkflow.core.database import ensure_audit_logs_findings_column

    engine = _new_engine()
    with engine.connect() as conn:
        ensure_audit_logs_findings_column(conn)
        conn.commit()
        assert _cols(conn, "audit_logs") == set()
