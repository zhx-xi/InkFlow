"""#1420：audit_logs 表 findings 列迁移（幂等）。

语义镜像 migrations_chapter.py / migrations_agent_executions.py：PRAGMA 检缺列才 ALTER，
表不存在（全新环境）→ no-op，等 ``create_all`` 建新表（ORM 已含该列）。
``core/database.py`` 保留同名 re-export，既有调用方无需改动。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_audit_logs_findings_column(conn: Connection) -> None:
    """#1420：为既有库 audit_logs 补 findings 列（幂等，conn.run_sync 调用）.

    存量行补列后为 '[]'（空 findings 数组）。#1420 演进：审计 findings 由「仅响应体」
    改为落库快照，客户端超时后可按审计记录 ID 取回（GET /api/v1/audit-logs/{log_id}）。
    """
    cols = conn.execute(text("PRAGMA table_info(audit_logs)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if "findings" not in names:
        conn.execute(text("ALTER TABLE audit_logs ADD COLUMN findings TEXT NOT NULL DEFAULT '[]'"))


_ASYNC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("content_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("run_status", "VARCHAR(10) NOT NULL DEFAULT 'completed'"),
    ("error", "TEXT NOT NULL DEFAULT ''"),
)
"""#1425 异步语义三列（列名, SQL 定义）—— 定义与 ORM `server_default` 一致。"""


def ensure_audit_logs_async_columns(conn: Connection) -> None:
    """#1425：为既有库 audit_logs 补异步语义三列（幂等，conn.run_sync 调用）.

    - `content_hash`：章节正文 sha256 指纹（幂等去重键；旧行默认空串 = 永不命中）；
    - `run_status`：任务执行态（默认 `'completed'`——v1.5 前均为同步执行完成，
      历史行读回语义正确）；
    - `error`：失败原因（默认空串）。

    表不存在（全新环境）→ no-op，等 ``create_all`` 建新表（ORM 已含三列）。
    """
    cols = conn.execute(text("PRAGMA table_info(audit_logs)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    for column, ddl in _ASYNC_COLUMNS:
        if column not in names:
            conn.execute(text(f"ALTER TABLE audit_logs ADD COLUMN {column} {ddl}"))
