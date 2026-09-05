"""#931 审查跟进（PR #943 finding #1，Moderate）：ingest_log header 路径 trace 兜底。

缺陷：前端 reportLog 把 trace 放 HTTP 头 traceparent（body=FrontendLogRecord 无
trace 字段），中间件解析入 contextvar；但 ingest_log 直接从 body 构建
StructuredLogRecord → GUI 上报记录 trace_id=None 成孤儿，违背「前端日志与内核
API 调用同 trace 聚合」意图（F57 §2.2 入口面 GUI 生成根 trace）。

GREEN 契约（ingest_log）：body 缺省（None）的 trace 三字段按 log_structured 同款
解析链从 trace contextvar **派生子 span** 补齐——span_id 新生成、parent_span_id
继承 ctx.span_id（HTTP 接收 span = 前端记录 span 的父）；无 contextvar 保持 None
→ exclude_none 剔除（#888 零回归）。显式 body 字段优先级不变（现有用例锁定）。
"""

from __future__ import annotations

from pathlib import Path


async def test_ingest_log_falls_back_to_header_trace_context(monkeypatch, tmp_path):
    """【R】body 无 trace 字段（前端真实形状）→ 中间件 contextvar 兜底派生子 span。"""
    import importlib

    from inkflow.api.routers import logs
    from inkflow.logging import StructuredLogStore
    from inkflow.logging.trace import TraceContext

    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", Path(tmp_path))
    store = StructuredLogStore(tmp_path / "logs" / "structured")

    payload = logs.LogRecordInput(
        level="info",
        caller_type="frontend",
        caller_name="WritingPage.review1",
        event="probe",
        message_key="log.event.x",
        params={},
        correlation_id="c-hdr",
    )
    # 模拟中间件已解析 traceparent 入 contextvar（HTTP 接收 span）
    http_span = TraceContext(trace_id="a" * 32, span_id="b" * 16, parent_span_id="")
    token = _set_trace(http_span)
    try:
        await logs.ingest_log(payload, store=store)
    finally:
        _reset_trace(token)

    items, _ = store.query()
    rec = next((r for r in items if r.get("caller_name") == "WritingPage.review1"), None)
    assert rec is not None, "ingest 未落库"
    assert rec.get("trace_id") == "a" * 32, (
        "#931 审查#1: body 缺省 trace 时必须从 contextvar（HTTP 头解析）兜底，"
        "否则 GUI 上报记录与内核 API 调用不同 trace（前端日志孤儿）"
    )
    assert rec.get("parent_span_id") == "b" * 16, (
        "兜底 span 的 parent = HTTP 接收 span（trace 父子链完整，非直接照抄）"
    )
    span_id = rec.get("span_id")
    assert isinstance(span_id, str) and len(span_id) == 16 and span_id != "b" * 16, (
        "记录 span 须新生成（前端日志是 HTTP 接收 span 的子）"
    )


async def test_ingest_log_no_context_keeps_trace_absent(monkeypatch, tmp_path):
    """【G】#888 零回归：无 body trace 字段且无 contextvar → 落库 trace 键为 null。

    store.append 用 model_dump(mode="json")（含 None 键）——既有 #888 语义；
    守护点 = 兜底逻辑绝不得在无上下文时注入假值（null 原文保持）。
    """
    import importlib

    from inkflow.api.routers import logs
    from inkflow.logging import StructuredLogStore

    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", Path(tmp_path))
    store = StructuredLogStore(tmp_path / "logs" / "structured")

    payload = logs.LogRecordInput(
        level="info",
        caller_type="frontend",
        caller_name="WritingPage.noctx",
        event="probe",
        message_key="log.event.x",
        params={},
        correlation_id="c-noctx",
    )
    assert _get_trace() is None  # 前提：无 trace 上下文
    await logs.ingest_log(payload, store=store)

    items, _ = store.query()
    rec = next((r for r in items if r.get("caller_name") == "WritingPage.noctx"), None)
    assert rec is not None
    assert rec.get("trace_id") is None, "#888: 无上下文不得兜底注入假值"
    assert rec.get("span_id") is None
    assert rec.get("parent_span_id") is None


def _set_trace(ctx):
    from inkflow.logging.trace import set_trace_context

    return set_trace_context(ctx)


def _reset_trace(token):
    from inkflow.logging.trace import reset_trace_context

    reset_trace_context(token)


def _get_trace():
    from inkflow.logging.trace import get_trace_context

    return get_trace_context()
