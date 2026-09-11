"""#1095 回归 RED — 归一幂等性破坏 + 守卫非不动点（数据丢失）。

背景：#1095（PR #1108, commit 0f459aa）合入的 normalize_chapter_content
存在幂等性缺陷 —— 二次归一**静默删除合法正文段落**。

根因（源码实证）
----------------
`chapter.py` 的 `_is_duplicate_title_line(line, title)` 内部先 `line.strip()`，
而 `str.strip()` 会剥掉 U+3000（全角空格属 Unicode 空白）。于是归一产物
首段 `　　第1章 开端` 在 strip 后 == title → 被重新认定为「重复标题行」→ 删除。

触发链（真实可达）
------------------
    x = "\\n\\n第1章 开端\\n\\n正文第一段。"
    N(x,t)   = "　　第1章 开端\\n\\n　　正文第一段。"   # 首行是空行 → 标题行未剥离
    N(N(x),t)= "　　正文第一段。"                        # 标题段被静默删除

    need(x, t)      = True
    need(N(x), t)   = True   ← 守卫不是不动点（归一产物仍被判为脏）

live 路径实证（本 worktree 复现）：create_chapter 落库
`　　第1章 开端\n\n　　正文第一段。` 后，一次 `update_chapter(status='writing')`
（**只改状态**）即把 `第1章 开端` 段删除 —— 数据丢失。

契约（本文件锁定的不变量）
--------------------------
I1 幂等：对任意 content/title，`N(N(x,t),t) == N(x,t)`
I2 守卫不动点：`need(N(x,t),t) == False`（归一产物必不再被判脏）
I3 一致性：`need(x,t) == (N(x,t) != x)`
I4 不删正文：归一不得删除与 title 同文但**属于正文**的段落
I5 回归：既有 31 个 #1095 契约断言不得破坏
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter import (
    ChapterUpdate,
    chapter_content_needs_normalize,
    normalize_chapter_content,
)
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.project import ProjectORM

FULLWIDTH = "\u3000"
TITLE = "第1章 开端"


# 覆盖「归一后仍需二次归一」的危险形态 —— 每条都必须满足 I1-I4
IDEMPOTENCY_INPUTS = [
    ("plain dup first", f"{TITLE}\n\n正文第一段。"),
    ("leading blank + title", f"\n\n{TITLE}\n\n正文第一段。"),
    ("leading blanks + title", f"\n\n\n{TITLE}\n\n正文第一段。"),
    ("hash dup", f"# {TITLE}\n\n正文第一段。"),
    ("hash dup + leading blank", f"\n\n# {TITLE}\n\n正文第一段。"),
    ("bold dup", f"**{TITLE}**\n\n正文第一段。"),
    ("chinese numeral form", "第一章 开端\n\n正文第一段。"),
    ("title repeated mid-body", f"{TITLE}\n\n正文零。\n\n{TITLE}\n\n正文第一段。"),
    ("already indented title para", f"{FULLWIDTH}{TITLE}\n\n{FULLWIDTH}正文第一段。"),
    ("indented + leading blank", f"\n\n{FULLWIDTH}{TITLE}\n\n{FULLWIDTH}正文第一段。"),
    ("multi-paragraph clean", f"{FULLWIDTH}正文一。\n\n{FULLWIDTH}正文二。"),
    ("trailing whitespace title", f"{TITLE}   \n\n正文第一段。"),
    ("single line", "师父停了三天。"),
    ("empty", ""),
    ("whitespace only", "   \n\n  \n"),
]


class TestI1Idempotency:
    """I1: N(N(x)) == N(x) —— 对全部危险形态成立。"""

    @pytest.mark.parametrize(("name", "content"), IDEMPOTENCY_INPUTS)
    def test_normalize_is_idempotent(self, name: str, content: str) -> None:
        once = normalize_chapter_content(content, TITLE)
        twice = normalize_chapter_content(once, TITLE)
        assert once == twice, (
            f"[{name}] 归一非幂等（二次归一改变了结果）\n"
            f"  输入 : {content!r}\n"
            f"  一次 : {once!r}\n"
            f"  二次 : {twice!r}"
        )


class TestI2GuardFixedPoint:
    """I2: need(N(x)) == False —— 归一产物不得再被判为脏（否则落库/导出会反复归一）。"""

    @pytest.mark.parametrize(("name", "content"), IDEMPOTENCY_INPUTS)
    def test_guard_is_fixed_point_after_normalize(self, name: str, content: str) -> None:
        once = normalize_chapter_content(content, TITLE)
        assert chapter_content_needs_normalize(once, TITLE) is False, (
            f"[{name}] 守卫非不动点：归一产物仍被判为脏 → 会触发二次归一\n" f"  归一产物: {once!r}"
        )


class TestI3GuardConsistency:
    """I3: need(x) == (N(x) != x) —— 守卫判断与纯函数行为一致。"""

    @pytest.mark.parametrize(("name", "content"), IDEMPOTENCY_INPUTS)
    def test_guard_matches_actual_change(self, name: str, content: str) -> None:
        changed = normalize_chapter_content(content, TITLE) != content
        assert chapter_content_needs_normalize(content, TITLE) is changed, (
            f"[{name}] 守卫与归一不一致（need={chapter_content_needs_normalize(content, TITLE)}, "
            f"changed={changed}）"
        )


class TestI4NoBodyParagraphDeleted:
    """I4: 归一不得删除与 title 同文但属于正文的段落。

    前导空行使「标题行」不在 raw 的 line[0]，故不被剥离 —— 归一后它带全角
    缩进成为正文首段。二次归一**不得**把它当重复标题删掉。
    """

    def test_leading_blank_title_paragraph_preserved_across_two_passes(self) -> None:
        content = f"\n\n{TITLE}\n\n正文第一段。"
        once = normalize_chapter_content(content, TITLE)
        twice = normalize_chapter_content(once, TITLE)
        assert (
            TITLE in twice
        ), f"二次归一删除了正文首段 {TITLE!r}\n  一次: {once!r}\n  二次: {twice!r}"
        assert "正文第一段。" in twice

    def test_body_titles_survive_even_when_equal_to_title(self) -> None:
        """正文中再次出现章名（LLM 常见）→ 两次归一后仍保留。"""
        content = f"{TITLE}\n\n正文零。\n\n{TITLE}\n\n正文第一段。"
        result = normalize_chapter_content(normalize_chapter_content(content, TITLE), TITLE)
        assert "正文零。" in result
        assert "正文第一段。" in result


@pytest.fixture
async def db_session():
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


class TestI4LivePathNoDataLoss:
    """I4 live 路径：只改 status 的 update 不得删除正文段落（数据丢失回归）。"""

    @pytest.mark.parametrize(
        "raw_content",
        [
            f"\n\n{TITLE}\n\n正文第一段。",
            f"{TITLE}\n\n正文零。\n\n{TITLE}\n\n正文第一段。",
        ],
    )
    async def test_status_only_update_preserves_content(self, db_session, raw_content: str) -> None:
        p = ProjectORM(name="归一回损项目")
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)

        svc = ChapterService(db_session)
        ch = await svc.create_chapter(uuid.UUID(int=p.id), TITLE, content=raw_content)
        created = ch.content or ""

        # 只改状态（真实编辑流程里的常规操作）
        updated = await svc.update_chapter(ch.id, ChapterUpdate(status="writing"))
        assert updated is not None
        assert updated.content == created, (
            "只改 status 的 update 改写了正文（二次归一）\n"
            f"  落库: {created!r}\n  更新后: {updated.content!r}"
        )
        for para in ("正文第一段。",):
            assert para in (
                updated.content or ""
            ), f"update 后丢失正文段落 {para!r}: {updated.content!r}"
