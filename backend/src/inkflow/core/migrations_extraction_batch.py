"""#1485：为存量库补 batch_id 列（幂等，conn.run_sync 调用）.

抽取独立模块的原因同 ``migrations_chapter``：``core/database.py`` 已顶 900 行
护栏上限，按 check_file_length.py「超限文件优先拆分」规则独立成模块，并直接由
``api/app.py`` 的 lifespan 迁移组导入（不经 database.py re-export）。

DDL 口径：列定义 VARCHAR(64)（ORM 侧 String(64), nullable=True）；**零回填**——
存量行没有「哪一批提取建了这条」这个事实，凭空造批次会让回滚删掉历史条目。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_world_settings_batch_id_column(conn: Connection) -> None:
    """#1485：为既有库 world_settings 补 batch_id 列（幂等，conn.run_sync 调用）.

    镜像 ``migrations_chapter.ensure_chapters_writing_requirements_column``：
    PRAGMA 检缺列才 ALTER；表不存在（全新环境 create_all 尚未跑）→ no-op，
    等 create_all 建新表（ORM 已含该列）。
    """
    cols = conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if "batch_id" not in names:
        conn.execute(text("ALTER TABLE world_settings ADD COLUMN batch_id VARCHAR(64)"))


def ensure_characters_batch_id_column(conn: Connection) -> None:
    """#1485：为既有库 characters 补 batch_id 列（幂等，conn.run_sync 调用）.

    与 ``ensure_world_settings_batch_id_column`` 同构（表名 / 列名不同）。
    """
    cols = conn.execute(text("PRAGMA table_info(characters)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if "batch_id" not in names:
        conn.execute(text("ALTER TABLE characters ADD COLUMN batch_id VARCHAR(64)"))
