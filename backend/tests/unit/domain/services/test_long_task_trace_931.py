"""#931 RED 契约：长任务（book 后台任务）trace/correlation 传播。

缺陷背景（issue #931 根因 5）：agent/book 长任务非 HTTP 请求上下文，contextvar
从未被设置 → 一次 run 横跨 planner→executor→pipeline→llm 的几十条日志无法串链。

GREEN 实现契约
--------------
1. asyncio.create_task 拷贝当前 context —— 中间件设置的 correlation/trace
   contextvar 天然传播到 spawn_background_task 任务体（守护用例锁定，防重构退化）。
2. books._run_book 任务体起点锚定**运行级** correlation：
   ``set_request_correlation_id(str(plan_id))``（issue 修复方向 3「一次运行一条链」），
   覆盖 HTTP 请求级值；trace contextvar 沿用请求继承的根（同 trace 贯穿 GUI 请求
   → 后台执行）。
3. 任务体内 log_structured 自动带 trace 三字段（= logging.trace 契约 3 的延伸，
   守护断言锁定端到端）。

RED 形态：函数级 import inkflow.logging.trace 不存在 → ImportError；
_run_book 不锚定 → correlation 断言 FAIL。
"""

from __future__ import annotations

import asyncio
import re
import uuid

TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


async def test_spawn_task_inherits_contextvars():
    """【G】守护：create_task 拷贝 context —— 任务体看到 spawn 点的 ctx。"""
    from inkflow.logging.correlation import (
        get_request_correlation_id,
        set_request_correlation_id,
    )
    from inkflow.logging.trace import TraceContext, get_trace_context, set_trace_context

    seen: dict = {}
    ctx = TraceContext(trace_id="c" * 32, span_id="d" * 16, parent_span_id="")

    async def body() -> None:
        seen["correlation_id"] = get_request_correlation_id()
        seen["trace"] = get_trace_context()

    tc = set_request_correlation_id("run-leak-guard")
    tt = set_trace_context(ctx)
    try:
        await asyncio.create_task(body())
    finally:
        from inkflow.logging.correlation import reset_request_correlation_id
        from inkflow.logging.trace import reset_trace_context

        reset_trace_context(tt)
        reset_request_correlation_id(tc)
    assert seen["correlation_id"] == "run-leak-guard"
    assert seen["trace"] is ctx


async def test_run_book_anchors_correlation_to_plan_id():
    """【R】_run_book 起点把 correlation 锚定为 str(plan_id)（一次运行一条链）。"""
    from unittest.mock import AsyncMock, MagicMock

    from inkflow.api.routers import books
    from inkflow.logging.correlation import (
        get_request_correlation_id,
        set_request_correlation_id,
    )

    plan_id = uuid.uuid4()
    observed: dict = {}

    svc = MagicMock()

    async def _capture(*_a, **_kw) -> dict:
        observed["correlation_id"] = get_request_correlation_id()
        return {"status": "completed"}

    svc.write_book = AsyncMock(side_effect=_capture)

    # 请求级 correlation（模拟 HTTP 入口值）——任务体必须覆盖为 plan_id
    token = set_request_correlation_id("http-level-corr")
    try:
        await books._run_book(svc, plan_id, None, mode="static", config=None)
    finally:
        from inkflow.logging.correlation import reset_request_correlation_id

        reset_request_correlation_id(token)

    assert observed.get("correlation_id") == str(plan_id), (
        "#931: 后台任务起点必须 set_request_correlation_id(str(plan_id))，"
        "否则整条 run 的日志仍无链可串"
    )


async def test_run_book_logs_carry_trace_fields():
    """【R】任务体内 @instrument 埋点日志自动带 OTel 三字段（trace 贯穿后台段）。"""
    from unittest.mock import AsyncMock, MagicMock

    from inkflow.api.routers import books
    from inkflow.logging.trace import (
        TraceContext,
        reset_trace_context,
        set_trace_context,
    )

    records: list[dict] = []
    plan_id = uuid.uuid4()

    class _Svc:
        pass

    svc = MagicMock()
    ctx = TraceContext(trace_id="e" * 32, span_id="f" * 16, parent_span_id="")

    async def _capture(*_a, **_kw) -> dict:
        from loguru import logger

        from inkflow.logging.schema import log_structured

        sink_id = logger.add(lambda m: records.append(m.record), level="INFO", format="{message}")
        try:
            log_structured(
                level="INFO",
                caller_type="agent",
                caller_name="book.pipeline.probe",
                event="run_step",
                message_key="log.event.x",
                params={},
            )
        finally:
            logger.remove(sink_id)
        return {"status": "completed"}

    svc.write_book = AsyncMock(side_effect=_capture)

    tt = set_trace_context(ctx)
    try:
        await books._run_book(svc, plan_id, None, mode="static", config=None)
    finally:
        reset_trace_context(tt)

    assert records, "探针日志未捕获"
    extra = records[0]["extra"]
    assert extra.get("trace_id") == "e" * 32, (
        "#931: 后台任务日志必须继承请求 trace_id（trace 贯穿全链）"
    )
    assert TRACE_ID_RE.match(extra["trace_id"])
    assert re.fullmatch(r"[0-9a-f]{16}", extra["span_id"])
