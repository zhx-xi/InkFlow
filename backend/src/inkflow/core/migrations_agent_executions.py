"""agent_executions 表的存量库补列迁移（从 core/database.py 抽出，900 行护栏）。

本族 4 个函数形态完全一致（PRAGMA 检缺列才 ALTER；表不存在 → no-op，
等 `create_all` 建新表），故集中一处便于核对。`core/database.py` 保留同名
re-export，既有 `from inkflow.core.database import ensure_...` 调用方无需改动。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def _ensure_agent_executions_column(conn: Connection, column: str, ddl: str) -> None:
    """为存量库 agent_executions 补列（幂等；表不存在 → no-op）。

    Args:
        conn: 同步 SQLAlchemy 连接（`conn.run_sync` 内调用）.
        column: 目标列名.
        ddl: 列定义（追加在 ``ADD COLUMN`` 之后）.
    """
    cols = conn.execute(text("PRAGMA table_info(agent_executions)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if column not in names:
        conn.execute(text(f"ALTER TABLE agent_executions ADD COLUMN {column} {ddl}"))


def ensure_agent_executions_hitl_payload_column(conn: Connection) -> None:
    """#161：为既有库 agent_executions 补 hitl_payload 列（幂等，配合 conn.run_sync 调用）."""
    _ensure_agent_executions_column(conn, "hitl_payload", "TEXT")


def ensure_agent_executions_relations_column(conn: Connection) -> None:
    """F46 #270：为既有库 agent_executions 补 relations 列（幂等）."""
    _ensure_agent_executions_column(conn, "relations", "TEXT")


def ensure_agent_executions_trace_column(conn: Connection) -> None:
    """F47 #379：为存量库 agent_executions 补 trace 列（幂等）."""
    _ensure_agent_executions_column(conn, "trace", "TEXT")


def ensure_agent_executions_thread_id_column(conn: Connection) -> None:
    """F44 阶段 4（#338）：为存量库 agent_executions 补 thread_id 列（幂等）."""
    _ensure_agent_executions_column(conn, "thread_id", "VARCHAR(64)")
