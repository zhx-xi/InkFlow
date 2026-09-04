"""SQLiteSearchRepository 真 SQLite 内存 FTS5 集成测试（F22 RED，spec §9.1「真库」）.

被测模块 ``inkflow.infrastructure.database.repositories.search_repo`` 尚未实现
（RED 阶段）——顶部 import 首报 ``No module named
'inkflow.infrastructure.database.repositories.search_repo'``，收集期整文件失败
（collected 0 items + errors）为预期终态；SearchDocument / SearchHit /
SearchEntityType 在 helper/用例体内惰性 import（核心规则 1c：收集错误只报主契约模块）。

==================== 设计假设（docstring 即契约） ====================

1. 模块路径与构造::

       from inkflow.infrastructure.database.repositories.search_repo import (
           SQLiteSearchRepository,
       )
       SQLiteSearchRepository(session: AsyncSession)

   全部操作走原生 SQL（sqlalchemy.text），不建 ORM 映射（spec §8.2，F15 audit_repo 同款）。

2. 建表（ensure_index()，幂等，spec §2.4）::

       CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
           title, body, entity_type UNINDEXED, entity_id UNINDEXED, project_id UNINDEXED)
       CREATE TABLE IF NOT EXISTS search_meta (key TEXT PRIMARY KEY, value TEXT)

   不依赖 Base.metadata.create_all（FTS5 虚拟表不是 SQLAlchemy 映射表）。
   rowid 自增无业务意义；entity_id/project_id 存 int（陷阱 18：uuid.int 跨实体引用）。

3. is_stale(tables: list[str]) -> bool（父侧裁定 2026-08-09 签名，修正 spec §8.2 草稿）:

   - search_meta 无 last_rebuilt_at → True
   - 对每张表 ``SELECT max(updated_at) FROM <table>``（表名来自参数，实现内部拼接）:
     任一 max(updated_at) > last_rebuilt_at → True；否则 False
   - 表空（max 为 NULL）→ 不判脏；比较前两侧归一化为 UTC aware
     （SQLite 读回的 naive datetime 按 UTC 处理）
   - last_rebuilt_at 写入格式: ``datetime.now(UTC).isoformat()``

4. rebuild(documents: Iterable[SearchDocument]) -> None:

   DELETE FROM search_index（全量清空）→ 批量 INSERT
   （title/body/entity_type/entity_id/project_id 五列）→ upsert
   search_meta.last_rebuilt_at = now(UTC) → commit。
   幂等：连续两次调用不报错，第二次结果覆盖第一次（E8）。

5. incremental_sync(documents: Iterable[SearchDocument],
   deleted: Iterable[tuple[str, int]]) -> None:

   对每个 (entity_type, entity_id) 对 DELETE 旧索引行 → INSERT 新文档 →
   upsert last_rebuilt_at → commit（§5.3 AI 自动维护）。

6. query(match: str, project_ids: list[int], types: list[str] | None,
   limit: int, offset: int) -> tuple[int, list[SearchHit]]:

   - WHERE search_index MATCH :match AND project_id IN (...) [AND entity_type IN (...)]
   - ORDER BY rank（BM25，低分在前）LIMIT :limit OFFSET :offset
   - total = 同条件 COUNT(*)（不受 limit 影响）
   - 高亮: ``snippet(search_index, 1, '<mark>', '</mark>', '…', 48)``
     （第 1 列 = body；第 0 列 title 不参与高亮——spec §5.4 列索引以父侧裁定 = 1）
   - score = rank 值（float，可为负）
   - 返回 SearchHit（inkflow.domain.models.search 领域 DTO）:
     entity_id/project_id 从 int 转回 uuid.UUID（UUID(int=...)）；
     entity_type 从 TEXT 映射回 SearchEntityType（StrEnum，.value 为 'chapter' 等）

7. get_setting(key) -> str | None / set_setting(key, value) -> None:

   search_meta key-value 读写；缺失键 → None（如 ai_maintenance 默认 None）；
   set 后 commit。

RED 预期: collected 0 items + 1 error（No module named
'inkflow.infrastructure.database.repositories.search_repo'）——预期 RED；
其他错误 = 测试文件自身缺陷。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.search_repo import SQLiteSearchRepository


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）。

    同仓储测试 fixture 模式：:memory: 每连接独立，必须全程同一
    engine/session；FTS5 虚拟表 + search_meta 由 ensure_index() 创建
    （不在 Base.metadata 内，spec §2.4）。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _doc(entity_type: str, entity_id: int, project_id: int, title: str, body: str):
    """构造 SearchDocument（惰性 import——RED 阶段 ports.search_repository 缺失）."""
    from inkflow.domain.ports.search_repository import SearchDocument

    return SearchDocument(
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=project_id,
        title=title,
        body=body,
    )


def _repo(db_session) -> SQLiteSearchRepository:
    """构造被测仓储（SearchRepositoryProtocol 的 SQLite 实现）."""
    return SQLiteSearchRepository(db_session)


# ────────────────────────────── 中文命中 + 高亮（M1/M3） ──────────────────────────────


async def test_chinese_token_hit_with_mark_snippet(db_session):
    """M1 核心: 分词后入库（'古井深处 龙 瞳睁开'）→ '"龙"' 命中 + <mark> 高亮."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild(
        [
            _doc("chapter", 1, 1, "第 3 章 龙的苏醒", "古井深处 龙 瞳睁开"),
        ]
    )

    total, hits = await repo.query('"龙"', [1], None, 20, 0)

    assert total == 1
    hit = hits[0]
    assert hit.title == "第 3 章 龙的苏醒"
    assert hit.entity_type == "chapter"
    assert hit.entity_id == uuid.UUID(int=1)
    assert hit.project_id == uuid.UUID(int=1)
    assert "<mark>龙</mark>" in hit.snippet
    assert isinstance(hit.score, float)


