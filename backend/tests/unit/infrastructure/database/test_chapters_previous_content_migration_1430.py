"""#1430：chapters.previous_content 列迁移（A2 旧稿备份落点）契约（RED→GREEN）。

背景：#1430 = #1288 第 2 项「方案 A」（`book run --force` 覆盖已有正文）。
覆盖即数据丢失 → 旧稿必须落专用备份落点（用户 2026-10-01 拍板 = **A2**：
`chapters` 新增 `previous_content`（Text, nullable），抄 `outline_service` 的
`extra["replace_snapshot"]` 快照先例 + 仓库既有 `LenientJSON` 列先例，不新造表）。

本测试钉住 ``ensure_chapters_previous_content_column`` 四形态：

- 旧库（chapters 存在但无 previous_content + 2 行存量正文）→ ALTER 补列，
  ⚠️ 且**存量 2 行的 previous_content 必须仍为 NULL**（零回填：存量行没有
  「被本次覆盖掉的那一版」这个事实，凭空把 content 抄进 previous_content
  会伪造出一份并不存在的旧稿）
- 幂等：连续两次调用不抛错、列不重复、存量行不被改写
- 新库（create_all 已含列）→ no-op，列集不变
- 表不存在（全新环境）→ no-op 且不隐式建表

RED 形态：``ensure_chapters_previous_content_column`` 不存在 → 顶部 import
收集期 ImportError（cannot import name，exit 2）。

依据: ADR-054（create_all + ensure_* 幂等迁移）+ issue #1430 实现清单第 1 条。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from inkflow.core.database import ensure_chapters_previous_content_column

# 旧库形态：#1430 之前（无 previous_content 列），携带 2 行有正文的存量章
# （备份落点的真实存量面：两章都已有正文）。
OLD_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL
);
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
);
INSERT INTO projects (name) VALUES ('旧项目');
INSERT INTO chapters (project_id, title, content, status)
VALUES
    (1, '第一章 起', '旧正文甲', 'final'),
    (1, '第二章 承', '旧正文乙', 'draft');
"""

# 新库形态：create_all 已按 ORM 建出带 previous_content 的表。
NEW_SCHEMA = OLD_SCHEMA.replace(
    "    content TEXT NOT NULL DEFAULT '',\n",
    "    content TEXT NOT NULL DEFAULT '',\n    previous_content TEXT,\n",
)


def _columns(conn, table: str) -> set[str]:
    """PRAGMA table_info 列名集合（镜像既有迁移契约测试助手）。"""
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _tables(conn) -> set[str]:
    """sqlite_master 全部表名。"""
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {row[0] for row in rows}


def _run(conn, schema: str) -> None:
    """按分号切分逐条执行建库脚本（镜像 test_foreshadowings_first_chapter_migration）。"""
    for stmt in schema.strip().split(";"):
        if stmt.strip():
            conn.execute(text(stmt))


def test_old_db_adds_column_and_keeps_legacy_rows_null(tmp_path):
    """旧库：补 previous_content 列；存量行保持 NULL（零回填）。"""
    db = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _run(conn, OLD_SCHEMA)
    with engine.connect() as conn:
        assert "previous_content" not in _columns(conn, "chapters")

        ensure_chapters_previous_content_column(conn)
        assert "previous_content" in _columns(conn, "chapters")

        # 零回填：存量 2 行仍为 NULL（不把当前 content 抄成「上一稿」）
        rows = conn.execute(text("SELECT previous_content FROM chapters ORDER BY id")).fetchall()
        assert [r[0] for r in rows] == [None, None]

        # 存量正文原样保留（备份是新列，不改既有数据）
        contents = conn.execute(text("SELECT content FROM chapters ORDER BY id")).fetchall()
        assert [r[0] for r in contents] == ["旧正文甲", "旧正文乙"]
    engine.dispose()


def test_old_db_idempotent_second_call(tmp_path):
    """幂等：连续两次调用不抛错、列不重复、存量行仍 NULL。"""
    db = tmp_path / "idem.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _run(conn, OLD_SCHEMA)
    with engine.connect() as conn:
        ensure_chapters_previous_content_column(conn)
        after_first = _columns(conn, "chapters")
        ensure_chapters_previous_content_column(conn)
        assert _columns(conn, "chapters") == after_first
        rows = conn.execute(text("SELECT previous_content FROM chapters")).fetchall()
        assert [r[0] for r in rows] == [None, None]
    engine.dispose()


def test_new_db_noop(tmp_path):
    """新库：create_all 已含列 → no-op，列集不变。"""
    db = tmp_path / "new.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _run(conn, NEW_SCHEMA)
    with engine.connect() as conn:
        before = _columns(conn, "chapters")
        assert "previous_content" in before

        ensure_chapters_previous_content_column(conn)
        assert _columns(conn, "chapters") == before
    engine.dispose()


def test_missing_table_noop(tmp_path):
    """表不存在（全新环境）→ no-op 不抛错，也不隐式建表（等 create_all）。"""
    db = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        ensure_chapters_previous_content_column(conn)  # 不应抛错
        assert _tables(conn) == set()
    engine.dispose()
