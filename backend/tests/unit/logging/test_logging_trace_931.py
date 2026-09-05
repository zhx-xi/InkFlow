"""#931 RED 契约：inkflow.logging.trace — OTel/W3C traceparent 原语 + contextvar。

模块契约（logging/trace.py，GREEN = CREATE）
--------------------------------------------
1. @dataclass(frozen=True) TraceContext：trace_id: str / span_id: str /
   parent_span_id: str（根 span 时 parent 为空串）。
2. new_trace_id() -> str：32 位小写 hex（secrets 随机，非全零）。
   new_span_id() -> str：16 位小写 hex（同上）。
3. make_traceparent(ctx) -> str：f"00-{trace_id}-{span_id}-01"（flags=采样）。
4. parse_traceparent(value) -> TraceContext | None：
   - 严格匹配 ``00-<32hex>-<16hex>-<2hex>``（W3C: version=00 拒大写/拒全零
     trace/span；flags 段透传校验为 2hex 即可）→ 返回 TraceContext(
     trace_id=头 trace_id, span_id=**新生成**, parent_span_id=头 span_id)
     即「继承 trace、开子 span」。
   - None / "" / 非法 → None（调用方负责兜底，绝不抛）。
   - 注意区分：parse 返回的子 span ctx 用 ``child_span_of`` 语义构造，
     traceparent 回写时用 parse 入参的原始 ctx 亦可（见 middleware 契约 3）。
5. contextvar（请求/任务级）：
   - get_trace_context() -> TraceContext | None（默认 None = 无 trace 上下文）
   - set_trace_context(ctx) -> Token / reset_trace_context(token)
     （与 correlation.py 同形态，标准库 contextvars，无框架依赖）。
6. span(trace_id=None, name=...) context manager 形态**不做**（YAGNI，
   节点级子 span 由各埋点在 ctx 上手动 child_span 即可）——本契约只锁上述原语。

RED 形态：from inkflow.logging.trace import ... 模块不存在 → ImportError。
"""

from __future__ import annotations

import re

TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")
TRACE_ID_A = "4bf92f3577b34da6a3ce929d0e0e4736"  # W3C 规范示例 trace
SPAN_ID_A = "00f067aa0ba902b7"  # W3C 规范示例 span


def _import_trace():
    """函数级 import（RED 期 ImportError；禁模块级防收集失败，f669 先例）。"""
    from inkflow.logging import trace

    return trace


class TestIds:
    def test_new_trace_id_format(self):
        trace = _import_trace()
        value = trace.new_trace_id()
        assert TRACE_ID_RE.match(value), f"trace_id 须 32 位小写 hex，实际 {value!r}"
        assert int(value, 16) != 0

    def test_new_span_id_format(self):
        trace = _import_trace()
        value = trace.new_span_id()
        assert SPAN_ID_RE.match(value), f"span_id 须 16 位小写 hex，实际 {value!r}"
        assert int(value, 16) != 0

    def test_ids_random_not_sequential(self):
        trace = _import_trace()
        ids = {trace.new_trace_id() for _ in range(64)}
        assert len(ids) == 64, "64 次生成不得碰撞"


class TestMakeTraceparent:
    def test_root_format(self):
        trace = _import_trace()
        ctx = trace.TraceContext(trace_id=TRACE_ID_A, span_id=SPAN_ID_A, parent_span_id="")
        assert trace.make_traceparent(ctx) == f"00-{TRACE_ID_A}-{SPAN_ID_A}-01"


