"""#1333 段 2 —— 自动写作任务看板后端契约（RED 先行）。

设计真相源：``specs/f19-gui/book.md`` §3（状态语义 / 数据面 / 实时通道）+ §4 N14-N26。

本文件锁定四组契约：

A. **任务视图数据面**（§3.2 Q4=③，零 DDL）
   ``get_summary.steps[]`` 升级为任务视图契约：在既有
   ``{index, outline_id, status, execution_id}`` 上补
   - ``name``       章名（outline join；取不到 → 回退 ``outline_id``，绝不缺键）
   - ``volume_name`` 所属卷名（无卷归属 → None）
   - ``substeps``   章内步骤（**仅 agentic 轨非空**；静态 / 卷级轨恒 ``[]``）
   顺序恒等 ``plan.progress.keys()``（既有契约不变）。

B. **状态语义完整性**（§3.3 · 修 D-3）
   run ``blocked``（#1267 审计阻断）时 ``progress_reason`` 必须对用户可见：
   ``get_status`` / ``get_summary`` 的 reason 门控由 ``{failed, degraded}``
   扩为 ``{failed, degraded, blocked}``。**否则前端无论怎么改都拿不到原因**
   （设计轨 §3.4 D-3 只记了前端门控，后端门控是同一缺陷的另一半）。

C. **实时通道发布点**（§3.2 Q3/Q4-D2 · N22）
   book run 状态跃迁写路径末尾发布 ``publish_change("writing_plan", "update",
   plan.id, plan.project_id)`` —— 统一走 ``book_run_mixin._publish_run_change``
   （单一 patch 目标）。

D. **重复启动拒绝**（§3.5-7 · N25）
   同一计划重复启动 → ``RunAlreadyActiveError``（``ValueError`` 子类，
   兼容既有 ``pytest.raises(ValueError, match="运行已在进行中")``）→ API 409。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService, RunAlreadyActiveError

_PLAN_ID = uuid.UUID("01920000-0000-7000-8000-000000001333")
_PROJECT_ID = uuid.UUID("01920000-0000-7000-8000-000000001334")
_VOLUME_ID = uuid.UUID("01920000-0000-7000-8000-000000001335")
_CH1_ID = uuid.UUID("01920000-0000-7000-8000-000000001336")
_CH2_ID = uuid.UUID("01920000-0000-7000-8000-000000001337")
_PUBLISH_TARGET = "inkflow.domain.services.book_run_mixin.publish_change"


def _outline(
    oid: uuid.UUID,
    *,
    name: str,
    level: str = "chapter",
    parent_id: uuid.UUID | None = None,
    sort_order: int = 0,
) -> Outline:
    now = datetime.now(UTC)
    return Outline(
        id=oid,
        project_id=_PROJECT_ID,
        name=name,
        description="",
        level=level,
        sort_order=sort_order,
        parent_id=parent_id,
        chapter_id=uuid.uuid4() if level == "chapter" else None,
        created_at=now,
        updated_at=now,
    )


def _plan(**overrides) -> WritingPlan:
    base = dict(
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
# A. 任务视图数据面（N14 / N15）
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_summary_steps_carry_chapter_name_and_volume_name() -> None:
    """steps[] 补 name（章名，join outline）+ volume_name（所属卷名）。

    N14：任务行必须能显示章名，不得只显示 outline_id。
    """
    outlines = [
        _outline(_VOLUME_ID, name="第一卷", level="volume"),
        _outline(_CH1_ID, name="开端", parent_id=_VOLUME_ID, sort_order=0),
        _outline(_CH2_ID, name="转折", parent_id=_VOLUME_ID, sort_order=1),
    ]
    plan = _plan(progress={str(_CH1_ID): "done", str(_CH2_ID): "pending"})
    svc = _service(plan=plan, outlines=outlines)

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    steps = result["steps"]
    assert [s["outline_id"] for s in steps] == [str(_CH1_ID), str(_CH2_ID)]
    assert steps[0]["name"] == "开端"
    assert steps[1]["name"] == "转折"
    assert steps[0]["volume_name"] == "第一卷"
    assert steps[1]["volume_name"] == "第一卷"


@pytest.mark.asyncio
async def test_get_summary_steps_name_falls_back_to_outline_id() -> None:
    """outline 取不到 → name 回退 outline_id（键恒在，绝不缺键）；volume_name = None。"""
    plan = _plan(progress={"01920000-0000-7000-8000-00000000abcd": "pending"})
    svc = _service(plan=plan, outlines=[])

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    step = result["steps"][0]
    assert step["name"] == "01920000-0000-7000-8000-00000000abcd"
    assert step["volume_name"] is None


@pytest.mark.asyncio
async def test_get_summary_steps_substeps_empty_without_agentic_pipeline() -> None:
    """静态 / 卷级轨（无 agentic_pipeline）→ substeps 恒 []（N15：不渲染展开入口）。"""
    plan = _plan(progress={str(_CH1_ID): "done", str(_CH2_ID): "in_progress"})
    svc = _service(plan=plan, outlines=[])

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    assert all(step["substeps"] == [] for step in result["steps"])


@pytest.mark.asyncio
async def test_get_summary_steps_substeps_derived_for_agentic_track() -> None:
    """agentic 轨（checkpoint 有 route_history）→ substeps 两档（done / now），
    op 取值 ⊆ {write_chapter, audit_chapter, revise_chapter, mark_done}（§3.3）。

    N15：章内步骤仅当该轨提供子步骤时非空。
    """
    agentic = AsyncMock()
    agentic.get_checkpoint_state.return_value = {
        "route_history": ["write_chapter", "audit_chapter"],
        "audit_results": {},
        "results": {},
    }
    plan = _plan(
        progress={str(_CH1_ID): "done", str(_CH2_ID): "in_progress"},
        thread_id=str(_PLAN_ID),
    )
    svc = _service(plan=plan, outlines=[], agentic_pipeline=agentic)

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    done_step, running_step = result["steps"]
    allowed_ops = {"write_chapter", "audit_chapter", "revise_chapter", "mark_done"}
    assert done_step["substeps"], "agentic 轨的已完成章必须带章内步骤"
    assert {s["op"] for s in done_step["substeps"]} <= allowed_ops
    assert {s["status"] for s in done_step["substeps"]} == {"done"}
    assert running_step["substeps"], "agentic 轨的进行中章必须有「当前动作」"
    assert any(s["status"] == "now" for s in running_step["substeps"])
    assert {s["op"] for s in running_step["substeps"]} <= allowed_ops


@pytest.mark.asyncio
async def test_get_summary_steps_substeps_empty_when_agentic_state_absent() -> None:
    """agentic_pipeline 装配但 checkpoint 无状态（卷级/静态跑法）→ substeps 仍为 []。"""
    agentic = AsyncMock()
    agentic.get_checkpoint_state.return_value = None
    plan = _plan(progress={str(_CH1_ID): "done"}, thread_id=str(_PLAN_ID))
    svc = _service(plan=plan, outlines=[], agentic_pipeline=agentic)

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    assert result["steps"][0]["substeps"] == []


# ══════════════════════════════════════════════════════════════════════
# B. 状态语义完整性：blocked 时原因可见（修 D-3）
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_status_exposes_progress_reason_when_blocked() -> None:
    """run=blocked（#1267 审计阻断）→ progress_reason 必须透出（不得被门控吞掉）。"""
    plan = _plan(
        status="blocked",
        progress={str(_CH1_ID): "needs_review"},
        progress_reason="第四章：审计阻断（人设漂移 severity=error）",
    )
    svc = _service(plan=plan, outlines=[])

    result = await svc.get_status(str(_PLAN_ID))

    assert result is not None
    assert result["progress_reason"] == "第四章：审计阻断（人设漂移 severity=error）"


