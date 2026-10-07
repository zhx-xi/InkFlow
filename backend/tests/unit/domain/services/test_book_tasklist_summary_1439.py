"""#1439 supervisor 任务清单 —— ``get_summary`` 附加键 + ``steps`` 契约不变 RED 契约。

设计真相源：``specs/f44-book-orchestrator/spec.md`` §5.9 + §12 D15 + §13.8 M22
+ §9.2 场景 15。

契约（本文件锁定）：

A. **GUI 复用**：``get_summary`` 返回值新增**附加键** ``tasklist``（supervisor 计划面），
   与 ``steps``（实际面）并列 → 「计划 vs 实际」可对照。
B. **``steps`` 契约逐字不变**：条目键集恒为
   ``{index, outline_id, name, status, execution_id, volume_name, substeps}``
   （#1333 段 2 正式契约，零回归）。
C. **既有轨零回归**：静态 / 卷级轨 ``tasklist`` 为空、``steps[].substeps`` 恒 ``[]``。
D. **落库接线**：``BookService.write_book_agentic`` 把 pipeline 留在 ``plan.tasklist``
   的清单随 ``update_writing_plan`` 落库。

RED 预期：``get_summary`` 无 ``tasklist`` 键 → KeyError FAIL；存储字段不存在 →
``WritingPlan(tasklist=...)`` Pydantic 忽略/AttributeError FAIL。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService

pytestmark = pytest.mark.asyncio

_PLAN_ID = uuid.UUID("01920000-0000-7000-8000-00000000f143")
_PROJECT_ID = uuid.UUID("01920000-0000-7000-8000-000000000001")
_VOLUME_ID = uuid.UUID("01920000-0000-7000-8000-00000000aa01")
_CH1_ID = uuid.UUID("01920000-0000-7000-8000-00000000aa02")
_CH2_ID = uuid.UUID("01920000-0000-7000-8000-00000000aa03")

_STEPS_KEYS = {
    "index",
    "outline_id",
    "name",
    "status",
    "execution_id",
    "volume_name",
    "substeps",
}


def _outline(
    oid: uuid.UUID, *, name: str, level: str = "chapter", parent_id: uuid.UUID | None = None
) -> Outline:
    now = datetime.now(UTC)
    return Outline(
        id=oid,
        project_id=_PROJECT_ID,
        name=name,
        description="",
        level=level,
        sort_order=0,
        parent_id=parent_id,
        chapter_id=uuid.uuid4() if level == "chapter" else None,
        created_at=now,
        updated_at=now,
    )


def _plan(**overrides) -> WritingPlan:
    base: dict = dict(
        id=_PLAN_ID,
        project_id=_PROJECT_ID,
        title="测试计划",
        status="ready",
        root_outline_id=_VOLUME_ID,
        character_ids=[],
        limits={"max_chapters": 10, "max_agent_calls": 20},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _service(
    *, plan: WritingPlan, outlines: list[Outline] | None = None, **overrides
) -> BookService:
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    repo.update_writing_plan.return_value = None
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (outlines if outlines is not None else [], 0)
    deps: dict = dict(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=BookLimits(),
    )
    deps.update(overrides)
    return BookService(**deps)


# ══════════════════════════════════════════════════════════════════════
# A. 附加键 tasklist（「计划 vs 实际」）
# ══════════════════════════════════════════════════════════════════════


async def test_get_summary_exposes_tasklist_additive_key() -> None:
    """summary 含附加键 tasklist（supervisor 计划面），与 steps 并列。"""
    tasklist = [{"op": "write_chapter", "outline_id": str(_CH1_ID), "title": "开端"}]
    plan = _plan(
        progress={str(_CH1_ID): "done"},
        thread_id=str(_PLAN_ID),
        tasklist=list(tasklist),
    )
    svc = _service(plan=plan, outlines=[_outline(_CH1_ID, name="开端")])

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    assert result["tasklist"] == tasklist
    # 「计划 vs 实际」并列：steps 仍是实际执行面
    assert [s["status"] for s in result["steps"]] == ["done"]


async def test_get_summary_tasklist_empty_when_absent() -> None:
    """未跑 supervisor（无清单）→ tasklist == []（不造假计划）。"""
    plan = _plan(progress={str(_CH1_ID): "pending"})
    svc = _service(plan=plan, outlines=[_outline(_CH1_ID, name="开端")])

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    assert result["tasklist"] == []


# ══════════════════════════════════════════════════════════════════════
# B. steps 契约逐字不变（#1333 段 2）
# ══════════════════════════════════════════════════════════════════════


async def test_get_summary_steps_key_set_unchanged() -> None:
    """steps 条目键集与 #1333 段 2 契约逐字一致（新增 tasklist 不改 steps 形状）。"""
    plan = _plan(progress={str(_CH1_ID): "done"})
    svc = _service(plan=plan, outlines=[_outline(_CH1_ID, name="开端")])

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    assert set(result["steps"][0].keys()) == _STEPS_KEYS


# ══════════════════════════════════════════════════════════════════════
# C. 既有轨零回归（静态 / 卷级轨）
# ══════════════════════════════════════════════════════════════════════


async def test_static_track_tasklist_empty_and_substeps_empty() -> None:
    """静态轨（无 agentic checkpoint）→ tasklist == [] 且 steps[].substeps 恒 []。"""
    plan = _plan(progress={str(_CH1_ID): "done", str(_CH2_ID): "pending"})
    svc = _service(
        plan=plan,
        outlines=[_outline(_CH1_ID, name="开端"), _outline(_CH2_ID, name="转折")],
    )

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    assert result["tasklist"] == []
    assert all(step["substeps"] == [] for step in result["steps"])


# ══════════════════════════════════════════════════════════════════════
# D. 落库接线：write_book_agentic 持久化 pipeline 留下的 tasklist
# ══════════════════════════════════════════════════════════════════════


async def test_write_book_agentic_persists_tasklist_left_by_pipeline() -> None:
    """pipeline.execute 在 plan 上写的 tasklist → 随 update_writing_plan 落库。"""
    plan = _plan(status="running")
    produced = [{"op": "write_chapter", "outline_id": str(_CH1_ID), "title": "开端"}]

    class _FakePipeline:
        def __init__(self) -> None:
            self.plan_seen: WritingPlan | None = None

        async def execute(self, plan_arg, chapters, limits, *, config=None, thread_id=None):
            self.plan_seen = plan_arg
            plan_arg.tasklist = list(produced)
            return {"run_id": thread_id or "", "status": "completed", "thread_id": thread_id}

        async def get_checkpoint_state(self, run_id):
            """契约同名鸭子方法：无 checkpoint（隐式返回 None）。"""
            return

    pipeline = _FakePipeline()
    svc = _service(plan=plan, outlines=[], agentic_pipeline=pipeline)

    await svc.write_book_agentic(_PLAN_ID)

    assert pipeline.plan_seen is not None
    assert plan.tasklist == produced
    # 落库：update_writing_plan 收到带 tasklist 的 plan
    persisted = svc._repo.update_writing_plan.await_args.args[0]
    assert persisted.tasklist == produced
