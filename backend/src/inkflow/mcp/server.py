"""F20 MCP server 装配 —— stdio + 薄客户端经 HTTP（Issue #49）。"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from typing import Any

import anyio
import mcp.types as mt
from mcp.server import Server
from mcp.server.stdio import stdio_server

from inkflow.logging import log_structured
from inkflow.logging.correlation import (
    get_request_correlation_id,
    reset_request_correlation_id,
    set_request_correlation_id,
)
from inkflow.logging.trace import (
    TraceContext,
    get_trace_context,
    new_span_id,
    new_trace_id,
    reset_trace_context,
    set_trace_context,
)
from inkflow.mcp.log_bridge import get_forwarder, is_bridge_active, mcp_log_sink
from inkflow.mcp.tools import MCPTool, build_mcp_tools


async def list_tools_result(tools: list[MCPTool]) -> mt.ListToolsResult:
    """tools/list handler 核心：ToolSpec → mcp.types.Tool（inputSchema 同源）。"""
    return mt.ListToolsResult(
        tools=[
            mt.Tool(
                name=t.spec.name,
                description=t.spec.description,
                input_schema=t.spec.input_schema,
            )
            for t in tools
        ]
    )


def _promote_project_id(value: object) -> int | None:
    """纯数字串 → int；UUID/缺失 → None（顶层过滤面，params 保留原串）。"""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _emit_tool_audit(
    name: str,
    arguments: dict[str, Any],
    *,
    ok: bool,
    error_code: str | None,
    duration_ms: float,
) -> None:
    """tools/call 审计 checkpoint（#924）：白名单 params，绝不落原始 arguments。

    日志/转发故障静默（suppress）——审计失败绝不影响返回的信封。
    """
    raw_action = arguments.get("action")
    raw_project_id = arguments.get("project_id")
    with contextlib.suppress(Exception):
        log_structured(
            level="INFO" if ok else "WARN",
            caller_type="mcp",
            caller_name="inkflow-mcp",
            event=name,
            message_key="log.event.mcp_tool_call",
            params={
                "tool": name,
                "action": str(raw_action) if raw_action is not None else None,
                "project_id": str(raw_project_id) if raw_project_id is not None else None,
            },
            project_id=_promote_project_id(raw_project_id),
            error_code=error_code,
            duration_ms=duration_ms,
        )


#: #931 MCP 进程级根 trace（模块单例懒生成一次：stdio 会话内所有调用共享 trace_id）
_process_root: TraceContext | None = None


def _get_process_root() -> TraceContext:
    """返回进程级根 TraceContext（首次访问时懒生成；一次会话一条链）。"""
    global _process_root
    if _process_root is None:
        _process_root = TraceContext(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            parent_span_id="",
        )
    return _process_root


async def call_tool_result(
    tools: list[MCPTool], name: str, arguments: dict[str, Any] | None
) -> mt.CallToolResult:
    """tools/call handler 核心：查工具 → func(**arguments) → 信封 → isError。

    #924：已知/未知工具均在返回前发一条审计 checkpoint（经 mcp_log_sink →
    POST /logs）；审计/转发故障对信封零影响，finally 尽力 flush（未 attach 时
    无 client → flush 为廉价 no-op，不触发任何网络/内核拉起）。
    #931：每次调用起点建立调用级 trace（外层 ctx → 子 span；无外层 → 进程根的
    子 span），correlation 空时兜底 uuid4——审计 checkpoint 与后续内核 HTTP 请求
    同 trace 串链。finally 复位两个 contextvar（Token 顺序）。
    """
    args = arguments or {}
    started = time.perf_counter()
    text = ""
    ok = False
    error_code: str | None = None
    outer = get_trace_context()
    if outer is not None:
        call_ctx = TraceContext(
            trace_id=outer.trace_id,
            span_id=new_span_id(),
            parent_span_id=outer.span_id,
        )
    else:
        root = _get_process_root()
        call_ctx = TraceContext(
            trace_id=root.trace_id,
            span_id=new_span_id(),
            parent_span_id=root.span_id,
        )
    trace_token = set_trace_context(call_ctx)
    corr_token = None
    if not get_request_correlation_id():
        corr_token = set_request_correlation_id(str(uuid.uuid4()))
    try:
        # #931/#924：stdio 会话面惰性 attach（forwarder 尚无 client 时）——审计
        # checkpoint 须在返回前 POST /logs，而已知工具未必经 ensure_kernel（纯本地
        # 工具面），故在调用起点统一兜底；失败静默，对信封零影响（未知工具分支同语义）。
        if get_forwarder().client is None and is_bridge_active():
            from inkflow.infrastructure.kernel import ensure_kernel

            with contextlib.suppress(Exception):
                await ensure_kernel()
        tool = next((t for t in tools if t.spec.name == name), None)
        if tool is None:
            names = sorted(t.spec.name for t in tools)
            text = json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "UNKNOWN_TOOL",
                        "message": f"未知工具: {name}",
                        "hint": f"可用工具: {', '.join(names)}（可经 tool_search 查询）",
                    },
                },
                ensure_ascii=False,
            )
            error_code = "UNKNOWN_TOOL"
        else:
            text = await tool.func(**args)
            envelope: object | None = None
            try:
                envelope = json.loads(text)
            except Exception:
                envelope = None
            if isinstance(envelope, dict):
                ok = bool(envelope.get("ok", False))
                if not ok:
                    error = envelope.get("error")
                    if isinstance(error, dict):
                        code = error.get("code")
                        if isinstance(code, str):
                            error_code = code
            else:
                ok = False
        result = mt.CallToolResult(
            content=[mt.TextContent(type="text", text=text)], is_error=not ok
        )
        _emit_tool_audit(
            name,
            args,
            ok=ok,
            error_code=error_code,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
        return result
    finally:
        # 缓冲记录在 tools/call 返回前推送（集成测试紧跟轮询）；失败静默
        reset_trace_context(trace_token)
        if corr_token is not None:
            reset_request_correlation_id(corr_token)
        await anyio.to_thread.run_sync(get_forwarder().flush)


def build_mcp_server(tools: list[MCPTool] | None = None) -> Server:
    """装配 mcp 2.0 Server：on_list_tools / on_call_tool 回调。"""
    tools = tools if tools is not None else build_mcp_tools()

    async def _on_list_tools(ctx, params: mt.PaginatedRequestParams | None) -> mt.ListToolsResult:
        return await list_tools_result(tools)

    async def _on_call_tool(ctx, params: mt.CallToolRequestParams) -> mt.CallToolResult:
        return await call_tool_result(tools, params.name, params.arguments or {})

    return Server("inkflow", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


async def main() -> None:
    """stdio 启动：协议帧独占 stdout；#924 会话主体包在 mcp_log_sink 内转发内核。"""
    server = build_mcp_server()
    with mcp_log_sink():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())


def run() -> None:
    """console script 入口：inkflow-mcp = inkflow.mcp.server:run。"""
    anyio.run(main)


if __name__ == "__main__":
    run()
