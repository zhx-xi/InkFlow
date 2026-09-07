"""#996 RED 契约测试 — BookVolumePipeline._delegate_chapter 锚点传递（委托点一）.

契约真相源: specs/f44-book-orchestrator/spec.md §5.2「锚点传递（#996）」+ 拍板契约 I:
book_pipeline._delegate_chapter 调用 writer_factory 新增 kwargs:
    expected_source_outline_id=chapter["outline_id"]
    expected_volume_outline_id=chapter.get("volume_outline_id")

当前实现对照（RED）: book_pipeline._delegate_chapter L470-474 只传 system_prompt /
expected_project_id / expected_chapter_id → writer_factory.await_args.kwargs 无两锚点键
（.get(...) 返回 None ≠ 章 outline_id / volume_outline_id → 断言 FAILED）。

镜像 test_book_pipeline.py _plan/_make_deps 形态，直接 await pipeline._delegate_chapter(chapter)
（不跑整个 LangGraph 图，聚焦委托点装配 kwargs 契约）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

pytestmark = pytest.mark.asyncio

OUTLINE_ID = uuid.UUID(int=51)
CHAPTER_ID = uuid.UUID(int=8)
VOLUME_OUTLINE_ID = uuid.UUID(int=41)
TEXT = "第一章 正文。本测试锁定委托点锚点传递契约。"


def _plan(**overrides):
    """构造 WritingPlan（镜像 test_book_pipeline.py _plan）。"""
    from inkflow.domain.models.writing_plan import WritingPlan

    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "卷级编排测试",
        "status": "running",
        "root_outline_id": uuid.uuid4(),
        "character_ids": [],
        "limits": {"max_chapters": 100, "max_agent_calls": 200},
        "progress": {},
        "execution_refs": {},
        "thread_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return WritingPlan(**base)


def _chapter(**overrides) -> dict:
    """构造章 dict（ChapterDict 形态，含 volume_outline_id）."""
    base = {
        "outline_id": OUTLINE_ID,
        "chapter_id": CHAPTER_ID,
        "name": "第一章",
        "description": "主角在时间旅途中发现悖论",
        "sort_order": 0,
        "volume_outline_id": VOLUME_OUTLINE_ID,
    }
    base.update(overrides)
    return base


def _make_deps(**overrides):
    """构造委托依赖（writer_factory 恒成功返回 fake agent）."""
    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content=TEXT)],
        "usage": {"total_tokens": 100},
    }
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")
    deps = {
        "llm_client": AsyncMock(),
        "writer_factory": writer_factory,
        "draft_service": draft_service,
        "agent": fake_agent,
    }
    deps.update(overrides)
    return deps


def _pipeline(deps: dict) -> BookVolumePipeline:
    return BookVolumePipeline(
        deps["llm_client"],
        writer_factory=deps["writer_factory"],
        draft_service=deps["draft_service"],
        checkpointer=None,
    )


class TestDelegateChapterAnchorPassthrough:
    """BookVolumePipeline._delegate_chapter 委托点锚点装配 kwargs（#996 契约 I-1）。"""

    async def test_delegate_chapter_passes_source_outline_anchor(self) -> None:
        """【R】writer_factory 收到 expected_source_outline_id == chapter["outline_id"]。

        当前实现不传该 kwarg → .get(...) 返回 None ≠ OUTLINE_ID → FAILED。
        """
        deps = _make_deps()
        pipeline = _pipeline(deps)
        pipeline._plan = _plan()
        chapter = _chapter()

        await pipeline._delegate_chapter(chapter)

        call_kwargs = deps["writer_factory"].await_args.kwargs
        assert call_kwargs.get("expected_source_outline_id") == OUTLINE_ID
        assert call_kwargs.get("expected_project_id") == pipeline._plan.project_id

    async def test_delegate_chapter_passes_volume_outline_anchor(self) -> None:
        """【R】writer_factory 收到 expected_volume_outline_id == chapter["volume_outline_id"].

        当前实现不传该 kwarg → .get(...) 返回 None ≠ VOLUME_OUTLINE_ID → FAILED。
        """
        deps = _make_deps()
        pipeline = _pipeline(deps)
        pipeline._plan = _plan()
        chapter = _chapter()

        await pipeline._delegate_chapter(chapter)

        call_kwargs = deps["writer_factory"].await_args.kwargs
        assert call_kwargs.get("expected_volume_outline_id") == VOLUME_OUTLINE_ID

    async def test_delegate_chapter_no_volume_outline_anchor_none(self) -> None:
        """【R】章 dict 无 volume_outline_id 键 → writer_factory 收到 volume 锚点为 None。"""
        deps = _make_deps()
        pipeline = _pipeline(deps)
        pipeline._plan = _plan()
        chapter = _chapter(volume_outline_id=None)

        await pipeline._delegate_chapter(chapter)

        call_kwargs = deps["writer_factory"].await_args.kwargs
        assert call_kwargs.get("expected_volume_outline_id") is None
        assert call_kwargs.get("expected_source_outline_id") == OUTLINE_ID
