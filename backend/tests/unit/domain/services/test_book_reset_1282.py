"""#1282 书级运行重置出口（方案 B）：不删正文的重跑入口契约。

issue #1282 背景：#1265 解耦安全闸判据后，「重跑」的唯一途径仍是破坏性操作
（删章节正文）。issue 倾向方案 B —— 提供显式 reset 出口，与既有安全闸共存：

- reset 只清**执行态**（``progress`` / ``execution_refs``）并退回 ``ready``；
- **不动** ``chapters.content`` / ``drafts``（方案 B 的核心优势：用户自己处理旧正文）；
- 语义仍受安全闸约束：正文仍在 → reset 后重跑依旧被 content_checker 拦住，
  reset 不是「静默覆盖」（方案 A 的取舍，本 issue 明确不做）。

可证伪自证：不调 reset 时，同一 plan 的 prepare_run 必须抛
ChapterAlreadyWrittenError（见 test_prepare_run_without_reset_rejected）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService, ChapterAlreadyWrittenError

_PLAN_ID = uuid.UUID("01920000-0000-7000-8000-000000000282")
_PROJECT_ID = uuid.UUID("01920000-0000-7000-8000-000000000283")
_CHAPTER_ID = uuid.UUID("01920000-0000-7000-8000-000000000284")
_OUTLINE_ID = uuid.UUID("01920000-0000-7000-8000-000000000285")


def _chapter() -> Outline:
    """目标章节点（level=chapter，挂 chapter_id → content_checker 参与判据）。"""
    now = datetime.now(UTC)
    return Outline(
        id=_OUTLINE_ID,
        project_id=_PROJECT_ID,
        name="第一章",
        description="开篇",
        level="chapter",
        sort_order=1,
        chapter_id=_CHAPTER_ID,
        created_at=now,
        updated_at=now,
    )


def _plan() -> WritingPlan:
    """跑过一轮的 plan：progress/execution_refs 有痕（reset 的清除对象）。"""
    return WritingPlan(
        id=_PLAN_ID,
        project_id=_PROJECT_ID,
        title="测试书",
        status="completed",
        progress={str(_OUTLINE_ID): "done"},
        execution_refs={str(_OUTLINE_ID): "exec-001"},
        limits={"max_chapters": 100, "max_agent_calls": 200},
    )


async def _find_chapters_stub(_plan: object) -> list[Outline]:
    """章节点解析替身：返回固定章列表，使安全闸判据完全由 content_checker 决定。"""
    return [_chapter()]


async def _build_service(*, content_written: bool) -> tuple[BookService, AsyncMock]:
    """装配 BookService：repo 返回同一 plan 实例，content_checker 由参数驱动。

    ``_find_chapters`` 用朴素协程替身（而非 ``AsyncMock``）：作用域仅限本文件，
    让 ``prepare_run`` 的章节点来源确定，闸门结论只取决于 ``content_checker``。
    """
    plan = _plan()
    repo = AsyncMock()
    repo.get_writing_plan = AsyncMock(return_value=plan)
    repo.update_writing_plan = AsyncMock()
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=AsyncMock(),
        limits=BookLimits(),
        content_checker=AsyncMock(return_value=content_written),
    )
    svc._find_chapters = _find_chapters_stub  # type: ignore[method-assign]  # 章节点解析出 DB，测试注入替身
    return svc, repo


@pytest.mark.asyncio
async def test_reset_clears_execution_state() -> None:
    """reset 清空 progress / execution_refs 并落库（execute 态归零）。"""
    svc, repo = await _build_service(content_written=True)

    result = await svc.reset_run(str(_PLAN_ID))

    plan = repo.get_writing_plan.return_value
    assert plan.progress == {}
    assert plan.execution_refs == {}
    assert result["status"] == "ready"
    repo.update_writing_plan.assert_awaited()


@pytest.mark.asyncio
async def test_reset_returns_plan_to_ready() -> None:
    """plan 状态退回 ready（planner 完成态 = 可执行态，状态机自洽）。"""
    svc, repo = await _build_service(content_written=True)

    result = await svc.reset_run(str(_PLAN_ID))

    assert result["run_id"] == str(_PLAN_ID)
    assert result["status"] == "ready"
    assert repo.get_writing_plan.return_value.status == "ready"


@pytest.mark.asyncio
async def test_reset_does_not_touch_chapters_or_drafts() -> None:
    """反向断言（本方案核心）：reset 不碰 drafts/chapters —— 零 draft_service 调用。

    方案 B 的语义边界：用户自己处理旧正文；reset 只重置编排态。
    """
    svc, repo = await _build_service(content_written=True)

    await svc.reset_run(str(_PLAN_ID))

    svc._draft_service.assert_not_called()  # type: ignore[attr-defined]  # 鸭子属性：BookService 持有 draft_service
    # plan 上除执行态外的编排元数据原样保留（limits/title/status 之外的字段不被顺手清）
    plan = repo.get_writing_plan.return_value
    assert plan.limits == {"max_chapters": 100, "max_agent_calls": 200}
    assert plan.title == "测试书"


@pytest.mark.asyncio
async def test_prepare_run_after_reset_rejected_when_content_still_there() -> None:
    """reset 不绕过安全闸：正文仍在（content_checker=True）→ 重跑仍被拒。

    证伪 reset = 静默覆盖（方案 A 的固有风险，issue 明确要求不引入）。
    """
    svc, _repo = await _build_service(content_written=True)

    await svc.reset_run(str(_PLAN_ID))

    with pytest.raises(ChapterAlreadyWrittenError):
        await svc.prepare_run(_PLAN_ID)


@pytest.mark.asyncio
async def test_prepare_run_after_reset_allowed_when_content_gone() -> None:
    """reset + 正文已清（content_checker=False）→ 重跑放行（本 issue 的目标场景）。

    对照组即 test_prepare_run_without_reset_rejected：不调 reset 时必须抛
    ChapterAlreadyWrittenError —— 闸门仍生效，本用例的放行来自 reset 而非闸门失效。
    """
    svc, _repo = await _build_service(content_written=False)

    await svc.reset_run(str(_PLAN_ID))
    result = await svc.prepare_run(_PLAN_ID)

    assert result == {"run_id": str(_PLAN_ID), "status": "running"}


@pytest.mark.asyncio
async def test_prepare_run_without_reset_rejected() -> None:
    """可证伪自证（对照组）：不调 reset → 同一 plan 一律被安全闸拒绝。

    用 ``content_written=True``（正文在场的**直判据**，#1265 核心语义）而非
    依赖 ``execution_refs`` 有痕：后者要穿过 ``prepare_run`` 的悬空引用修剪
    （按活 outline 剪 refs）才生效，是间接前提，不该作为对照组的唯一触发源。
    """
    svc, _repo = await _build_service(content_written=True)

    with pytest.raises(ChapterAlreadyWrittenError):
        await svc.prepare_run(_PLAN_ID)


@pytest.mark.asyncio
async def test_reset_unknown_run_raises() -> None:
    """run 不存在 → ValueError（API 层映射 404，对齐 get_status/intervene）。"""
    repo = AsyncMock()
    repo.get_writing_plan = AsyncMock(return_value=None)
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=AsyncMock(),
        limits=BookLimits(),
        content_checker=AsyncMock(return_value=False),
    )

    with pytest.raises(ValueError, match="运行不存在"):
        await svc.reset_run(str(_PLAN_ID))


@pytest.mark.asyncio
async def test_reset_rejects_while_running() -> None:
    """执行中不可 reset（与 prepare_run「运行已在进行中」同口径）→ ValueError。"""
    svc, repo = await _build_service(content_written=False)
    repo.get_writing_plan.return_value.status = "running"

    with pytest.raises(ValueError, match="进行中"):
        await svc.reset_run(str(_PLAN_ID))
