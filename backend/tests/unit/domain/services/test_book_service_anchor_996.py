"""#996 RED 契约测试 — BookService._delegate_chapter 锚点传递（静态轨委托点）.

契约真相源: specs/f44-book-orchestrator/spec.md §5.2「锚点传递（#996）」+ 拍板契约 I:
book_service._delegate_chapter 调用 writer_factory 新增 kwargs:
    expected_source_outline_id=chapter.id
    expected_volume_outline_id=chapter.parent_id

当前实现对照（RED）: book_service._delegate_chapter L827-831 只传 system_prompt /
expected_project_id / expected_chapter_id → writer_factory.await_args.kwargs 无两锚点键
（.get(...) 返回 None ≠ outline.id / outline.parent_id → 断言 FAILED）。

镜像 test_book_service.py _plan/_outline/_make_deps/_service 形态（静态轨章是 Outline 对象）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, WritingPlan
from inkflow.domain.services.book_service import BookService

pytestmark = pytest.mark.asyncio

VOLUME_OUTLINE_ID = uuid.UUID(int=41)


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        title="测试计划",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _outline(**overrides) -> Outline:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        name="第一章",
        description="主角在时间旅途中发现悖论",
        sort_order=0,
        level="chapter",
        parent_id=None,
        chapter_id=None,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Outline(**base)


def _make_deps(**overrides):
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    repo.update_writing_plan.return_value = None

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="第一章正文内容", tool_calls=[])]
    }
    writer_factory = AsyncMock(return_value=fake_agent)

    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)

    deps = dict(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
    )
    deps.update(overrides)
    return deps


def _service(**overrides) -> BookService:
    return BookService(**_make_deps(**overrides))


class TestBookServiceDelegateAnchorPassthrough:
    """BookService._delegate_chapter 静态轨锚点装配 kwargs（#996 契约 I-2）。"""

    async def test_delegate_chapter_passes_source_outline_anchor(self) -> None:
        """【R】writer_factory 收到 expected_source_outline_id == outline.id。

        当前实现不传该 kwarg → .get(...) 返回 None ≠ outline.id → FAILED。
        """
        plan = _plan()
        chapter = _outline(parent_id=VOLUME_OUTLINE_ID, description="测试章")
        deps = _make_deps()
        svc = BookService(**deps)

        await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

        call_kwargs = deps["writer_factory"].await_args.kwargs
        assert call_kwargs.get("expected_source_outline_id") == chapter.id
        assert call_kwargs.get("expected_project_id") == plan.project_id

    async def test_delegate_chapter_passes_volume_outline_anchor(self) -> None:
        """【R】writer_factory 收到 expected_volume_outline_id == outline.parent_id。

        当前实现不传该 kwarg → .get(...) 返回 None ≠ parent_id → FAILED。
        """
        plan = _plan()
        chapter = _outline(parent_id=VOLUME_OUTLINE_ID, description="测试章")
        deps = _make_deps()
        svc = BookService(**deps)

        await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

        call_kwargs = deps["writer_factory"].await_args.kwargs
        assert call_kwargs.get("expected_volume_outline_id") == chapter.parent_id

    async def test_delegate_chapter_no_parent_volume_anchor_none(self) -> None:
        """【R】outline.parent_id 为 None → writer_factory 收到 volume 锚点为 None。"""
        plan = _plan()
        chapter = _outline(parent_id=None, description="游离章")
        deps = _make_deps()
        svc = BookService(**deps)

        await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

        call_kwargs = deps["writer_factory"].await_args.kwargs
        assert call_kwargs.get("expected_volume_outline_id") is None
        assert call_kwargs.get("expected_source_outline_id") == chapter.id
