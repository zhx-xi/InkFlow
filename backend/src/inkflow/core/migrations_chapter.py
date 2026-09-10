"""#1017：chapters 表章级写作要求列迁移（幂等）。

从 ``core/database.py`` 抽出（该文件已达 900 行护栏上限，按 check_file_length.py
「超限文件优先拆分」规则独立成模块）；``core/database.py`` 保留同名 re-export，
既有 `from inkflow.core.database import ensure_chapters_writing_requirements_column`
的调用方（api/app.py 与测试）无需改动。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_chapters_writing_requirements_column(conn: Connection) -> None:
    """#1017：为既有库 chapters 补 writing_requirements 列（幂等，conn.run_sync 调用）.

    镜像 ensure_characters_brief_column：PRAGMA 检缺列才 ALTER；表不存在（全新环境）
    → no-op，等 create_all 建新表（ORM 已含该列）。存量行补列后为 NULL = 继承
    项目级 config.writing_style（零行为变化，spec f2-chapter §2.3）。
    """
    cols = conn.execute(text("PRAGMA table_info(chapters)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if "writing_requirements" not in names:
        conn.execute(text("ALTER TABLE chapters ADD COLUMN writing_requirements TEXT"))
