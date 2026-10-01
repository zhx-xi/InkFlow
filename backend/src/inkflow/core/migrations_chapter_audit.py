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
