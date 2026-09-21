"""#1323：时间线叙事序一次性回填为合成序（幂等 + 可回滚）。

背景（G4）：``_timeline_extractor`` 曾把 LLM 的**章内序**原样落库，而该序每章从 1 重数
（prompt：「叙事位置 = 事件在本章叙事中出现的先后（从 1 开始）」）→ 跨章必然碰撞。
DB 实测（issue 记录）：215 条事件只有 34 个不同 position 值，1/6/7 各对应 10 条。

本迁移把既有数据重排为**合成序**（与 ``_composite_positions`` 同口径）：
章基址 = 该章之前所有章的事件数累计 + 1，章内按原 narrative_position 升序紧凑重排。
⇒ 迁移后 ``narrative_position`` 全局严格递增、两两不同（跨章碰撞归零），
且**章内相对先后保持不变**（纯重编号，不改任何业务字段）。

可回滚：迁移前把原值快照进 ``timeline_position_backup_1323``（仅当该表不存在时创建，
即首次迁移的「原始」快照不会被后续运行覆盖）。回滚 = 按 event_id 恢复原值。

幂等：以「迁移是否已执行」为开关 —— 迁移后本函数写入固定标记行，
第二次运行直接返回（见 ``_MARKER``）。
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

BACKUP_TABLE = "timeline_position_backup_1323"
"""回滚快照表名（event_id → 迁移前 narrative_position）。"""

_MARKER_KEY = "timeline_composite_backfill_1323"
"""幂等标记键（存于 kv 风格单行表；用常量表 ``migration_markers`` 承载）。"""

_MARKER_TABLE = "migration_markers"


def _table_exists(conn: Connection, name: str) -> bool:
    """SQLite：查 sqlite_master 判断表是否存在。"""
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
    ).fetchone()
    return row is not None


def rollback_timeline_composite_positions(conn: Connection) -> int:
    """#1323：把 ``narrative_position`` 恢复到迁移前的原值。

    Args:
        conn: 同步 SQLAlchemy 连接（``conn.run_sync`` 内调用）.

    Returns:
        恢复的行数；无快照表 → 0（无可回滚，视为未迁移）。
    """
    if not _table_exists(conn, BACKUP_TABLE):
        return 0
    result = conn.execute(
        text(
            f"UPDATE timeline_events SET narrative_position = ("
            f"  SELECT b.narrative_position FROM {BACKUP_TABLE} b "
            f"  WHERE b.event_id = timeline_events.id"
            f") WHERE EXISTS ("
            f"  SELECT 1 FROM {BACKUP_TABLE} b WHERE b.event_id = timeline_events.id"
            f")"
        )
    )
    conn.execute(text(f"DELETE FROM {_MARKER_TABLE} WHERE key = :k"), {"k": _MARKER_KEY})
    return int(result.rowcount or 0)


def ensure_timeline_composite_positions(conn: Connection) -> None:
    """#1323：既有时间线事件叙事序 → 合成序一次性回填（幂等，conn.run_sync 调用）.

    设计要点：
    - 表不存在（全新环境）→ no-op，等 ``create_all`` 建表（新数据天然走合成序）。
    - 幂等：``migration_markers`` 里已有标记 → 直接返回（不重复快照、不重复重排）。
    - 快照只在**首次**运行时写入（``IF NOT EXISTS``）：重复运行不会用已迁移后的值
      覆盖「原始」快照，因此回滚始终能回到迁移前状态。
    - 单事务：任何异常回滚整批，不留半迁移状态。

    Args:
        conn: 同步 SQLAlchemy 连接（``conn.run_sync`` 内调用）.
    """
    if not _table_exists(conn, "timeline_events"):
        return

    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_MARKER_TABLE} ("
            f"  key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
    )
    done = conn.execute(
        text(f"SELECT value FROM {_MARKER_TABLE} WHERE key = :k"), {"k": _MARKER_KEY}
    ).fetchone()
    if done is not None:
        return  # 幂等：已迁移

    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} ("
            f"  event_id INTEGER PRIMARY KEY, narrative_position INTEGER NOT NULL)"
        )
    )

    # ① 首次快照（IF NOT EXISTS 语义：表刚建 or 之前建过 —— 只补缺失行，不覆盖）
    conn.execute(
        text(
            f"INSERT OR IGNORE INTO {BACKUP_TABLE} (event_id, narrative_position) "
            f"SELECT id, narrative_position FROM timeline_events"
        )
    )

    # ② 逐项目、逐章重排为合成序（章内按原 position 升序紧凑重排，章间累计偏移）
    rows = conn.execute(
        text(
            "SELECT id, project_id, source_chapter_id, narrative_position "
            "FROM timeline_events ORDER BY project_id, "
            "  CASE WHEN source_chapter_id IS NULL THEN 1 ELSE 0 END, "
            "  source_chapter_id, narrative_position, id"
        )
    ).fetchall()
    if not rows:
        conn.execute(
            text(f"INSERT INTO {_MARKER_TABLE} (key, value) VALUES (:k, :v)"),
            {"k": _MARKER_KEY, "v": "1"},
        )
        return

    # 按 (project, chapter) 分组保序；**offset 必须逐项目重置**（叙事序是项目内序号）
    groups: list[tuple[object, list[int]]] = []
    last_key: tuple[object, object] | None = None
    for event_id, project_id, chapter_id, _pos in rows:
        key = (project_id, chapter_id)
        if key != last_key:
            groups.append((project_id, []))
            last_key = key
        # 每个分组记住所属项目
        groups[-1] = (project_id, groups[-1][1] + [event_id])

    updates: list[tuple[int, int]] = []
    current_project: object = None
    offset = 0
    for project_id, event_ids in groups:
        if project_id != current_project:
            current_project = project_id
            offset = 0  # 项目内重新从 0 起算
        for idx, event_id in enumerate(event_ids, start=1):
            updates.append((offset + idx, event_id))
        offset += len(event_ids)

    for position, event_id in updates:
        conn.execute(
            text("UPDATE timeline_events SET narrative_position = :p WHERE id = :i"),
            {"p": position, "i": event_id},
        )

    conn.execute(
        text(f"INSERT INTO {_MARKER_TABLE} (key, value) VALUES (:k, :v)"),
        {"k": _MARKER_KEY, "v": "1"},
    )
    logger.info("#1323 时间线叙事序回填完成：%d 条重排为合成序", len(updates))
