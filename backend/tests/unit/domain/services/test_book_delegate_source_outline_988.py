"""#988 创建点回填 RED 契约 — BookService._delegate_chapter（书级顺序委托轨）.

被测: book_service.py:857 兜底建草稿调用。chapter 形参即 Outline 领域对象
（plan.volumes 消费链 _outline_to_chapter_dict / _chapters 同源，chapter.id
就是大纲节点 UUID）→ GREEN 必把 chapter.id 作为 source_outline_id 透传。

当前 create 调用不带该 kwarg → await_args.kwargs["source_outline_id"]
KeyError（RED）。fake 形态镜像 test_book_service.py._make_deps（fake agent
消息无 tool_calls → #975 守卫走兜底 create）。

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
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


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _outline(**overrides) -> Outline:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        name="第一章",
        description="主角在时间旅途中发现悖论",
        sort_order=0,
        level="chapter",
        parent_id=None,
        chapter_id=uuid.uuid4(),
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Outline(**base)


def _plan() -> WritingPlan:
    return WritingPlan(
        id=uuid.uuid4(),
        project_id=_pid(),
        title="来源锚定测试",
        status="running",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={"max_chapters": 100, "max_agent_calls": 200},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_deps(**overrides) -> dict:
    """镜像 test_book_service._make_deps：fake agent 消息无 tool_calls → 兜底 create。"""
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


async def test_book_service_delegate_passes_source_outline_id() -> None:
    """【R】_delegate_chapter → draft_service.create 收 source_outline_id=chapter.id."""
    deps = _make_deps()
    svc = BookService(**deps)
    plan = _plan()
    chapter = _outline(description="主角在时间旅途中发现悖论")

    execution_id = await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

    assert execution_id
    deps["draft_service"].create.assert_awaited_once()
    create_kwargs = deps["draft_service"].create.await_args.kwargs
    # 当前无该键 → KeyError（RED）；GREEN 后 = 章 Outline 节点 id
    assert create_kwargs["source_outline_id"] == chapter.id
    # 既有绑定语义守护（当前即成立）
    assert create_kwargs["chapter_id"] == chapter.chapter_id
