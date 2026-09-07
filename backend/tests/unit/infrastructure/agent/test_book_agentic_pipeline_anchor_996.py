"""#996 RED 契约测试 — BookAgenticPipeline._delegate_write 锚点传递（agentic 轨委托点）.

契约真相源: specs/f44-book-orchestrator/spec.md §5.2「锚点传递（#996）」+ 拍板契约 I:
book_agentic_pipeline._delegate_write 调用 writer_factory 新增 kwargs:
    expected_source_outline_id=chapter["outline_id"]
    expected_volume_outline_id=chapter.get("volume_outline_id")

当前实现对照（RED）: book_agentic_pipeline._delegate_write L775-779 只传 system_prompt /
expected_project_id / expected_chapter_id → writer_factory 记录 kwargs 无两锚点键
（.get(...) 返回 None ≠ 章 outline_id / volume_outline_id → 断言 FAILED）。

镜像 test_book_agentic_pipeline.py 的 FakeWriterFactory/FakeDraftService 形态，直接 await
pipeline._delegate_write(chapter_dict)（不跑整个 LangGraph 图）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

pytestmark = pytest.mark.asyncio

OUTLINE_ID = uuid.UUID(int=51)
CHAPTER_ID = uuid.UUID(int=8)
VOLUME_OUTLINE_ID = uuid.UUID(int=41)
TEXT = "第一章 正文。本测试锁定 agentic 轨委托点锚点传递契约。"


class _FakeAgent:
    def __init__(self, content: str) -> None:
        self._content = content

    async def invoke(self, messages, config=None):
        return {"messages": [{"role": "assistant", "content": self._content}]}


class FakeWriterFactory:
    """记录 writer_factory 逐次 kwargs（镜像 test_book_agentic_pipeline.py FakeWriterFactory）。"""

    def __init__(self, content: str = TEXT) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeAgent(self.content)


class FakeDraftService:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))


def _chapter(**overrides) -> dict:
    """构造章 dict（ChapterDict 形态，含 volume_outline_id）. """
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


def _plan_obj():
    """WritingPlan 鸭子对象（_delegate_write 只消费 project_id/character_ids）. """
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        character_ids=[],
    )


def _pipeline() -> tuple[BookAgenticPipeline, FakeWriterFactory, FakeDraftService]:
    wf = FakeWriterFactory()
    ds = FakeDraftService()
    pipeline = BookAgenticPipeline(
        AsyncMock(),
        writer_factory=wf,
        draft_service=ds,
        checkpointer=None,
    )
    pipeline._plan = _plan_obj()
    return pipeline, wf, ds


class TestBookAgenticDelegateWriteAnchorPassthrough:
    """BookAgenticPipeline._delegate_write 委托点锚点装配 kwargs（#996 契约 I-3）。"""

    async def test_delegate_write_passes_source_outline_anchor(self) -> None:
        """【R】writer_factory 收到 expected_source_outline_id == chapter["outline_id"]。

        当前实现不传该 kwarg → wf.calls[-1].get(...) 返回 None ≠ OUTLINE_ID → FAILED。
        """
        pipeline, wf, _ds = _pipeline()

        await pipeline._delegate_write(_chapter())

        assert wf.calls
        call_kwargs = wf.calls[-1]
        assert call_kwargs.get("expected_source_outline_id") == OUTLINE_ID
        assert call_kwargs.get("expected_project_id") == pipeline._plan.project_id

    async def test_delegate_write_passes_volume_outline_anchor(self) -> None:
        """【R】writer_factory 收到 expected_volume_outline_id == chapter["volume_outline_id"].

        当前实现不传该 kwarg → wf.calls[-1].get(...) 返回 None ≠ VOLUME_OUTLINE_ID → FAILED。
        """
        pipeline, wf, _ds = _pipeline()

        await pipeline._delegate_write(_chapter())

        assert wf.calls
        call_kwargs = wf.calls[-1]
        assert call_kwargs.get("expected_volume_outline_id") == VOLUME_OUTLINE_ID

    async def test_delegate_write_no_volume_outline_anchor_none(self) -> None:
        """【R】章 dict 无 volume_outline_id 键 → writer_factory 收到 volume 锚点为 None。"""
        pipeline, wf, _ds = _pipeline()

        await pipeline._delegate_write(_chapter(volume_outline_id=None))

        assert wf.calls
        call_kwargs = wf.calls[-1]
        assert call_kwargs.get("expected_volume_outline_id") is None
        assert call_kwargs.get("expected_source_outline_id") == OUTLINE_ID
