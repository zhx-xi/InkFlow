"""Coverage backfill batch 2: BookRunMixin 收尾/同步分支。

经公开 BookService 方法驱动：
- write_book_agentic 非 completed 状态 -> 直接落库不再收尾演化（323->332）
- resume_run 中 checkpoint 同步读取抛异常 -> 静默跳过（237-239）
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


def _plan(*, status: str = "running", thread_id: str | None = None) -> WritingPlan:
    now = datetime.now(UTC)
    return WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="测试计划",
        status=status,
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={
            "max_chapters": 100,
            "max_agent_calls": 200,
            "max_tokens": 200_000,
            "tokens_used": 0,
            "tokens_warning": False,
        },
        progress={},
        execution_refs={},
        thread_id=thread_id,
        created_at=now,
        updated_at=now,
    )


def _chapter(plan: WritingPlan, sort_order: int) -> Outline:
    now = datetime.now(UTC)
    return Outline(
        id=uuid.uuid4(),
        project_id=plan.project_id,
        name=f"第{sort_order + 1}章",
        description="",
        sort_order=sort_order,
        level="chapter",
        parent_id=plan.root_outline_id,
        chapter_id=uuid.uuid4(),
        extra={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_write_book_agentic_non_completed_status_skips_finalize() -> None:
    """pipeline 返回 failed -> 按 result.status 落库，不收尾重演化（323->332）。"""
    plan = _plan()
    chapter = _chapter(plan, 0)
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([chapter], 1)
    agentic_pipeline = SimpleNamespace(
        execute=AsyncMock(return_value={"status": "failed"})
    )
    svc = BookService(
        repo=repo,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        agentic_pipeline=agentic_pipeline,
    )

    result = await svc.write_book_agentic(plan.id)

    assert result == {"run_id": str(plan.id), "status": "failed"}
    assert plan.status == "failed"
    repo.update_writing_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_run_swallows_checkpoint_sync_error() -> None:
    """resume 再次中断时 checkpoint 读取抛异常 -> 静默跳过仍落 waiting_hitl（237-239）。"""
    from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

    plan = _plan(status="paused", thread_id="t-1")
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)

    class _FlakyPipeline:
        def __init__(self) -> None:
            self.calls = 0

        async def get_checkpoint_state(self, thread_id: str):
            self.calls += 1
            if self.calls == 1:
                return {"results": {}}
            raise RuntimeError("checkpoint boom")

        async def execute(self, plan, volumes, merged, *, thread_id=None):
            raise VolumeHITLInterrupt({"volume": "v1"})

    svc = BookService(
        repo=repo,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        volume_pipeline=_FlakyPipeline(),
    )

    result = await svc.resume_run(str(plan.id))

    assert result["status"] == "waiting_hitl"
    assert plan.status == "waiting_hitl"
