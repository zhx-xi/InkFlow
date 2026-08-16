"""F20 MCP 工具注册表 —— 15 个聚合工具（spec §4.1/§4.2，Issue #49）。

MCPTool 必须先于子模块工厂 import 定义（工厂模块顶层 from inkflow.mcp.tools
import MCPTool，依赖包初始化期间该名字已绑定，避免循环导入）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from inkflow.domain.models.agent_tools import ToolSpec


@dataclass
class MCPTool:
    """MCP 工具 —— ToolSpec（F26 契约）+ async func（信封 JSON 字符串）。"""

    spec: ToolSpec
    func: Callable[..., Awaitable[str]]


from inkflow.mcp.tools.manage_tools import (  # noqa: E402  # 工厂模块顶层依赖 MCPTool 已绑定：先定义再导入子模块（避免包初始化循环）
    build_manage_chapter_tool,
    build_manage_character_tool,
    build_manage_foreshadowing_tool,
    build_manage_outline_tool,
    build_manage_project_tool,
    build_manage_relation_tool,
    build_manage_timeline_tool,
    build_manage_world_tool,
)
from inkflow.mcp.tools.operation_tools import (  # noqa: E402  # 工厂模块顶层依赖 MCPTool 已绑定：先定义再导入子模块（避免包初始化循环）
    build_audit_tool,
    build_export_tool,
    build_extract_tool,
    build_search_tool,
    build_write_tool,
)
from inkflow.mcp.tools.session_tools import (  # noqa: E402  # 工厂模块顶层依赖 MCPTool 已绑定：先定义再导入子模块（避免包初始化循环）
    build_manage_session_tool,
    build_tool_search_tool,
)

MCP_TOOL_REGISTRY: list[MCPTool] = [
    build_manage_project_tool(),
    build_manage_chapter_tool(),
    build_manage_character_tool(),
    build_manage_relation_tool(),
    build_manage_timeline_tool(),
    build_manage_world_tool(),
    build_manage_outline_tool(),
    build_manage_foreshadowing_tool(),
    build_write_tool(),
    build_audit_tool(),
    build_extract_tool(),
    build_export_tool(),
    build_search_tool(),
    build_manage_session_tool(),
    build_tool_search_tool(),
]


def build_mcp_tools() -> list[MCPTool]:
    """返回当前工具面（与 MCP_TOOL_REGISTRY 同源，tools/list 数据源）。"""
    return list(MCP_TOOL_REGISTRY)
