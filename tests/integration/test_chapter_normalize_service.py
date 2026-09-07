"""#999 章节标题双编号归一化 — ChapterService.normalize_all_titles 服务层集成（RED-2 批）。

契约定稿 .hermes/plans/999-contract.md §4:
- `ChapterService(db_session)` 单参兼容（既有调用零破坏）+ 可选 outline_repo/project_repo。
- `normalize_all_titles(project_id, fmt) -> dict[str, int]`（返回 chapters/outlines 两计数）。

真实 in-memory SQLite 全链路：种项目 + 章 + chapter 级大纲 → 调用 normalize_all_titles
→ 断言计数、库中 title 变化、project.config 持久化、幂等（第二次计数全 0）。

实现不存在 → 本文件新用例预期 AttributeError（normalize_all_titles 未定义）→ FAIL。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

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


# ── #999 coverage 补测（service 级黑盒：契约 §4 防御分支，直接绿非 RED）──


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_invalid_fmt_raises(db_session, sample_project):
    """契约 §4：fmt 非法（arabic/chinese 之外）→ ValueError（router 转 422）。"""
    svc = ChapterService(db_session)
    with pytest.raises(ValueError, match="不支持的章节标题格式"):
        await svc.normalize_all_titles(sample_project.id, "weird")


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_project_missing_returns_none(db_session):
    """契约 §4：项目不存在（合法 UUID 但无行）→ 返回 None（router 转 404）。"""
    svc = ChapterService(db_session)
    missing = uuid.UUID(int=999_999)
    assert await svc.normalize_all_titles(missing, "arabic") is None


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_skips_non_chapter_and_unchanged(
    db_session, sample_project
):
    """契约 §4：level≠chapter 大纲不参与归一；归一后不变的章级大纲不计数。"""
    pid = sample_project.id
    db_session.add(
        OutlineORM(project_id=pid, name="第1卷 风起", level="volume", volume_id=None)
    )
    db_session.add(
        OutlineORM(project_id=pid, name="第一章 已中", level="chapter", volume_id=None)
    )
    await db_session.commit()

    svc = ChapterService(db_session)
    result = await svc.normalize_all_titles(pid, "chinese")
    # 卷纲「第1卷」不动（非章轨）；章纲已是中文 → 无变化不计数
    assert result == {"chapters_replaced": 0, "outlines_replaced": 0}
    rows = (
        await db_session.execute(
            select(OutlineORM).where(OutlineORM.project_id == pid)
        )
    ).scalars()
    assert {o.name for o in rows} == {"第1卷 风起", "第一章 已中"}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_dup_name_skipped(db_session, sample_project):
    """契约 §4：章纲归一后撞 uq_outlines_active_name 重名 → 跳过不计数不抛。"""
    pid = sample_project.id
    db_session.add(
        OutlineORM(project_id=pid, name="第1章 a", level="chapter", volume_id=None)
    )
    db_session.add(
        OutlineORM(project_id=pid, name="第一章 a", level="chapter", volume_id=None)
    )
    await db_session.commit()

    svc = ChapterService(db_session)
    result = await svc.normalize_all_titles(pid, "chinese")
    assert result == {"chapters_replaced": 0, "outlines_replaced": 0}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_all_titles_paginates_all_chapters(db_session, sample_project):
    """契约 §4：>50 章/大纲时分页循环取完（回边弧），全部归一计数正确。"""
    pid = sample_project.id
    svc = ChapterService(db_session)
    for i in range(51, 106):  # 55 章阿拉伯序号 51..105 → chinese 全变化
        await svc.create_chapter(pid, f"第{i}章 t")
    for i in range(106, 161):  # 55 个章级大纲 106..160 → chinese 全变化
        db_session.add(
            OutlineORM(project_id=pid, name=f"第{i}章 o", level="chapter", volume_id=None)
        )
    await db_session.commit()

    result = await svc.normalize_all_titles(pid, "chinese")
    assert result == {"chapters_replaced": 55, "outlines_replaced": 55}

    items, total = await svc.list_chapters(pid, limit=100)
    assert total == 55
    assert all("章" in c.title and not any(ch.isdigit() for ch in c.title) for c in items)
