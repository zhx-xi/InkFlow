"""#863 P1：writing_plan 引用已删除 outline 节点 → progress 失效（RED 契约）。

根因：WritingPlan.progress / execution_refs 以 outline_id 为键的存储快照（spec §2.2 R2
「进度权威 = WritingPlan.progress」），绑定 outline 节点。outline 节点被硬删
（outline_service.hard_delete → DB FK CASCADE）后，writing_plan 中指向它的键悬空，
write_book 聚合进度时幽灵条目残留在 plan.progress，导致 chapters_written /
agent_calls / 硬护栏计数虚高，进度树引用已不存在的节点 → 进度失效。

契约（#863）：**write_book 聚合进度必须按当前 outline 树实时推导**，删除 outline 后
优雅跳过/标记悬空引用（修剪幽灵条目），progress 不再失效、聚合不崩。

修复面（设计决策）：reconcile 落在 **write_book**（活 outline 树唯一权威来源）。
get_status / get_summary 是存储快照的只读透传；write_book 修剪后快照即干净，
报告路径自然无幽灵。**不**在 get_status/get_summary 内做 outline 树读取修剪——
既有单测用虚构 outline id（如 "c1"）+ 空 list 构造，若报告路径按活树修剪会清空
合法进度致 chapters_written 归零 → 破坏向后兼容（#863 约束：最小改动不复用骨架）。

RED 预期（当前实现）：
- test_write_book_prunes_dangling_outline_ref：write_book 后 plan.progress 仍含已删
  outline_id（幽灵条目残留）→ AssertionError。
- test_write_book_then_report_clean：write_book 修剪后 get_status 报进度不含已删
  outline_id；当前实现未修剪 → 幽灵透出 → AssertionError。

守护用例（RED 期刻意 PASS）：无悬空引用时 write_book 行为不变（向后兼容守护）。
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


def _now() -> datetime:
    return datetime.now(UTC)


def _plan(progress: dict, execution_refs: dict, root_outline_id) -> WritingPlan:
    return WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="测试计划",
        status="ready",
        root_outline_id=root_outline_id,
        character_ids=[],
        limits={"max_chapters": 100, "max_agent_calls": 100},
        progress=progress,
        execution_refs=execution_refs,
        thread_id=None,
        created_at=_now(),
        updated_at=_now(),
    )


def _outline(oid: uuid.UUID, name: str, *, sort_order: int = 0) -> Outline:
    return Outline(
        id=oid,
        project_id=uuid.uuid4(),
        name=name,
        description="章描述",
        sort_order=sort_order,
        level="chapter",
        parent_id=None,
        chapter_id=uuid.uuid4(),
        extra={},
        created_at=_now(),
        updated_at=_now(),
    )


def _svc(plan: WritingPlan, live: list[Outline], *, repo: AsyncMock | None = None) -> BookService:
    """构造 BookService：outline_repo 返回 live 树（模拟删除后当前树）；plan 附着在 repo。"""
    repo = repo or AsyncMock()
    repo.get_writing_plan.return_value = plan
    repo.update_writing_plan.return_value = None

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {"messages": [SimpleNamespace(content="正文", tool_calls=[])]}
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    outline_repo = AsyncMock()
    outline_repo.list.return_value = (live, len(live))

    return BookService(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
    )


# ── 悬空引用：write_book 优雅跳过（修剪幽灵条目）──────────────────


@pytest.mark.asyncio
async def test_write_book_prunes_dangling_outline_ref():
    """outline O1 已删（悬空），progress/execution_refs 引用它；live 树只有 O2。
    write_book 聚合进度须优雅跳过悬空 O1（修剪幽灵条目），只保留当前树节点 O2。
    O2 在修剪时即持有合法引用（execution_refs 混合悬空+合法 → 修剪保合法删悬空；
    progress in_progress 不触发「已完成」安全阀，O2 照常派发并覆写引用）。"""
    o1 = _outline(uuid.uuid4(), "第一章(已删除)")
    o2 = _outline(uuid.uuid4(), "第一章(重建)")
    plan = _plan(
        progress={str(o1.id): "done", str(o2.id): "in_progress"},
        execution_refs={str(o1.id): "exec-1", str(o2.id): "exec-old"},
        root_outline_id=o2.id,
    )
    svc = _svc(plan, [o2])

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    # 悬空 O1 被优雅跳过（不再残留于进度）
    assert str(o1.id) not in plan.progress
    assert str(o1.id) not in plan.execution_refs
    # 当前树节点 O2 正常派发（合法引用保留并被新执行覆写）
    assert plan.progress.get(str(o2.id)) == "done"
    assert plan.execution_refs == {str(o2.id): "draft-1"}


@pytest.mark.asyncio
async def test_write_book_then_report_clean():
    """write_book 修剪后，报告路径（get_status）报进度不含已删 outline_id：
    存储快照权威（spec R2）在 write_book 聚合时被清理，透出版自然干净。"""
    o1 = _outline(uuid.uuid4(), "第一章(已删除)")
    o2 = _outline(uuid.uuid4(), "第一章(重建)")
    plan = _plan(
        progress={str(o1.id): "done", str(o2.id): "in_progress"},
        execution_refs={str(o1.id): "exec-1"},
        root_outline_id=o2.id,
    )
    svc = _svc(plan, [o2])

    await svc.write_book(plan.id)
    status = await svc.get_status(str(plan.id))

    assert status is not None
    assert str(o1.id) not in status["progress"]
    assert str(o2.id) in status["progress"]


# ── 守护用例：无悬空引用时行为不变（RED 期刻意 PASS）─────────────


@pytest.mark.asyncio
async def test_write_book_no_dangling_unchanged():
    """无悬空引用：write_book 行为与既有契约一致（全 done，不修剪合法引用）。"""
    o1 = _outline(uuid.uuid4(), "第一章")
    plan = _plan(progress={}, execution_refs={}, root_outline_id=o1.id)
    svc = _svc(plan, [o1])

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert plan.progress.get(str(o1.id)) == "done"
    assert str(o1.id) in plan.execution_refs