async def test_snippet_escapes_html_no_raw_tags(db_session):
    """M3/E10: snippet 高亮且不含未转义 HTML（正文入库前已 XML 转义，原样回显）."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild(
        [
            _doc(
                "chapter",
                1,
                1,
                "古井秘闻",
                "古井深处 龙 瞳睁开 &lt;script&gt;alert(1)&lt;/script&gt;",
            ),
        ]
    )

    total, hits = await repo.query('"龙"', [1], None, 20, 0)

    assert total == 1
    snippet = hits[0].snippet
    assert "<mark>龙</mark>" in snippet
    assert "<script" not in snippet
    assert "&lt;script&gt;" in snippet


# ────────────────────────────── 保留字安全（M7） ──────────────────────────────


async def test_reserved_word_escape_quoted_match(db_session):
    """M7: FTS5 保留字 AND 被引号包裹 → 按普通词匹配正文中的 'AND'."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild(
        [
            _doc("character", 2, 1, "北境守军", "北境 荒原 AND 冰雪 覆盖"),
        ]
    )

    total, hits = await repo.query('"AND"', [1], None, 20, 0)

    assert total == 1
    assert hits[0].title == "北境守军"


# ────────────────────────────── 过滤 / 分页 / 类型（M10/§6.3） ──────────────────────────────


async def test_multi_project_filter(db_session):
    """M10: project_id IN 过滤——单项目只返回本项目命中，双项目返回全部."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild(
        [
            _doc("chapter", 1, 1, "第一部 龙", "古井深处 龙 瞳睁开"),
            _doc("chapter", 2, 2, "第二部 龙", "北境荒原 龙 息如雷"),
        ]
    )

    total, hits = await repo.query('"龙"', [1], None, 20, 0)
    assert total == 1
    assert hits[0].entity_id == uuid.UUID(int=1)
    assert hits[0].project_id == uuid.UUID(int=1)

    total2, hits2 = await repo.query('"龙"', [1, 2], None, 20, 0)
    assert total2 == 2
    assert {h.entity_id for h in hits2} == {uuid.UUID(int=1), uuid.UUID(int=2)}


async def test_pagination_limit_offset(db_session):
    """分页: limit/offset 生效，total 不受 limit 影响（跨页命中不重叠）."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild(
        [
            _doc("chapter", 1, 1, "龙一", "龙 一"),
            _doc("chapter", 2, 1, "龙二", "龙 二"),
            _doc("chapter", 3, 1, "龙三", "龙 三"),
        ]
    )

    total, page1 = await repo.query('"龙"', [1], None, 2, 0)
    assert total == 3
    assert len(page1) == 2

    total2, page2 = await repo.query('"龙"', [1], None, 2, 2)
    assert total2 == 3
    assert len(page2) == 1
    assert page2[0].title not in {h.title for h in page1}


