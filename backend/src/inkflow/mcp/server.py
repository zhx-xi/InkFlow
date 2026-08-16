"""F20 MCP server 装配 —— stdio + 薄客户端经 HTTP（Issue #49）。"""

from __future__ import annotations

import json
from typing import Any

import anyio
import mcp.types as mt
from mcp.server import Server
from mcp.server.stdio import stdio_server

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


async def call_tool_result(
    tools: list[MCPTool], name: str, arguments: dict[str, Any] | None
) -> mt.CallToolResult:
    """tools/call handler 核心：查工具 → func(**arguments) → 信封 → isError。"""
    tool = next((t for t in tools if t.spec.name == name), None)
    if tool is None:
        text = json.dumps({"ok": False, "error": f"未知工具: {name}"}, ensure_ascii=False)
        return mt.CallToolResult(content=[mt.TextContent(type="text", text=text)], is_error=True)
    text = await tool.func(**(arguments or {}))
    try:
        ok = bool(json.loads(text).get("ok", False))
    except Exception:
        ok = False
    return mt.CallToolResult(content=[mt.TextContent(type="text", text=text)], is_error=not ok)


def build_mcp_server(tools: list[MCPTool] | None = None) -> Server:
    """装配 mcp 2.0 Server：on_list_tools / on_call_tool 回调。"""
    tools = tools if tools is not None else build_mcp_tools()

    async def _on_list_tools(ctx, params: mt.PaginatedRequestParams | None) -> mt.ListToolsResult:
        return await list_tools_result(tools)

    async def _on_call_tool(ctx, params: mt.CallToolRequestParams) -> mt.CallToolResult:
        return await call_tool_result(tools, params.name, params.arguments or {})

    return Server("inkflow", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


async def main() -> None:
    """stdio 启动：协议帧独占 stdout，日志走 stderr（MCP 硬约束）。"""
    server = build_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run() -> None:
    """console script 入口：inkflow-mcp = inkflow.mcp.server:run。"""
    anyio.run(main)


if __name__ == "__main__":
    run()
