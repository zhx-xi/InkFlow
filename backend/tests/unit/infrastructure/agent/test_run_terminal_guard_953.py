"""#953 契约 RED-3b — 终态兜底守护（异常冒泡链的终态映射已存在，以【G】固化）。

先读契约 ``.hermes/plans/contract-953.md`` §2 RED-3b / §0#7 后再编码。

背景（§0#7）：黑洞 = 永久挂起无异常 + 重启后遗留 running；异常路径已有终态映射
（``_write_chapter`` L420-428 try/except→failed；``_run_book`` books.py:533-535→mark_failed）。
本文件以【G】守护测试固化这两个既有终态映射，不改 ``_write_chapter``/``_run_book`` 逻辑。

重复度核查结论（防造冗余，§2 RED-3b 明示）
----------------------------------------
- ``test_delegate_write_exception_marks_chapter_failed``：既有 test_book_agentic_pipeline.py
  未覆盖「writer 异常 → 章 failed」（grep failed/RuntimeError/_write_chapter 无命中），
  → 新写，不冗余。
- ``test_run_book_exception_marks_plan_failed``：既有 suite 中 (a) test_book_service_background.py
  直接测 ``svc.mark_failed``（BookService 单测，非 ``_run_book``）；(b) test_long_task_trace_931.py
  测 ``_run_book`` 的 correlation 锚定，未测「异常 → mark_failed」分支；(c) test_book_run_929.py
  只 patch ``books._run_book`` 断言不 spawn。→ ``_run_book`` 异常分支无既有用例，新写，不冗余。

装配形态取舍（RED-3b 题 1）
------------------------
契约原意图走 ``execute`` 全图；但 writer 抛异常后 supervisor 可能再路由（fallback 会重写并
置 done），全图终态未必稳定落在 ``failed`` 上。故降级为**直接测 ``_write_chapter`` 状态机落点
节点函数**（§0#7 明确其是 try/except→failed 的映射实现），管线鸭子 + state 字典直构，稳定性与
忠实度更高，并在 docstring 注明取舍。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace


async def test_delegate_write_exception_marks_chapter_failed() -> None:
    """【G】writer 委托抛异常 → _write_chapter 把该章标记 failed（终态兜底，现状已满足）。

    直接调用状态机落点 ``_write_chapter``：writer_factory 返回的 adapter 鸭子，其
    ``invoke`` 每次抛 ``RuntimeError``，重试 retry_limit 次全败后节点正常返回
    ``progress[oid]=='failed'``、``results[oid]=='failed'``，函数**不抛**（run 可终态）。
    """
    from inkflow.infrastructure.agent.book_agentic_pipeline import (
        BookAgenticPipeline,
        _write_chapter,
    )

    oid = str(uuid.uuid4())
    state: dict = {
        "target_outline_id": oid,
        "chapters": [
            {
                "outline_id": oid,
                "chapter_id": str(uuid.uuid4()),
                "name": "第一章",
                "description": "第一章大纲描述",
                "sort_order": 0,
            }
        ],
        "steps": 0,
        "consecutive": 0,
        "last_op": "",
        "progress": {},
        "results": {},
    }

    class _ThrowingAdapter:
        def __init__(self) -> None:
            self.invoke_count = 0

        async def invoke(self, messages, config=None):
            self.invoke_count += 1
            raise RuntimeError("boom")

    class _ThrowingWriterFactory:
        def __init__(self) -> None:
            self.adapter = _ThrowingAdapter()

        async def __call__(self, **kwargs):
            return self.adapter

    factory = _ThrowingWriterFactory()
    pipeline = BookAgenticPipeline(
        llm_client=None,
        writer_factory=factory,
        draft_service=object(),  # invoke 先抛，draft_service.create 不会被触达
        retry_limit=2,
    )
    pipeline._plan = SimpleNamespace(
        id=uuid.UUID(int=1),
        project_id=uuid.UUID(int=10),
        character_ids=[],
        limits={},
        progress={},
        execution_refs={},
        root_outline_id=None,
        title="测试书",
        status="running",
    )

    result = await _write_chapter(state, pipeline)

    # 终态兜底：该章必须落 failed（非 running/挂起），且节点正常返回不抛
    assert result["progress"][oid] == "failed", (
        f"写章委托异常后该章应落 failed，实际 progress={result['progress'][oid]!r}"
    )
    assert result["results"][oid] == "failed", (
        f"results 应同步 failed，实际 {result['results'][oid]!r}"
    )
    # 确认确实经历了「重试全败」路径，而非成功委托（retry_limit=2 → 3 次尝试）
    assert factory.adapter.invoke_count == 3


async def test_run_book_exception_marks_plan_failed() -> None:
    """【G】_run_book 任务体 write_book_agentic 抛 → svc.mark_failed 被调用
    （终态兜底，现状已满足）。

    契约 §2 RED-3b / §0#7：``_run_book`` books.py:533-535 捕获异常后
    ``with contextlib.suppress(Exception): await svc.mark_failed(str(plan_id))``。
    """
    from unittest.mock import AsyncMock, MagicMock

    from inkflow.api.routers import books

    plan_id = uuid.uuid4()
    svc = MagicMock()
    svc.write_book_agentic = AsyncMock(side_effect=RuntimeError("boom"))
    svc.mark_failed = AsyncMock(return_value={"run_id": str(plan_id), "status": "failed"})

    # 函数体 import 的 set_request_correlation_id / reset_request_correlation_id
    # 由 books 模块全局提供并在任务体 finally 复位，无需 patch（镜像 test_long_task_trace_931.py）。
    await books._run_book(svc, plan_id, None, mode="agentic", config=None)

    svc.write_book_agentic.assert_awaited_once()
    svc.mark_failed.assert_awaited_once_with(str(plan_id))
