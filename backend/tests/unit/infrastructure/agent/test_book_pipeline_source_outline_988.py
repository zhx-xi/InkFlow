"""#988 创建点回填 RED 契约 — F44 卷轨（BookVolumePipeline._delegate_chapter）.

被测: book_pipeline.py:488 兜底建草稿调用。章 dict 恒含 outline_id
（_outline_to_chapter_dict 产物，L503 usage 事件同键实证）→ GREEN 必把
chapter["outline_id"] 作为 source_outline_id 透传给 draft_service.create。

当前 create 调用不带该 kwarg → await_args.kwargs["source_outline_id"]
KeyError（RED）。fake 形态镜像 test_book_pipeline.py（AsyncMock draft_service，
fake agent 返回无 tool_calls 消息 → #975 守卫走兜底 create）。

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

pytestmark = pytest.mark.asyncio


def _chapter(**overrides) -> dict:
    """构造章 dict（镜像 test_book_pipeline._chapter）。"""
    base = {
        "outline_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "name": "第一章",
        "description": "主角在时间旅途中发现悖论",
        "sort_order": 0,
    }
    base.update(overrides)
    return base


def _volume(chapters, **overrides) -> dict:
    """构造卷 dict（镜像 test_book_pipeline._volume）。"""
    base = {"volume_id": uuid.uuid4(), "chapters": chapters}
    base.update(overrides)
    return base


def _plan(**overrides) -> WritingPlan:
    """构造 WritingPlan（镜像 test_book_pipeline._plan）。"""
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "卷轨来源锚定测试",
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


async def test_volume_delegate_create_passes_source_outline_id() -> None:
    """【R】一卷一章端到端 → draft_service.create 收 source_outline_id=章 outline_id."""
    chapters = [_chapter()]
    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="正文")],
        "usage": {"total_tokens": 100},
    }
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    pipeline = BookVolumePipeline(
        AsyncMock(),
        writer_factory=writer_factory,
        draft_service=draft_service,
        retry_limit=2,
        checkpointer=InMemorySaver(),
    )
    result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())

    assert result["status"] == "completed"
    assert draft_service.create.await_count == 1
    create_kwargs = draft_service.create.await_args.kwargs
    # 当前无该键 → KeyError（RED）；GREEN 后 = 章 dict 的 outline_id
    assert create_kwargs["source_outline_id"] == chapters[0]["outline_id"]
    # 既有绑定语义守护（当前即成立，防 GREEN 回归）
    assert create_kwargs["chapter_id"] == chapters[0]["chapter_id"]