@pytest.mark.asyncio
async def test_get_summary_exposes_progress_reason_when_blocked() -> None:
    """get_summary 同族门控同步放宽（否则 GUI 摘要/任务列表拿不到阻断原因）。"""
    plan = _plan(
        status="blocked",
        progress={str(_CH1_ID): "needs_review"},
        progress_reason="审计阻断原因占位",
    )
    svc = _service(plan=plan, outlines=[])

    result = await svc.get_summary(str(_PLAN_ID))

    assert result is not None
    assert result["progress_reason"] == "审计阻断原因占位"


@pytest.mark.asyncio
async def test_reason_gate_still_hides_for_running_and_completed() -> None:
    """反例守护：门控放宽只加 blocked —— running / completed 仍不透出陈旧 reason。"""
    for status in ("running", "completed"):
        plan = _plan(
            status=status,
            progress={str(_CH1_ID): "done"},
            progress_reason="陈旧值（不应透出）",
        )
        svc = _service(plan=plan, outlines=[])
        result = await svc.get_status(str(_PLAN_ID))
        assert result is not None
        assert result["progress_reason"] is None


# ══════════════════════════════════════════════════════════════════════
# C. 实时通道发布点（N22）
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_prepare_run_publishes_writing_plan_change() -> None:
    """启动（ready → running）落库后发布 writing_plan/update（项目域）。"""
    plan = _plan(status="ready")
    svc = _service(plan=plan, outlines=[])

    async def _find_chapters_stub(_plan: WritingPlan) -> list[Outline]:
        return [_outline(_CH1_ID, name="开端")]

    svc._find_chapters = _find_chapters_stub  # type: ignore[method-assign]  # 测试注入章节点替身（#1430 同法）
    svc._content_checker = AsyncMock(return_value=False)

    with patch(_PUBLISH_TARGET, new_callable=AsyncMock) as publish:
        await svc.prepare_run(_PLAN_ID, mode="static")

    publish.assert_awaited()
    assert publish.await_args is not None
    assert publish.await_args.args[:4] == (
        "writing_plan",
        "update",
        str(_PLAN_ID),
        _PROJECT_ID,
    )


