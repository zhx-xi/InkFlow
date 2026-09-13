"""#1156：存量库遗留 ``projects.genre`` 列迁移（幂等）。

从 ``core/database.py`` 抽出（该文件贴 900 行护栏上限，按 check_file_length.py
「超限文件优先拆分」规则独立成模块，镜像 #1017 的 ``migrations_chapter.py``）；
``core/database.py`` 保留同名 re-export，既有
``from inkflow.core.database import ensure_projects_drop_legacy_genre_column``
的调用方（``api/app.py`` 与测试）无需改动。

背景：``#595``「删 genre 枚举迁 tags」把 ``genre`` 从 ORM 移除，但未迁移存量库——
遗留 ``genre`` 是无 SQL DEFAULT 的 ``NOT NULL`` 列，而 ORM INSERT 不再写该列
→ ``IntegrityError(NOT NULL constraint failed: projects.genre)`` → 建项目 HTTP 500。
全新库（``create_all`` 按当前 ORM 建表）本无该列，故 CI 绿 / 存量库红。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_projects_drop_legacy_genre_column(conn: Connection) -> None:
    """#1156：为存量库摘除遗留 ``projects.genre`` 列（幂等，conn.run_sync 调用）.

    镜像 ``ensure_world_drop_is_deleted``：PRAGMA 检列才 DROP；表不存在 / 列已不存在
    → no-op（全新库 ``create_all`` 建的表本无该列）。摘列同时消除写入约束与死列；
    存量行数据（name/tags/config 等）原样保留。
    """
    cols = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
    names = {row[1] for row in cols}
    if not names or "genre" not in names:
        return
    conn.execute(text("ALTER TABLE projects DROP COLUMN genre"))
