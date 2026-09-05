"""#931 RED 契约：InkFlowHTTPClient（CLI/MCP 入口面）注入 W3C traceparent 头。

缺陷背景（issue #931 根因 2）：client 只带 X-InkFlow-Token，CLI/MCP 全部请求
无 trace/correlation 头 → 内核日志链路 ID 恒空。

GREEN 实现契约（infrastructure/http/client.py MODIFY）
------------------------------------------------------
1. 每请求（含 stream_sse / get_bytes / multipart 面，统一走 _send 收口点）注入
   ``traceparent`` 头（格式 ``00-<32hex>-<16hex>-01``）：
   - 进程/调用外层已有 trace contextvar（如 MCP call_tool_result 已建根）→
     头 = 外层 ctx 的 trace_id + span_id（client 作为其子，span 复用父即头值）；
   - 无外层 ctx → 客户端实例级懒生成根：同一 client 生命周期内 trace_id 恒定，
     每请求新生成 span_id（一次 CLI 命令 = 一条 trace，多次轮询共享）。
2. 同步注入 ``X-Correlation-Id``：实例级 uuid4 一次生成、每请求复用（批量轮询
   共享一条操作链，issue 修复方向 2「命令级共享」语义）。
3. 已有头语义零回归：调用方显式 headers 覆盖（本契约仅约束 client 默认头，
   构造时 headers dict 扩展即可，per-request headers 优先级由 httpx 保证）。
4. trace/correlation 生成复用 logging.trace / uuid 标准原语，禁止在 http 层
   自造 hex 逻辑（层依赖：infrastructure → logging 合法，同 #924 先例）。

RED 形态：MockTransport handler 记录 request.headers → traceparent None FAIL。
patch 注入点镜像 test_http_client.py：源头模块命名空间 AsyncClient → 真实
httpx + MockTransport 轨（零网络）。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import httpx

from inkflow.infrastructure.http import InkFlowHTTPClient
from inkflow.infrastructure.kernel.bootstrap import KernelHandle

TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
TOKEN = "test-token-931"
BASE_URL = "http://127.0.0.1:38291/api/v1"


def _make_handle() -> KernelHandle:
    return KernelHandle(
        port=38291,
        token=TOKEN,
        pid=4242,
        version="0.1.0",
        started_at=datetime(2026, 9, 5, tzinfo=UTC),
        reused=True,
    )


@contextmanager
def _mock_http(handler):
    """真实 AsyncClient + MockTransport（镜像 test_http_client._mock_http，防递归）。"""
    real_cls = httpx.AsyncClient

    def _factory(**kwargs):
        return real_cls(transport=httpx.MockTransport(handler), **kwargs)

    with patch("inkflow.infrastructure.http.client.httpx.AsyncClient", new=_factory):
        yield


def _json_response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", BASE_URL))


class TestTraceparentInjection:
    async def test_default_request_carries_valid_traceparent(self):
        seen: list[httpx.Headers] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers)
            return _json_response(200, {"ok": True})

        with _mock_http(handler):
            async with InkFlowHTTPClient(_make_handle()) as client:
                await client.get("/projects")

        assert len(seen) == 1
        value = seen[0].get("traceparent")
        assert value is not None, "CLI/MCP 请求必须带 traceparent（#931 根因 2）"
        assert TRACEPARENT_RE.match(value), f"traceparent 格式非法: {value!r}"

    async def test_same_instance_shares_trace_id_per_request_new_span(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["traceparent"])
            return _json_response(200, {"ok": True})

        with _mock_http(handler):
            async with InkFlowHTTPClient(_make_handle()) as client:
                await client.get("/projects")
                await client.post("/projects", json={"name": "x"})

        m1, m2 = (TRACEPARENT_RE.match(v) for v in seen)
        assert m1 and m2
        assert m1.group(1) == m2.group(1), "同一 client（一次命令）共享 trace_id"
        assert m1.group(2) != m2.group(2), "每请求独立 span_id"

    async def test_correlation_header_uuid4_shared_per_instance(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["x-correlation-id"])
            return _json_response(200, {"ok": True})

        with _mock_http(handler):
            async with InkFlowHTTPClient(_make_handle()) as client:
                await client.get("/projects")
                await client.get("/projects")

        assert seen[0] == seen[1], "correlation 命令级共享（批量轮询一条链）"
        import uuid

        assert str(uuid.UUID(seen[0])) == seen[0].lower()

    async def test_outer_context_reused_as_parent_header(self):
        """外层已有 trace ctx（MCP 会话根）→ 头 = 外层 trace_id + 外层 span_id。"""
        from inkflow.logging.trace import TraceContext, set_trace_context

        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["traceparent"])
            return _json_response(200, {"ok": True})

        outer = TraceContext(trace_id="a" * 32, span_id="b" * 16, parent_span_id="")
        token = set_trace_context(outer)
        try:
            with _mock_http(handler):
                async with InkFlowHTTPClient(_make_handle()) as client:
                    await client.get("/projects")
        finally:
            from inkflow.logging.trace import reset_trace_context

            reset_trace_context(token)

        assert seen[0] == f"00-{'a' * 32}-{'b' * 16}-01", (
            "外层 ctx 存在时头必须复用（内核据此建子 span，trace 贯穿 CLI→内核）"
        )

    async def test_stream_sse_also_carries_traceparent(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("traceparent", ""))
            return httpx.Response(
                200,
                content=b'data: {"done": true}\n\n',
                headers={"content-type": "text/event-stream"},
                request=httpx.Request("POST", f"{BASE_URL}/x"),
            )

        with _mock_http(handler):
            async with InkFlowHTTPClient(_make_handle()) as client:
                frames = [f async for f in client.stream_sse("/write")]

        assert frames == [{"done": True}]
        assert TRACEPARENT_RE.match(seen[0]), "SSE 流式面同样带头（收口 _send）"
