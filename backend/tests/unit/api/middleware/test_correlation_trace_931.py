"""#931 RED 契约：CorrelationIdMiddleware 兜底生成 + W3C traceparent（拍板 A）。

缺陷背景（issue #931，rc2 实测）
--------------------------------
correlation_id 非空率 1/65：中间件「非空才 set」不兜底 → CLI/MCP/内部调用
全部产生 correlation 为空的日志；trace_id/span_id 0/65：全仓无生成点。

GREEN 实现契约（api/middleware/correlation.py MODIFY + logging/trace.py CREATE）
--------------------------------------------------------------------------------
1. correlation：无 x-correlation-id 头 → 兜底生成 uuid4 set contextvar；有 →
   沿用（#496 B4 语义不变）。头名大小写不敏感（ASGI scope 键已小写，lower() 兼容）。
2. traceparent：解析有效 W3C 头（``00-<trace 32hex>-<parent_span 16hex>-<flags 2hex>``，
   trace/span 非全零、version=00）→ 内核建**子 span**：同 trace_id、新 span_id、
   parent_span_id=传入 span_id。缺失/非法 → 兜底生成新根 TraceContext
   （parent_span_id=""）——绝不抛异常、绝不透传非法值。
3. 响应回写：send wrapper 在 http.response.start 追加 ``x-correlation-id`` 与
   ``traceparent``（回写值 = 当前内核 span，供客户端/排障关联）。纯 ASGI（禁
   BaseHTTPMiddleware，F23 SSE 同族决策）。
4. 非 http scope 透传；finally reset 双 contextvar（防泄漏到后续请求/任务）。

RED 形态
--------
inkflow.logging.trace 不存在 → 函数级 import ImportError（禁模块级 import 防
整文件收集失败，f669 先例）；响应头无 traceparent → 断言 FAIL。【G】= 回归守护。

测试约定
--------
- 裸 ASGI 直调（不引 FastAPI/TestClient）：inner app 记录 contextvar 观测值。
- asyncio_mode=auto（pyproject），async 用例无需 marker。
"""

from __future__ import annotations

import re
import uuid

import pytest

from inkflow.api.middleware.correlation import CorrelationIdMiddleware

TRACE_ID_A = "a" * 32
SPAN_ID_A = "b" * 16
VALID_TP = f"00-{TRACE_ID_A}-{SPAN_ID_A}-01"

TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def _http_scope(headers: list[tuple[bytes, bytes]]) -> dict:
    """最小合法 http scope（ASGI 规范字段齐；headers 键按规范小写但用例故意混大小写）。"""
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/x",
        "raw_path": b"/x",
        "query_string": b"",
        "headers": list(headers),
        "client": ("127.0.0.1", 5000),
        "server": ("127.0.0.1", 8000),
        "root_path": "",
    }


async def _drive(headers: list[tuple[bytes, bytes]]) -> tuple[dict, list[dict]]:
    """请求过一遍中间件，返回 (app 内观测值, send 消息列表)。

    观测 = correlation contextvar + trace contextvar（函数级 import：RED 期
    logging.trace 不存在 → ImportError 即本文件全部【R】用例的失败形态）。
    """
    from inkflow.logging.correlation import get_request_correlation_id
    from inkflow.logging.trace import get_trace_context

    seen: dict = {}
    messages: list[dict] = []

    async def inner(scope: dict, receive, send) -> None:
        seen["correlation_id"] = get_request_correlation_id()
        seen["trace"] = get_trace_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    mw = CorrelationIdMiddleware(inner)

    async def send(msg: dict) -> None:
        messages.append(msg)

    await mw(_http_scope(headers), None, send)
    return seen, messages


def _resp_headers(messages: list[dict]) -> dict[bytes, bytes]:
    """http.response.start 头表（键小写 bytes）。"""
    start = next(m for m in messages if m["type"] == "http.response.start")
    return {bytes(k).lower(): bytes(v) for k, v in start.get("headers", [])}


def _assert_trace_id(value: str) -> None:
    assert re.fullmatch(r"[0-9a-f]{32}", value), f"trace_id 须 32 位小写 hex，实际 {value!r}"
    assert int(value, 16) != 0, "trace_id 不得为全零（OTel 无效值）"


def _assert_span_id(value: str) -> None:
    assert re.fullmatch(r"[0-9a-f]{16}", value), f"span_id 须 16 位小写 hex，实际 {value!r}"
    assert int(value, 16) != 0, "span_id 不得为全零（OTel 无效值）"


