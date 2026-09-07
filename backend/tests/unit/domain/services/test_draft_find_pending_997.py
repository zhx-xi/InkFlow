"""#997 RED 契约测试 — DraftService.find_pending / replace_content（幂等覆盖服务层增量）.

契约真相源: specs/f27-writer-agent/spec.md §5.2「DraftService/仓储增量（D2 拍板）」.
拍板契约 E:

- async find_pending(project_id, *, chapter_id=None, source_outline_id=None) -> Draft | None:
  两键皆 None → 直接返回 None（不查 repo）；否则透传 repo.find_pending(project_id=…,
  chapter_id=…, source_outline_id=…)。
- async replace_content(draft_id, content, summary=None) -> Draft:
  空 content（strip 后）→ ValueError；repo.get 无 → DraftNotFoundError；
  状态非 DRAFT → DraftStateError；repo.update_content(draft_id, content, summary=summary)
  返回 None → DraftNotFoundError；成功返回 Draft；全程不调 memory_service（F28 零 diff）。

当前实现对照（全部 RED）: DraftService 无 find_pending / replace_content 方法 →
svc.find_pending(...) / svc.replace_content(...) 抛 AttributeError（契约未实现类 RED）。

镜像 test_draft_volume_976.py 形态（AsyncMock repo + 直接 await 服务方法）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services.draft_service import (
    DraftNotFoundError,
    DraftService,
    DraftStateError,
)

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
SOURCE_OUTLINE_ID = uuid.UUID(int=51)
CONTENT = "第一章 测试内容。这是草稿正文，用于验证 find_pending / replace_content 契约。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    kwargs: dict = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content=CONTENT,
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


def _arg_or_kw(call, name: str, index: int, default=None):
    """宽松取 mock 调用参数：优先关键字，回退位置参数（兼容两种 GREEN 形态）。"""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


# ── 契约 E: find_pending ──


async def test_find_pending_none_key_short_circuits() -> None:
    """【R】两归组键皆 None → 直接返回 None，不查 repo（chat 轨无锚点防御）。"""
    repo = AsyncMock()
    repo.find_pending.return_value = _make_draft()
    svc = DraftService(draft_repo=repo)

    result = await svc.find_pending(PROJECT_ID)

    assert result is None
    repo.find_pending.assert_not_awaited()


async def test_find_pending_passes_kwargs_to_repo() -> None:
    """【R】find_pending(project_id, chapter_id=…, source_outline_id=…) 透传 repo。

    当前 DraftService 无 find_pending → AttributeError（RED）。
    """
    repo = AsyncMock()
    repo.find_pending.return_value = _make_draft()
    svc = DraftService(draft_repo=repo)

    result = await svc.find_pending(
        PROJECT_ID, chapter_id=CHAPTER_ID, source_outline_id=SOURCE_OUTLINE_ID
    )

    assert result is not None
    repo.find_pending.assert_awaited_once()
    call = repo.find_pending.await_args
    assert call.kwargs["project_id"] == PROJECT_ID
    assert call.kwargs["chapter_id"] == CHAPTER_ID
    assert call.kwargs["source_outline_id"] == SOURCE_OUTLINE_ID


async def test_find_pending_source_only_kwarg() -> None:
    """【R】仅 source_outline_id 归组键 → repo.find_pending 收 source_id 且 chapter None。"""
    repo = AsyncMock()
    repo.find_pending.return_value = _make_draft()
    svc = DraftService(draft_repo=repo)

    await svc.find_pending(PROJECT_ID, source_outline_id=SOURCE_OUTLINE_ID)

    call = repo.find_pending.await_args
    assert call.kwargs["chapter_id"] is None
    assert call.kwargs["source_outline_id"] == SOURCE_OUTLINE_ID


async def test_find_pending_returns_none_when_repo_none() -> None:
    """【R】repo.find_pending 返回 None → 服务透传 None。"""
    repo = AsyncMock()
    repo.find_pending.return_value = None
    svc = DraftService(draft_repo=repo)

    result = await svc.find_pending(PROJECT_ID, source_outline_id=SOURCE_OUTLINE_ID)

    assert result is None


# ── 契约 E: replace_content ──


async def test_replace_content_empty_content_raises() -> None:
    """【R】空 content（strip 后）→ ValueError；不查 repo.get。"""
    repo = AsyncMock()
    svc = DraftService(draft_repo=repo)

    with pytest.raises(ValueError):
        await svc.replace_content("draft-1", "   ")

    repo.get.assert_not_awaited()


async def test_replace_content_missing_draft_raises() -> None:
    """【R】repo.get 无 → DraftNotFoundError。"""
    repo = AsyncMock()
    repo.get.return_value = None
    svc = DraftService(draft_repo=repo)

    with pytest.raises(DraftNotFoundError):
        await svc.replace_content("draft-x", CONTENT)


async def test_replace_content_confirmed_raises() -> None:
    """【R】草稿状态非 DRAFT（confirmed）→ DraftStateError（幂等守卫：不可静默改正文）。"""
    repo = AsyncMock()
    repo.get.return_value = _make_draft(status=DraftStatus.CONFIRMED)
    svc = DraftService(draft_repo=repo)

    with pytest.raises(DraftStateError):
        await svc.replace_content("draft-1", CONTENT)


async def test_replace_content_rejected_raises() -> None:
    """【R】草稿状态非 DRAFT（rejected）→ DraftStateError。"""
    repo = AsyncMock()
    repo.get.return_value = _make_draft(status=DraftStatus.REJECTED)
    svc = DraftService(draft_repo=repo)

    with pytest.raises(DraftStateError):
        await svc.replace_content("draft-1", CONTENT)


async def test_replace_content_update_returns_none_raises() -> None:
    """【R】repo.update_content 返回 None（竞态：确认前被删除）→ DraftNotFoundError。"""
    repo = AsyncMock()
    repo.get.return_value = _make_draft()
    repo.update_content.return_value = None
    svc = DraftService(draft_repo=repo)

    with pytest.raises(DraftNotFoundError):
        await svc.replace_content("draft-1", CONTENT)


async def test_replace_content_success_passes_summary_to_repo() -> None:
    """【R】成功路径 repo.update_content 收 (draft_id, content, summary=summary)。

    当前 DraftService 无 replace_content → AttributeError（RED）。
    """
    repo = AsyncMock()
    repo.get.return_value = _make_draft()
    repo.update_content.return_value = _make_draft()
    svc = DraftService(draft_repo=repo)

    result = await svc.replace_content("draft-1", CONTENT, summary="新摘要")

    assert result is not None
    repo.update_content.assert_awaited_once()
    call = repo.update_content.await_args
    assert call.args[0] == "draft-1"
    assert call.args[1] == CONTENT
    assert _arg_or_kw(call, "summary", 2, None) == "新摘要"


async def test_replace_content_summary_none_preserves() -> None:
    """【R】summary 缺省（None）→ repo.update_content 收 summary=None（保原值）。"""
    repo = AsyncMock()
    repo.get.return_value = _make_draft()
    repo.update_content.return_value = _make_draft()
    svc = DraftService(draft_repo=repo)

    await svc.replace_content("draft-1", CONTENT)

    call = repo.update_content.await_args
    assert _arg_or_kw(call, "summary", 2, None) is None


async def test_replace_content_does_not_touch_memory_service() -> None:
    """【R】replace_content 全程不调 memory_service（F28 零 diff，不走 update/record）。"""
    repo = AsyncMock()
    repo.get.return_value = _make_draft()
    repo.update_content.return_value = _make_draft()
    memory = AsyncMock()
    svc = DraftService(draft_repo=repo, memory_service=memory)

    await svc.replace_content("draft-1", CONTENT)

    memory.record_draft_edit.assert_not_awaited()
