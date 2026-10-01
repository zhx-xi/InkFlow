"""#1430：章节「上一稿快照」+ 恢复读口契约（RED→GREEN）。

权威来源：issue #1430 实现清单第 2/3 条 + 拍板结论 A2。

语义（本契约冻结）
==================

**快照规则（写路径）**：`ChapterService.update_chapter` 在**落实新正文之前**，
若「归一后的新正文 != 库中旧正文」且「旧正文非空白」→ 把**库中旧正文**
（``existing.content``，逐字，非入参原文）写进 ``previous_content``。

- 旧正文为空白（``""`` / 纯空白）→ **不写空壳**：``previous_content`` 保持原值
  （空值判据与安全闸 ``content_checker`` 同口径：``.strip()`` 后非空才算有正文）
- 只改标题 / 正文值未变 → 不产生快照（无内容丢失，备份无意义）
- 连续覆盖 → ``previous_content`` 始终是**紧邻上一版**（不是首版）

**恢复读口**：`ChapterService.restore_previous_content(chapter_id)`

- 把 ``previous_content`` 写回 ``content``；动作本身也**遵守同一覆盖口径**
  （旧稿是被新正文覆盖掉的，所以恢复同样先落一次快照）→ 结果是一次
  **双向切换**：``content`` ⇄ ``previous_content`` 互换，可再恢复回去
- ``previous_content`` 为空/纯空白 → ``PreviousContentUnavailableError``
  （router 409「无可恢复的旧稿」）
- 章不存在 → ``None``（router 404）

RED 形态：`Chapter` 无 ``previous_content`` 字段 / `restore_previous_content`
与 `PreviousContentUnavailableError` 不存在 → 收集期或首例即失败。
"""

from __future__ import annotations

import uuid

import pytest

from inkflow.domain.models.chapter import Chapter
from inkflow.domain.services.chapter_service import (
    ChapterService,
    PreviousContentUnavailableError,
)

_PROJECT_ID = uuid.UUID("01920000-0000-7000-8000-000000001430")
_CHAPTER_ID = uuid.UUID("01920000-0000-7000-8000-000000001431")

_FIRST_DRAFT = "第一稿正文"
_SECOND_DRAFT = "第二稿正文"


class _FakeChapterRepo:
    """单章内存仓储替身（只实现本文件用到的两个方法）。"""

    def __init__(self, chapter: Chapter) -> None:
        self.chapter = chapter
        self.update_calls = 0

    async def get_chapter(self, chapter_id: uuid.UUID) -> Chapter | None:
        if chapter_id != self.chapter.id:
            return None
        return self.chapter

    async def update_chapter(self, chapter: Chapter) -> Chapter:
        self.update_calls += 1
        self.chapter = chapter
        return chapter


def _chapter(content: str, *, title: str = "第一章 起") -> Chapter:
    """构造单行正文的章（单行 = 归一豁免，便于断言逐字相等）。"""
    return Chapter(
        id=_CHAPTER_ID,
        project_id=_PROJECT_ID,
        title=title,
        content=content,
        previous_content=None,
    )


def _service(content: str, *, title: str = "第一章 起") -> tuple[ChapterService, _FakeChapterRepo]:
    """装配 ChapterService：替换内部仓储为内存替身。"""
    svc = ChapterService(db_session=None)
    repo = _FakeChapterRepo(_chapter(content, title=title))
    svc._repo = repo  # type: ignore[assignment]  # 单测替身：仓储出 DB
    return svc, repo


@pytest.mark.asyncio
async def test_overwrite_snapshots_previous_content_verbatim() -> None:
    """覆盖前必落：旧正文逐字进 previous_content，正文本身被新值替换。"""
    from inkflow.domain.models.chapter import ChapterUpdate

    svc, repo = _service(_FIRST_DRAFT)

    saved = await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(content=_SECOND_DRAFT))

    assert saved is not None
    assert saved.content == _SECOND_DRAFT
    assert saved.previous_content == _FIRST_DRAFT  # 逐字相等（含未做任何改写）
    assert repo.chapter.previous_content == _FIRST_DRAFT


