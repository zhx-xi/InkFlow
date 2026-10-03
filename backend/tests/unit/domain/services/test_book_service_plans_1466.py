"""#1466 书级计划列表·服务层契约（成书页水合）。

缺陷背景：成书页对「已有 plan / 跑过 book run 的书」只显示起点表单。
根因之一 = 后端只有单条读取（get_status/get_summary），**没有「按项目列 plan」**。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

BookService 新增只读方法（无副作用，不改 run 执行语义）：

    async def list_plans(
        self, project_id: uuid.UUID | None, offset: int = 0, limit: int = 50
    ) -> tuple[list[WritingPlan], int]

- 纯委托 `self._repo.list_writing_plans(project_id=..., offset=..., limit=...)`
  （鸭子 repo，镜像既有 `list_planner_sessions` 形态）；
- **不做状态过滤、不做排序改写**（排序由 repo 的 `updated_at DESC` 负责）；
- 空项目 / 不存在项目 → `([], 0)`（不抛异常——端点层要求 200 空列表非 404）；
- repo 异常原样上抛（服务层不吞错，与 get_status/reset_run 同族）。

【RED 预期形态】`BookService.list_plans` 不存在 → AttributeError。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.writing_plan import WritingPlan
from inkflow.domain.services.book_service import BookService


def _project_id() -> uuid.UUID:
    return uuid.UUID(int=1)


def _plan(**overrides: object) -> WritingPlan:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": _project_id(),
        "title": "既有写作计划",
        "status": "running",
        "root_outline_id": None,
        "character_ids": [],
        "limits": {"max_chapters": 3, "max_agent_calls": 6},
        "progress": {"o-c1": "done"},
        "execution_refs": {},
        "thread_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return WritingPlan(**base)  # type: ignore[arg-type]  # 测试 helper：overrides 逐键覆盖返回 object


def _service(repo: AsyncMock) -> BookService:
    return BookService(repo=repo)


@pytest.mark.asyncio
async def test_list_plans_delegates_to_repo_with_project_and_paging() -> None:
    """project_id/offset/limit 透传鸭子 repo（服务层零加工）。"""
    repo = AsyncMock()
    plans = [_plan(title="P1"), _plan(title="P2")]
    repo.list_writing_plans = AsyncMock(return_value=(plans, 2))

    items, total = await _service(repo).list_plans(_project_id(), offset=10, limit=5)

    assert items == plans
    assert total == 2
    repo.list_writing_plans.assert_awaited_once_with(project_id=_project_id(), offset=10, limit=5)


@pytest.mark.asyncio
async def test_list_plans_defaults_offset_and_limit() -> None:
    """缺省分页 = offset 0 / limit 50（与 GET /planner 列表同惯例）。"""
    repo = AsyncMock()
    repo.list_writing_plans = AsyncMock(return_value=([], 0))

    items, total = await _service(repo).list_plans(_project_id())

    assert (items, total) == ([], 0)
    repo.list_writing_plans.assert_awaited_once_with(project_id=_project_id(), offset=0, limit=50)


@pytest.mark.asyncio
async def test_list_plans_empty_project_returns_empty_not_raises() -> None:
    """空项目 → ([], 0)（端点层据此返回 200 空列表，非 404）。"""
    repo = AsyncMock()
    repo.list_writing_plans = AsyncMock(return_value=([], 0))

    items, total = await _service(repo).list_plans(uuid.UUID(int=999))

    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_plans_project_none_passthrough() -> None:
    """project_id=None 原样透传（全量列表语义，与 list_planner_sessions 一致）。"""
    repo = AsyncMock()
    repo.list_writing_plans = AsyncMock(return_value=([], 0))

    await _service(repo).list_plans(None)

    repo.list_writing_plans.assert_awaited_once_with(project_id=None, offset=0, limit=50)


@pytest.mark.asyncio
async def test_list_plans_repo_error_propagates() -> None:
    """repo 异常不吞（服务层无 try/except——错误由路由层/上层决定信封）。"""
    repo = AsyncMock()
    repo.list_writing_plans = AsyncMock(side_effect=RuntimeError("db down"))

    with pytest.raises(RuntimeError, match="db down"):
        await _service(repo).list_plans(_project_id())
