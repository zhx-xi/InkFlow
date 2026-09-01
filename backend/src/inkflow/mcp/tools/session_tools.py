"""F20 MCP 会话/发现工具工厂 —— manage_session + tool_search（Issue #49）。

manage_session 经 HTTP 薄客户端访问内核；tool_search 为本地装配（spec §7 #15，
不经 HTTP）。注册表在函数内延迟 import，避免与 mcp/tools/__init__ 循环导入。
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.mcp.tools import MCPTool
from inkflow.mcp.tools.schemas import ManageSessionParams, ToolSearchParams


class _HTTPClient(Protocol):
    """InkFlowHTTPClient 结构性接口（F38 方法面，避免模块级绑定真实类）。"""

    async def get(
        self, path: str, *, params: dict | None = None, json: dict | None = None
    ) -> dict: ...
    async def post(
        self,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        timeout: float | None = None,
    ) -> dict: ...
    async def patch(
        self, path: str, *, params: dict | None = None, json: dict | None = None
    ) -> dict: ...
    async def delete(
        self, path: str, *, params: dict | None = None, json: dict | None = None
    ) -> dict: ...
    async def get_raw(self, path: str, *, params: dict | None = None) -> str: ...


def _ok(data: object) -> str:
    """成功信封：{"ok": True, "data": <序列化结果>}（对齐 F26）。"""
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _error(code: str, message: str, hint: str) -> str:
    """结构化失败信封：error 为对象 {code, message, hint}（ADR-048 §4，LLM 自愈）。"""
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message, "hint": hint}},
        ensure_ascii=False,
    )


def _hint_for(code: str) -> str:
    """按错误码返回可修复提示（ADR-048 §4，LLM 自愈）。"""
    hints = {
        "NOT_FOUND": "请先经对应的 list 工具确认目标存在后再操作",
        "VALIDATION_ERROR": "请补充/修正必填字段后重试",
        "CONFIG_ERROR": "请重启内核重新获取 token 后重试",
        "LLM_ERROR": "请检查 provider/API key 配置后重试",
    }
    return hints.get(code, "请检查参数与后端状态后重试")


def _compact(mapping: dict[str, object]) -> dict[str, object]:
    """剔除值为 None 的键（httpx 会把 None 编码为空串 → 422，spec 固定陷阱）。"""
    return {key: value for key, value in mapping.items() if value is not None}


def _actions_of(tool: object) -> list[str]:
    """提取工具 input_schema 中 action 枚举（tool_search 本地装配数据源）。"""
    spec = getattr(tool, "spec", None)
    schema = getattr(spec, "input_schema", None)
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    action_prop = properties.get("action")
    if not isinstance(action_prop, dict):
        return []
    enum = action_prop.get("enum")
    if not isinstance(enum, list):
        return []
    return [str(item) for item in enum]


async def _route_session(client: _HTTPClient, params: ManageSessionParams) -> object:
    """manage_session action 路由（spec §2.2 映射表）。"""
    if params.action == "create":
        return await client.post(
            "/sessions",
            json=_compact(
                {
                    "session_type": params.session_type,
                    "project_id": params.project_id,
                    "title": params.title,
                    "description": params.description,
                }
            ),
        )
    if params.action == "list":
        return await client.get(
            "/sessions",
            params=_compact(
                {
                    "session_type": params.session_type,
                    "status": params.status,
                    "project_id": params.project_id,
                    "search": params.search,
                }
            ),
        )
    if params.action == "get":
        return await client.get(f"/sessions/{params.id}")
    if params.action in ("pause", "resume", "fail"):
        return await client.post(f"/sessions/{params.id}/{params.action}")
    if params.action == "complete":
        return await client.post(
            f"/sessions/{params.id}/complete",
            json=_compact({"result_json": params.result_json}) or None,
        )
    return await client.post(f"/sessions/{params.id}/logs", json=_compact({"content": params.logs}))


def build_manage_session_tool() -> MCPTool:
    """会话管理：创建/列出/查看/暂停/恢复/完成/失败 agent 会话。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageSessionParams.model_validate(kwargs)
        except ValidationError as exc:
            return _error(
                "INVALID_ARGS",
                str(exc),
                "请检查 action 枚举与必填字段（可经 tool_search 查询合法值），修正后重试",
            )
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_session(client, params)
            return _ok(data)
        except HttpApiError as exc:
            code, message = map_http_error(exc.status_code, exc.detail, exc.code)
            return _error(code, message, _hint_for(code))
        except KernelStartupError as exc:
            return _error("KERNEL_ERROR", f"内核启动失败: {exc}", "请重新拉起内核再试")
        except Exception as exc:
            return _error(
                "INTERNAL_ERROR",
                str(exc) or f"{type(exc).__name__}: 内核调用失败",
                "请携带完整上下文重试；若持续失败报告 API 层",
            )

    return MCPTool(
        spec=ToolSpec(
            name="manage_session",
            description="会话管理：创建/列出/查看/暂停/恢复/完成/失败 agent 会话",
            input_schema=ManageSessionParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_tool_search_tool() -> MCPTool:
    """工具发现：列出当前 MCP 工具面（渐进式发现入口，本地装配）。"""

    async def _impl(**kwargs: object) -> str:
        try:
            ToolSearchParams.model_validate(kwargs)
        except ValidationError as exc:
            return _error(
                "INVALID_ARGS",
                str(exc),
                "请检查 action 枚举与必填字段（可经 tool_search 查询合法值），修正后重试",
            )
        try:
            from inkflow.mcp.tools import MCP_TOOL_REGISTRY  # 延迟 import：避免包初始化循环

            data = [
                {
                    "name": tool.spec.name,
                    "description": tool.spec.description,
                    "actions": _actions_of(tool),
                }
                for tool in MCP_TOOL_REGISTRY
            ]
            return _ok(data)
        except Exception as exc:
            return _error(
                "INTERNAL_ERROR",
                str(exc) or f"{type(exc).__name__}: 内核调用失败",
                "请携带完整上下文重试；若持续失败报告 API 层",
            )

    return MCPTool(
        spec=ToolSpec(
            name="tool_search",
            description="工具发现：列出当前 MCP 工具面（渐进式发现入口）",
            input_schema=ToolSearchParams.model_json_schema(),
        ),
        func=_impl,
    )