@pytest.mark.asyncio
async def test_overwrite_of_empty_content_leaves_no_shell() -> None:
    """旧值为空时不留空壳：空正文被覆盖 → previous_content 恒为 None。"""
    from inkflow.domain.models.chapter import ChapterUpdate

    svc, _repo = _service("")

    saved = await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(content=_SECOND_DRAFT))

    assert saved is not None
    assert saved.content == _SECOND_DRAFT
    assert saved.previous_content is None


@pytest.mark.asyncio
async def test_overwrite_of_whitespace_only_content_leaves_no_shell() -> None:
    """纯空白旧正文同样不算「有旧稿」（与 content_checker 的 .strip() 同口径）。"""
    from inkflow.domain.models.chapter import ChapterUpdate

    svc, _repo = _service("   \n  ")

    saved = await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(content=_SECOND_DRAFT))

    assert saved is not None
    assert saved.previous_content is None


@pytest.mark.asyncio
async def test_title_only_update_does_not_snapshot() -> None:
    """只改标题不产生快照（正文未被覆盖，无内容丢失）。"""
    from inkflow.domain.models.chapter import ChapterUpdate

    svc, _repo = _service(_FIRST_DRAFT)

    saved = await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(title="第一章 起势"))

    assert saved is not None
    assert saved.title == "第一章 起势"
    assert saved.content == _FIRST_DRAFT
    assert saved.previous_content is None


@pytest.mark.asyncio
async def test_same_content_update_does_not_snapshot() -> None:
    """正文值未变（幂等写）不产生快照。"""
    from inkflow.domain.models.chapter import ChapterUpdate

    svc, _repo = _service(_FIRST_DRAFT)

    saved = await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(content=_FIRST_DRAFT))

    assert saved is not None
    assert saved.previous_content is None


@pytest.mark.asyncio
async def test_second_overwrite_keeps_adjacent_previous_version() -> None:
    """连续覆盖 → previous_content 是紧邻上一版（不是首版）。"""
    from inkflow.domain.models.chapter import ChapterUpdate

    svc, _repo = _service(_FIRST_DRAFT)
    await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(content=_SECOND_DRAFT))

    saved = await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(content="第三稿正文"))

    assert saved is not None
    assert saved.content == "第三稿正文"
    assert saved.previous_content == _SECOND_DRAFT


@pytest.mark.asyncio
async def test_restore_swaps_content_with_previous() -> None:
    """恢复读口：previous_content 写回 content；恢复动作自身也遵守覆盖口径 → 双向切换。"""
    from inkflow.domain.models.chapter import ChapterUpdate

    svc, repo = _service(_FIRST_DRAFT)
    await svc.update_chapter(_CHAPTER_ID, ChapterUpdate(content=_SECOND_DRAFT))

    restored = await svc.restore_previous_content(_CHAPTER_ID)

    assert restored is not None
    assert restored.content == _FIRST_DRAFT  # 旧稿写回
    assert restored.previous_content == _SECOND_DRAFT  # 被替换的新正文落回备份位（可再切回）
    assert repo.chapter.content == _FIRST_DRAFT


@pytest.mark.asyncio
async def test_restore_without_previous_content_raises() -> None:
    """无可恢复的旧稿（previous_content 为空/纯空白）→ PreviousContentUnavailableError。"""
    svc, _repo = _service(_FIRST_DRAFT)

    with pytest.raises(PreviousContentUnavailableError):
        await svc.restore_previous_content(_CHAPTER_ID)


@pytest.mark.asyncio
async def test_restore_whitespace_previous_content_raises() -> None:
    """纯空白 previous_content 不算可恢复内容（同口径）。"""
    svc, repo = _service(_FIRST_DRAFT)
    repo.chapter = repo.chapter.model_copy(update={"previous_content": "  \n "})

    with pytest.raises(PreviousContentUnavailableError):
        await svc.restore_previous_content(_CHAPTER_ID)


@pytest.mark.asyncio
async def test_restore_unknown_chapter_returns_none() -> None:
    """章不存在 → None（router 转 404），不抛 PreviousContentUnavailableError。"""
    svc, _repo = _service(_FIRST_DRAFT)

    assert await svc.restore_previous_content(uuid.uuid4()) is None
