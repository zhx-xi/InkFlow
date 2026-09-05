"""#931 集成契约：中间件全链路 —— 请求 → 埋点 → 结构化 store 落库带 OTel 三字段。

与 middleware 单元契约（test_correlation_trace_931）互补：本文件走真实
ASGI 链（中间件 + 处理函数内 log_structured + _structured_sink 落库），断言
issue 验收判据的数据面：
- 无头请求 → store 记录 correlation_id 非空 + trace_id(32hex)/span_id(16hex)；
- 带 traceparent → 同 trace_id + parent_span_id=传入 span；
- #888 零回归：store query 仍可按 correlation_id 过滤命中。
"""

from __future__ import annotations

import re

from inkflow.api.middleware.correlation import CorrelationIdMiddleware


def _patch_store_dir(monkeypatch, tmp_path):
    import importlib

    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", tmp_path)
    monkeypatch.setattr(cfg_mod.config, "debug", True)
    monkeypatch.setattr(cfg_mod.config, "log_level", "INFO")
    core_log = importlib.import_module("inkflow.core.log")
    monkeypatch.setattr(core_log, "resolve_log_dir", lambda: tmp_path / "logs")
    return core_log


async def _get(scope_headers, handler):
    messages: list[dict] = []

    async def send(msg: dict) -> None:
        messages.append(msg)

    mw = CorrelationIdMiddleware(handler)
    await mw(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "GET",
            "path": "/x",
            "headers": list(scope_headers),
        },
        None,
        send,
    )
    return messages


async def test_headless_request_logs_land_with_otel_fields(monkeypatch, tmp_path):
    from inkflow.logging import StructuredLogStore, log_structured

    core_log = _patch_store_dir(monkeypatch, tmp_path)
    core_log.setup_logging()

    async def handler(scope, receive, send):
        # 模拟 @instrument 埋点在请求上下文内记录（contextvar 驱动）
        log_structured(
            level="INFO",
            caller_type="api",
            caller_name="e2e.probe",
            event="probe",
            message_key="log.event.x",
            params={},
        )
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    await _get([], handler)

    items, _total = StructuredLogStore(tmp_path / "logs" / "structured").query()
    rec = next((r for r in items if r.get("caller_name") == "e2e.probe"), None)
    assert rec is not None, "请求内埋点未落 store"
    assert rec["correlation_id"], "#931: 无头请求 correlation 必须兜底非空"
    assert re.fullmatch(r"[0-9a-f]{32}", rec.get("trace_id", "")), "trace_id 32hex 落库"
    assert re.fullmatch(r"[0-9a-f]{16}", rec.get("span_id", "")), "span_id 16hex 落库"
    assert rec.get("parent_span_id") == "", "根 span parent 空串"


async def test_incoming_traceparent_queryable_by_trace_id(monkeypatch, tmp_path):
    """验收判据（issue 旅程重放的静态版）：客户端持有 traceparent → 该请求全链路
    日志同 trace_id → 可按 trace_id/correlation_id 聚合查询。"""
    from inkflow.logging import StructuredLogStore, log_structured

    core_log = _patch_store_dir(monkeypatch, tmp_path)
    core_log.setup_logging()

    incoming_tp = "00-" + "7" * 32 + "-" + "8" * 16 + "-01"

    async def handler(scope, receive, send):
        # 嵌套两层埋点 = 一次操作多条日志（模拟 planner/executor 多段）
        log_structured(
            level="INFO",
            caller_type="agent",
            caller_name="e2e.planner",
            event="plan",
            message_key="log.event.x",
            params={},
        )
        log_structured(
            level="INFO",
            caller_type="llm",
            caller_name="e2e.llm",
            event="call",
            message_key="log.event.x",
            params={},
        )
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    await _get([(b"traceparent", incoming_tp.encode())], handler)

    store = StructuredLogStore(tmp_path / "logs" / "structured")
    items, _total = store.query()
    probe = [r for r in items if r.get("caller_name", "").startswith("e2e.")]
    assert len(probe) == 2
    assert {r["trace_id"] for r in probe} == {"7" * 32}, "同一请求内所有日志共享 trace_id（一条链）"
    assert probe[0]["parent_span_id"] == "8" * 16, "同请求多埋点共享 parent=宿主 span"
    # #888 零回归：correlation 过滤面照常工作
    corr = probe[0]["correlation_id"]
    assert corr
    hit, n = store.query(correlation_id=corr)
    assert n >= 2 and all(r["correlation_id"] == corr for r in hit)


async def test_ingest_log_persists_trace_fields(monkeypatch, tmp_path):
    """【R】POST /logs 桥接面：LogRecordInput 含 trace 三字段 → StructuredLogRecord
    透传落 store（GUI 上报记录与内核同 trace 聚合，#888 兼容仅追加可选键）。

    RED：LogRecordInput 无该字段（pydantic 忽略）→ ingest 构建的记录无 trace_id。
    """
    from inkflow.api.routers import logs
    from inkflow.logging import StructuredLogStore

    _patch_store_dir(monkeypatch, tmp_path)
    store = StructuredLogStore(tmp_path / "logs" / "structured")

    payload = logs.LogRecordInput(
        level="info",
        caller_type="frontend",
        caller_name="WritingPage.tp",
        event="probe",
        message_key="log.event.x",
        params={},
        correlation_id="c-ing",
        trace_id="9" * 32,
        span_id="1" * 16,
        parent_span_id="2" * 16,
    )
    await logs.ingest_log(payload, store=store)

    items, _ = store.query()
    rec = next((r for r in items if r.get("caller_name") == "WritingPage.tp"), None)
    assert rec is not None, "ingest 未落库"
    assert rec.get("trace_id") == "9" * 32, (
        "#931: LogRecordInput 必须新增可选 trace_id/span_id/parent_span_id 并透传 store"
    )
    assert rec.get("span_id") == "1" * 16
    assert rec.get("parent_span_id") == "2" * 16