async def test_type_filter(db_session):
    """§6.3: entity_type IN 筛选；types=None → 全部类型."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild(
        [
            _doc("chapter", 1, 1, "第 3 章 龙", "古井深处 龙 瞳睁开"),
            _doc("character", 2, 1, "龙女", "北境 龙 女"),
        ]
    )

    total, hits = await repo.query('"龙"', [1], ["chapter"], 20, 0)
    assert total == 1
    assert hits[0].entity_type == "chapter"

    total_all, _ = await repo.query('"龙"', [1], None, 20, 0)
    assert total_all == 2


# ────────────────────────────── 确定性 / 空库（M8/E5） ──────────────────────────────


async def test_deterministic_results(db_session):
    """M8: 同数据同查询两次 → 结果完全一致（BM25 稳定，无随机种子）."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild(
        [
            _doc("chapter", 1, 1, "第 3 章 龙", "古井深处 龙 瞳睁开 龙息 如雷"),
            _doc("character", 2, 1, "龙女", "北境 龙 女 龙族 血脉"),
        ]
    )

    t1, h1 = await repo.query('"龙"', [1], None, 20, 0)
    t2, h2 = await repo.query('"龙"', [1], None, 20, 0)

    assert t1 == t2 == 2
    assert [(h.entity_id, h.title, h.score, h.snippet) for h in h1] == [
        (h.entity_id, h.title, h.score, h.snippet) for h in h2
    ]


async def test_empty_index_returns_empty(db_session):
    """E5: 空库查询 → (0, []) 不报错."""
    repo = _repo(db_session)
    await repo.ensure_index()

    total, hits = await repo.query('"龙"', [1], None, 20, 0)

    assert total == 0
    assert hits == []


# ────────────────────────────── 脏检测（M5） ──────────────────────────────


async def test_is_stale_lifecycle(db_session):
    """M5: 无 meta → True；rebuild 后 → False；业务表新行（updated_at 更新）→ True."""
    repo = _repo(db_session)
    await repo.ensure_index()

    assert await repo.is_stale(["chapters"]) is True

    await repo.rebuild([_doc("chapter", 1, 1, "第 3 章 龙", "古井深处 龙 瞳睁开")])
    assert await repo.is_stale(["chapters"]) is False

    project = ProjectORM(name="测试项目")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    future = datetime.now(UTC) + timedelta(days=1)
    db_session.add(
        ChapterORM(
            project_id=project.id,
            title="新章",
            content="龙 息",
            status="final",
            updated_at=future,
        )
    )
    await db_session.commit()

    assert await repo.is_stale(["chapters"]) is True


# ────────────────────────────── 设置读写（§5.3） ──────────────────────────────


async def test_settings_roundtrip(db_session):
    """§5.3: ai_maintenance 默认 None；set 后读回 'true'（写操作 commit）."""
    repo = _repo(db_session)
    await repo.ensure_index()

    assert await repo.get_setting("ai_maintenance") is None

    with patch.object(db_session, "commit", new=AsyncMock(wraps=db_session.commit)) as mock_commit:
        await repo.set_setting("ai_maintenance", "true")
    mock_commit.assert_awaited_once()

    assert await repo.get_setting("ai_maintenance") == "true"


# ────────────────────────────── 重建幂等 / 增量同步（E8/§5.3） ──────────────────────────────


async def test_rebuild_idempotent_overwrites(db_session):
    """E8: 连续两次 rebuild 不报错，第二次全量覆盖第一次（DELETE + 重插）."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild([_doc("chapter", 1, 1, "旧标题", "龙 旧文")])
    await repo.rebuild([_doc("chapter", 1, 1, "新标题", "龙 新文")])

    total, hits = await repo.query('"龙"', [1], None, 20, 0)

    assert total == 1
    assert hits[0].title == "新标题"


async def test_incremental_sync_replaces_rows(db_session):
    """§5.3 增量: DELETE 旧行 + INSERT 新行 + 刷新 meta（旧内容不可再命中）."""
    repo = _repo(db_session)
    await repo.ensure_index()
    await repo.rebuild([_doc("chapter", 1, 1, "旧标题", "龙 旧文")])

    await repo.incremental_sync(
        documents=[_doc("chapter", 1, 1, "新标题", "龙 新文")],
        deleted=[("chapter", 1)],
    )

    total, hits = await repo.query('"龙"', [1], None, 20, 0)
    assert total == 1
    assert hits[0].title == "新标题"

    total_old, hits_old = await repo.query('"旧文"', [1], None, 20, 0)
    assert total_old == 0
    assert hits_old == []

    assert await repo.is_stale(["chapters"]) is False