@pytest.mark.asyncio
async def test_mark_failed_publishes_writing_plan_change() -> None:
    """后台异常兜底置 failed 后发布（否则 GUI 看不到跃迁）。"""
    plan = _plan(status="running")
    svc = _service(plan=plan, outlines=[])

    with patch(_PUBLISH_TARGET, new_callable=AsyncMock) as publish:
        await svc.mark_failed(str(_PLAN_ID))

    publish.assert_awaited()
    assert publish.await_args is not None
    assert publish.await_args.args[:4] == (
        "writing_plan",
        "update",
        str(_PLAN_ID),
        _PROJECT_ID,
    )


@pytest.mark.asyncio
async def test_reset_run_publishes_writing_plan_change() -> None:
    """reset（→ ready）后发布，GUI 才能收回任务列表。"""
    plan = _plan(status="completed", progress={str(_CH1_ID): "done"})
    svc = _service(plan=plan, outlines=[])

    with patch(_PUBLISH_TARGET, new_callable=AsyncMock) as publish:
        await svc.reset_run(str(_PLAN_ID))

    publish.assert_awaited()
    assert publish.await_args is not None
    assert publish.await_args.args[:4] == (
        "writing_plan",
        "update",
        str(_PLAN_ID),
        _PROJECT_ID,
    )


# ══════════════════════════════════════════════════════════════════════
# D. 重复启动拒绝（N25）
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_prepare_run_duplicate_start_raises_run_already_active() -> None:
    """同一计划重复启动（status == running）→ RunAlreadyActiveError（ValueError 子类）。"""
    plan = _plan(status="running")
    svc = _service(plan=plan, outlines=[])

    with pytest.raises(RunAlreadyActiveError, match="运行已在进行中"):
        await svc.prepare_run(_PLAN_ID, mode="static")


def test_run_already_active_error_is_value_error_subclass() -> None:
    """兼容守护：既有 ``pytest.raises(ValueError, match="运行已在进行中")`` 不得破。"""
    assert issubclass(RunAlreadyActiveError, ValueError)
