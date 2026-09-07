"""#999 章节标题双编号归一化 — ChapterService.normalize_all_titles 服务层集成（RED-2 批）。

契约定稿 .hermes/plans/999-contract.md §4:
- `ChapterService(db_session)` 单参兼容（既有调用零破坏）+ 可选 outline_repo/project_repo。
- `normalize_all_titles(project_id, fmt) -> dict[str, int]`（返回 chapters/outlines 两计数）。

真实 in-memory SQLite 全链路：种项目 + 章 + chapter 级大纲 → 调用 normalize_all_titles
→ 断言计数、库中 title 变化、project.config 持久化、幂等（第二次计数全 0）。

实现不存在 → 本文件新用例预期 AttributeError（normalize_all_titles 未定义）→ FAIL。
"""

from __future__ import annotations

import pytest

from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_arabic(db_session, sample_project):
    """arabic 归一：'第三章 转折'→'第3章 转折'（chapters_replaced 1）、
    '第一百章 终'→'第100章 终'（outline 同步 1）；其余不动。"""
    pid = sample_project.id
    svc = ChapterService(db_session)
    await svc.create_chapter(pid, "第1章 起点")
    await svc.create_chapter(pid, "第三章 转折")
    await svc.create_chapter(pid, "一叶落")
    db_session.add(
        OutlineORM(project_id=pid, name="第一百章 终", level="chapter", volume_id=None)
    )
    await db_session.commit()

    result = await svc.normalize_all_titles(pid, "arabic")
    assert result == {"chapters_replaced": 1, "outlines_replaced": 1}

    items, _total = await svc.list_chapters(pid)
    titles = {c.title for c in items}
    assert titles == {"第1章 起点", "第3章 转折", "一叶落"}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_idempotent(db_session, sample_project):
    """同 fmt 第二次调用 → 两计数全 0（幂等）。"""
    pid = sample_project.id
    svc = ChapterService(db_session)
    await svc.create_chapter(pid, "第三章 转折")

    first = await svc.normalize_all_titles(pid, "arabic")
    assert first == {"chapters_replaced": 1, "outlines_replaced": 0}

    second = await svc.normalize_all_titles(pid, "arabic")
    assert second == {"chapters_replaced": 0, "outlines_replaced": 0}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_persists_config(db_session, sample_project):
    """normalize 后 project.config.chapter_title_format == fmt（project_repo.update 持久化）。"""
    pid = sample_project.id
    svc = ChapterService(db_session)
    await svc.create_chapter(pid, "第三章 转折")

    result = await svc.normalize_all_titles(pid, "arabic")
    assert result["chapters_replaced"] == 1

    proj = await SQLiteProjectRepository(db_session).get(pid)
    assert proj is not None
    assert proj.config.chapter_title_format == "arabic"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_chinese(db_session, sample_project):
    """chinese 归一：'第1章 起点'→'第一章 起点'（计数 1）。"""
    pid = sample_project.id
    svc = ChapterService(db_session)
    await svc.create_chapter(pid, "第1章 起点")
    await svc.create_chapter(pid, "第三章 转折")

    result = await svc.normalize_all_titles(pid, "chinese")
    assert result == {"chapters_replaced": 1, "outlines_replaced": 0}

    items, _total = await svc.list_chapters(pid)
    titles = {c.title for c in items}
    assert titles == {"第一章 起点", "第三章 转折"}