class TestParseTraceparent:
    def test_valid_inherits_trace_opens_child_span(self):
        trace = _import_trace()
        ctx = trace.parse_traceparent(f"00-{TRACE_ID_A}-{SPAN_ID_A}-01")
        assert ctx is not None
        assert ctx.trace_id == TRACE_ID_A
        assert ctx.parent_span_id == SPAN_ID_A, "子 span 的 parent = 传入 span_id"
        assert SPAN_ID_RE.match(ctx.span_id) and ctx.span_id != SPAN_ID_A

    def test_flags_ff_accepted(self):
        trace = _import_trace()
        assert trace.parse_traceparent(f"00-{TRACE_ID_A}-{SPAN_ID_A}-ff") is not None

    def test_vendor_version_with_extension_rejected(self):
        """W3C：version=ff 永不合法；'ff' + 多余段按非法处理（本内核仅支持 00）。"""
        trace = _import_trace()
        assert trace.parse_traceparent(f"ff-{TRACE_ID_A}-{SPAN_ID_A}-01") is None
        assert trace.parse_traceparent(f"01-{TRACE_ID_A}-{SPAN_ID_A}-01") is None

    def test_all_zero_ids_rejected(self):
        trace = _import_trace()
        assert trace.parse_traceparent(f"00-{'0' * 32}-{SPAN_ID_A}-01") is None
        assert trace.parse_traceparent(f"00-{TRACE_ID_A}-{'0' * 16}-01") is None

    def test_garbage_rejected_no_raise(self):
        trace = _import_trace()
        for bad in ["", None, "x", f"00-{TRACE_ID_A}", f"00-{TRACE_ID_A.upper()}-{'b' * 16}-01"]:
            assert trace.parse_traceparent(bad) is None, f"非法值须返回 None: {bad!r}"

    def test_extra_trailing_segment_accepted_w3c_strict(self):
        """W3C 规定未来版本可加段，但 version=00 的当前规范恰为 4 段——多段按非法。"""
        trace = _import_trace()
        assert trace.parse_traceparent(f"00-{TRACE_ID_A}-{SPAN_ID_A}-01-extra") is None


class TestContextVar:
    def test_default_none(self):
        trace = _import_trace()
        assert trace.get_trace_context() is None

    def test_set_get_reset(self):
        trace = _import_trace()
        ctx = trace.TraceContext(trace_id=TRACE_ID_A, span_id=SPAN_ID_A, parent_span_id="")
        token = trace.set_trace_context(ctx)
        try:
            assert trace.get_trace_context() is ctx
        finally:
            trace.reset_trace_context(token)
        assert trace.get_trace_context() is None


class TestLogStructuredIntegration:
    """log_structured 与 trace 的接线（schema.py 契约 3）：ctx 在 → 三字段入 extra；
    显式参数 > contextvar；parent_span_id 同步透传。"""

    def _capture_extra(self, **kw):
        from loguru import logger

        from inkflow.logging.schema import log_structured

        records: list[dict] = []
        sid = logger.add(lambda m: records.append(m.record), level="INFO", format="{message}")
        try:
            log_structured(
                level="INFO",
                caller_type="api",
                caller_name="trace.wire",
                event="e",
                message_key="log.event.x",
                **kw,
            )
        finally:
            logger.remove(sid)
        assert len(records) == 1
        return records[0]["extra"]

    def test_contextvar_populates_trace_fields(self):
        trace = _import_trace()

        ctx = trace.TraceContext(trace_id=TRACE_ID_A, span_id=SPAN_ID_A, parent_span_id="")
        token = trace.set_trace_context(ctx)
        try:
            extra = self._capture_extra(correlation_id="c1")
        finally:
            trace.reset_trace_context(token)
        assert extra["trace_id"] == TRACE_ID_A
        assert extra["span_id"] == SPAN_ID_A
        assert extra["parent_span_id"] == "", "根 span parent 空串也须出现在 extra"

    def test_explicit_params_win_over_contextvar(self):
        trace = _import_trace()

        ctx = trace.TraceContext(trace_id=TRACE_ID_A, span_id=SPAN_ID_A, parent_span_id="")
        token = trace.set_trace_context(ctx)
        try:
            extra = self._capture_extra(correlation_id="c1", trace_id="e" * 32, span_id="f" * 16)
        finally:
            trace.reset_trace_context(token)
        assert extra["trace_id"] == "e" * 32
        assert extra["span_id"] == "f" * 16

    def test_no_context_no_trace_keys(self):
        """无 trace 上下文 → extra 不含 trace_id/span_id（#888 零回归：现有消费面
        按键存在性读取，不得注入空串假值）。"""
        extra = self._capture_extra(correlation_id="c1")
        assert "trace_id" not in extra
        assert "span_id" not in extra
        assert "parent_span_id" not in extra
