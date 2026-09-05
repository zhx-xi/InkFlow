"""#931 RED 契约：MCP tools/call 审计 checkpoint 带 OTel trace 字段。

缺陷背景（issue #931 根因 2/5）：MCP 薄进程 call_tool_result 的审计 checkpoint
无 trace_id/span_id → 内核 store 里 MCP 操作与后续 HTTP 请求日志断链。

GREEN 实现契约
--------------
1. call_tool_result 每次工具调用**起点**建立调用级 trace：
   - 外层已有 trace contextvar → 派生子 span（同 trace_id，新 span_id，
     parent=外层 span_id）；
   - 无（stdio 会话）→ 取**进程级根**（模块单例懒生成一次，会话内所有调用共享
     trace_id = 一次会话一条链），本次调用 = 根的子 span（set contextvar，
     finally reset）。correlation 同理兜底（MCP 进程无 HTTP 中间件，调用级
     uuid4 correlation 由 trace ctx 设置点一并兜底）。
2. _emit_tool_audit 的 log_structured 走 contextvar 自动带 trace_id/span_id/
   parent_span_id（logging.trace 契约），经 #924 桥接 POST /logs body 含三字段。
3. body 新增键仅追加（#888 LogRecordInput 兼容：可选字段，前端旧记录零影响）。

RED 形态：inkflow.logging.trace 不存在 → 函数级 import ImportError；
桥接 body 无 trace_id → 断言 FAIL。镜像 test_mcp_log_bridge fake_env/fake_log
双缝（ensure_kernel / _make_client），零网络零真实内核。
"""

from __future__ import annotations

import importlib
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.mcp.log_bridge import get_forwarder, mcp_log_sink
from inkflow.mcp.server import call_tool_result
from inkflow.mcp.tools import MCPTool


def _trace_mod():
    """函数级 import（RED 期 ModuleNotFoundError；禁模块级防收集失败，f669 先例）。"""
    from inkflow.logging import trace

    return trace


kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
bridge_mod = importlib.import_module("inkflow.mcp.log_bridge")

_FAKE_TOKEN = "sekret-931"
TP_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


class FakeLogClient:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def post(self, path, *, json=None, timeout=None):
        self.posts.append({"path": path, "json": json, "timeout": timeout})
        return SimpleNamespace(status_code=200)

    def close(self) -> None:
        pass


def _ok_tool() -> MCPTool:
    async def _func(**_kw) -> str:
        return json.dumps({"ok": True, "data": {"id": "1"}})

    return MCPTool(
        spec=ToolSpec(name="probe_tool", description="d", input_schema={}),
        func=_func,
    )


@pytest.fixture
def fake_env(monkeypatch):
    fake_ensure = AsyncMock(
        return_value=SimpleNamespace(port=1, token=_FAKE_TOKEN, pid=2, version="0.1.0")
    )
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    client = FakeLogClient()
    monkeypatch.setattr(bridge_mod, "_make_client", lambda port, token: client)
    fwd = get_forwarder()
    fwd.reset()
    yield SimpleNamespace(client=client, forwarder=fwd)
    fwd.reset()


async def _call_and_body(fake_env) -> dict:
    with mcp_log_sink():
        await call_tool_result([_ok_tool()], "probe_tool", {})
    assert fake_env.client.posts, "桥接未发生（#924 回归？）"
    body = fake_env.client.posts[-1]["json"]
    assert isinstance(body, dict)
    return body


class TestMcpAuditTraceFields:
    async def test_audit_body_carries_otel_trace_fields(self, fake_env):
        """【R】MCP 审计 body 含 trace_id(32hex)/span_id(16hex)。"""
        body = await _call_and_body(fake_env)
        trace_id = body.get("trace_id")
        span_id = body.get("span_id")
        assert isinstance(trace_id, str) and re.fullmatch(r"[0-9a-f]{32}", trace_id), (
            f"#931: MCP 审计 checkpoint 必须带 OTel trace_id，实际 body={body!r}"
        )
        assert isinstance(span_id, str) and re.fullmatch(r"[0-9a-f]{16}", span_id)
        assert body.get("correlation_id"), "MCP 调用必须兜底 correlation"

    async def test_outer_trace_inherited_as_child(self, fake_env):
        """【R】外层已有 trace ctx → 审计记录同 trace_id + parent=外层 span。"""
        trace = _trace_mod()
        outer = trace.TraceContext(trace_id="a" * 32, span_id="b" * 16, parent_span_id="")
        token = trace.set_trace_context(outer)
        try:
            body = await _call_and_body(fake_env)
        finally:
            trace.reset_trace_context(token)
        assert body["trace_id"] == "a" * 32, "同 trace_id 贯穿宿主 → MCP → 内核"
        assert body.get("parent_span_id") == "b" * 16, "MCP span 的 parent = 宿主 span"
        assert body["span_id"] != "b" * 16

    async def test_correlation_shared_across_calls_in_conversation(self, fake_env):
        """【G→R】同一 MCP 进程多次调用 trace_id 稳定（会话级共享根 trace）。"""
        body1 = await _call_and_body(fake_env)
        body2 = await _call_and_body(fake_env)
        assert body1["trace_id"] == body2["trace_id"], (
            "#931: MCP 会话共享根 trace_id（一次会话一条链）"
        )
        assert body1["span_id"] != body2["span_id"], "每次调用独立子 span"