class TestFallbackGeneration:
    """契约 1+2：全空头 → correlation uuid4 + 根 trace 兜底生成（当前必 FAIL）。"""

    async def test_no_headers_generates_uuid_correlation(self):
        seen, _ = await _drive([])
        correlation_id = seen["correlation_id"]
        assert correlation_id, "无头请求必须兜底生成 uuid4 correlation_id（#931 根因 1）"
        parsed = uuid.UUID(correlation_id)  # 非法 uuid → ValueError FAIL
        assert parsed.version == 4
        assert str(parsed) == correlation_id.lower()

    async def test_no_traceparent_generates_root_trace(self):
        seen, _ = await _drive([])
        ctx = seen["trace"]
        assert ctx is not None, "无 traceparent 必须兜底生成根 TraceContext（#931 根因 4）"
        _assert_trace_id(ctx.trace_id)
        _assert_span_id(ctx.span_id)
        assert ctx.parent_span_id == "", "根 span 的 parent_span_id 为空串"

    async def test_two_requests_get_different_fallback_ids(self):
        seen1, _ = await _drive([])
        seen2, _ = await _drive([])
        assert seen1["trace"].trace_id != seen2["trace"].trace_id
        assert seen1["correlation_id"] != seen2["correlation_id"]


class TestTraceparentChildSpan:
    """契约 2：有效头 → 同 trace_id + 子 span（parent=传入 span）。"""

    async def test_valid_header_same_trace_child_span(self):
        seen, _ = await _drive(
            [(b"traceparent", VALID_TP.encode()), (b"x-correlation-id", b"c-931")]
        )
        assert seen["correlation_id"] == "c-931"  # 头沿用（B4 #496 语义不变）
        ctx = seen["trace"]
        assert ctx.trace_id == TRACE_ID_A, "同 trace_id（订单号贯穿）"
        assert ctx.parent_span_id == SPAN_ID_A, "parent_span_id = 传入 span_id（工序号衔接）"
        _assert_span_id(ctx.span_id)
        assert ctx.span_id != SPAN_ID_A, "内核 span 必须新生成，不得复用传入值"

    async def test_response_echo_traceparent_same_trace_new_span(self):
        seen, messages = await _drive([(b"traceparent", VALID_TP.encode())])
        hdrs = _resp_headers(messages)
        echoed = hdrs.get(b"traceparent")
        assert echoed is not None, "响应必须回写 traceparent（send wrapper）"
        m = TRACEPARENT_RE.match(echoed.decode("latin-1"))
        assert m is not None, f"回写 traceparent 格式非法: {echoed!r}"
        assert m.group(1) == seen["trace"].trace_id
        assert m.group(2) == seen["trace"].span_id
        assert m.group(3) == "01"

    async def test_response_echo_correlation_id(self):
        _seen, messages = await _drive([(b"x-correlation-id", b"c-echo")])
        hdrs = _resp_headers(messages)
        assert hdrs.get(b"x-correlation-id") == b"c-echo"


class TestInvalidTraceparentFallback:
    """契约 2：非法/缺量头 → 兜底新根，绝不崩溃、绝不全零透传。"""

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "garbage",
            "00-xyz",
            f"00-{'0' * 32}-{SPAN_ID_A}-01",  # 全零 trace_id
            f"00-{TRACE_ID_A}-{'0' * 16}-01",  # 全零 span_id
            f"01-{TRACE_ID_A}-{SPAN_ID_A}-01",  # 未知 version
            f"00-{TRACE_ID_A.upper()}-{SPAN_ID_A}-01",  # 大写 hex（W3C 规定小写）
            f"00-{TRACE_ID_A}-{SPAN_ID_A}",  # 缺 flags 段
        ],
    )
    async def test_invalid_header_falls_back_to_new_root(self, bad):
        seen, _ = await _drive([(b"traceparent", bad.encode("latin-1"))])
        ctx = seen["trace"]
        assert ctx is not None
        _assert_trace_id(ctx.trace_id)
        _assert_span_id(ctx.span_id)
        assert ctx.parent_span_id == "", "非法头必须整体弃用 → 新根（禁止部分采信）"


class TestContextIsolation:
    """契约 4：请求结束 reset；非 http 透传（【G】守护）。"""

    async def test_contextvars_reset_after_request(self):
        from inkflow.logging.correlation import get_request_correlation_id
        from inkflow.logging.trace import get_trace_context

        await _drive([(b"x-correlation-id", b"c-leak")])
        assert get_request_correlation_id() == "", "请求结束必须 reset correlation"
        assert get_trace_context() is None, "请求结束必须 reset trace"

    async def test_non_http_scope_passthrough(self):
        called: dict = {}

        async def inner(scope, receive, send):
            called["type"] = scope["type"]

        mw = CorrelationIdMiddleware(inner)
        await mw({"type": "lifespan"}, None, None)  # send 不会被调用
        assert called.get("type") == "lifespan"
