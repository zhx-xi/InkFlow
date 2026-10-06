"""#1410：时间线多纪元正式化 —— 三列 ``era`` / ``era_value`` / ``era_scale`` + 存量回填（幂等）。

背景（ADR-065 §4 / f12 spec v1.4 §2.8 E7/E9）：0.16.0（#1353）用 ``extra.era`` /
``extra.era_value`` 承载纪元轴（零 DDL，弱约束）；0.17.0 把纪元抬到**正式列**，
并把 ``extra`` 里的旧值**一次性投影**进正式列（旧键保留为 v1.3 遗留快照，不再读写）。

本模块放在 sibling 文件而非 ``core/database.py``：后者已顶 900 行护栏
（``ci_cd/check_file_length.py``），镜像 ADR-063 对 ``ensure_project_id_fk_children`` 的处置；
接线守护落在契约测试 ``tests/unit/core/test_timeline_era_migration_1410.py``（AST 提取）。

设计要点（镜像 #1323 的 ``ensure_timeline_composite_positions``）：
- 表不存在（全新环境）→ no-op，等 ``create_all`` 建表（ORM 已含三列）。
- ``ADD COLUMN`` 逐列探测（``PRAGMA table_info``）→ 三形态（空表 / 有表缺列 / 有表有列）幂等。
- ``era_scale`` 由 ``ADD COLUMN ... DEFAULT 1.0`` 对既有行**自动填充**。
- 存量回填以 ``migration_markers`` 标记键保证**只跑一次**（不回写、不覆盖正式列既有值）。
- 任何异常向上传播（由 lifespan 决定是否兜底）；本函数自身不吞异常。
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from inkflow.domain.models.timeline import ERA_KEY, ERA_VALUE_KEY

logger = logging.getLogger(__name__)

_TABLE = "timeline_events"

_MARKER_TABLE = "migration_markers"
_MARKER_KEY = "timeline_era_backfill_1410"


def _table_exists(conn: Connection, name: str) -> bool:
    """SQLite：查 ``sqlite_master`` 判断表是否存在。"""
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
    ).fetchone()
    return row is not None


def _column_names(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _load_extra(raw: Any) -> dict[str, Any]:
    """容错解析 ``extra`` JSON 列（空串 / 非 JSON / 非对象 → ``{}``）。"""
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _legacy_era_value(data: dict[str, Any]) -> float | None:
    """从遗留 extra 里取有限数值的轴内值；否则 ``None``。"""
    raw = data.get(ERA_VALUE_KEY)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def ensure_timeline_era_columns(conn: Connection) -> None:
    """#1410：为 ``timeline_events`` 补三列并把 ``extra`` 旧承载一次性投影（幂等）。

    Args:
        conn: 同步 SQLAlchemy 连接（``conn.run_sync`` 内调用）.
    """
    if not _table_exists(conn, _TABLE):
        return  # 全新环境 → 等 create_all 建表（ORM 已含三列）

    # ⚠️ 表名保持**字面量**、且 (列名, SQL 定义) 元组置于**函数体内** —— ORM↔迁移
    # 漂移门禁（ci_cd/check_orm_migration_drift.py）按 AST 提取「字面表名的动态
    # ADD COLUMN f-string + 同函数体的 (列名, SQL 定义) 元组」来识别迁移接线；
    # 改用 _TABLE 变量或把元组提到模块级都会让门禁看不见本迁移（假绿面）。
    additions: tuple[tuple[str, str], ...] = (
        ("era", "VARCHAR(50) NOT NULL DEFAULT ''"),
        ("era_value", "FLOAT"),
        ("era_scale", "FLOAT NOT NULL DEFAULT 1.0"),
    )
    names = _column_names(conn, _TABLE)
    for column, ddl in additions:
        if column not in names:
            conn.execute(text(f"ALTER TABLE timeline_events ADD COLUMN {column} {ddl}"))

    # 幂等标记（一次性回填开关）；表不存在则建（#1323 已引入同表）
    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_MARKER_TABLE} "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
    )
    done = conn.execute(
        text(f"SELECT value FROM {_MARKER_TABLE} WHERE key = :k"), {"k": _MARKER_KEY}
    ).fetchone()
    if done is not None:
        return  # 已回填过 → 不再触碰正式列

    rows = conn.execute(text(f"SELECT id, extra FROM {_TABLE}")).fetchall()
    backfilled = 0
    for event_id, raw in rows:
        data = _load_extra(raw)
        era_raw = data.get(ERA_KEY)
        if not isinstance(era_raw, str) or not era_raw.strip():
            continue  # 无纪元键 / 非字符串 / 空白 → 默认轴（保持 era=''）
        result = conn.execute(
            text(
                f"UPDATE {_TABLE} SET era = :e, era_value = :v "
                "WHERE id = :i AND (era IS NULL OR era = '')"
            ),
            {"e": era_raw.strip(), "v": _legacy_era_value(data), "i": event_id},
        )
        backfilled += int(result.rowcount or 0)

    conn.execute(
        text(f"INSERT INTO {_MARKER_TABLE} (key, value) VALUES (:k, :v)"),
        {"k": _MARKER_KEY, "v": "1"},
    )
    logger.info("#1410 多纪元正式化：三列就绪，回填 %d 条事件（extra → 正式列）", backfilled)
