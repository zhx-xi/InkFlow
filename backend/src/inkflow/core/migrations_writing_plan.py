"""#1439：writing_plans 表 tasklist 列迁移（幂等）.

从 ``core/database.py`` 抽出（该文件已达 900 行护栏上限，按 check_file_length.py
「超限文件优先拆分」规则独立成模块）；沿用 ADR-054 的 ``create_all`` + ``ensure_*``
幂等补列先例：PRAGMA 检缺列才 ALTER；表不存在（全新环境）→ no-op，等 create_all 建新表。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_writing_plan_tasklist_column(conn: Connection) -> None:
    """#1439：为存量库 writing_plans 补 tasklist 列（幂等，conn.run_sync 调用）.

    镜像 ensure_writing_plan_progress_reason_column：PRAGMA 检缺列才 ALTER；表不存在
    （全新环境）→ no-op，等 create_all 建新表（ORM 已含列）。**零回填**：存量行取
    SQL DEFAULT '[]'（不凭空造出假清单，与 #1430「零回填」同族）。
    """
    cols = conn.execute(text("PRAGMA table_info(writing_plans)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if "tasklist" not in names:
        conn.execute(
            text("ALTER TABLE writing_plans ADD COLUMN tasklist JSON NOT NULL DEFAULT '[]'")
        )
