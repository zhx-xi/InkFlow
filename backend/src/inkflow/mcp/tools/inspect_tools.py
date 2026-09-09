"""F20 MCP 只读巡检工具工厂 —— manage_config + manage_log（#933，零新增端点）。

manage_config：环境自检（provider_list/llm_status）；manage_log：日志巡检（query）。
两者均为只读面：仅 GET 端点，不暴露 set-key/PATCH 写面（凭据纪律，宿主侧自管）。
骨架同 manage_tools：func 内延迟 import infrastructure.http/kernel（load-bearing：
测试 monkeypatch 模块属性动态生效）。
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.logging import instrument
from inkflow.mcp.tools import MCPTool
from inkflow.mcp.tools.schemas import ManageConfigParams, ManageLogParams


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


def _serialize_data(value: object) -> object:
    """递归序列化：列表逐元素、pydantic 模型 model_dump(mode="json")、其余原样。"""
    if isinstance(value, list):
        return [_serialize_data(item) for item in value]
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper(mode="json")
        if isinstance(dumped, dict):
            return dumped
    return value


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
        "TIMEOUT": "服务端任务可能仍在进行，请先用对应 list/get 工具查询结果再决定是否重试",
    }
    return hints.get(code, "请检查参数与后端状态后重试")


def _compact(mapping: dict[str, object]) -> dict[str, object]:
    """剔除值为 None 的键（httpx 会把 None 编码为空串 → 422，spec 固定陷阱）。"""
    return {key: value for key, value in mapping.items() if value is not None}


async def _route_config(client: _HTTPClient, params: ManageConfigParams) -> object:
    """manage_config action 路由（#933 只读：仅 GET 端点，spec §2.2 映射表）。"""
    if params.action == "provider_list":
        return await client.get("/provider-configs")
    # llm_status：Provider 注册表 + embedding 注册态 + 可选向量状态摘要。
    response = await client.get("/provider-configs")
    providers_raw = response.get("items")
    providers = providers_raw if isinstance(providers_raw, list) else []
    embedding_model: dict[str, object] | None = None
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        for model in provider.get("models") or []:
            if isinstance(model, dict) and model.get("type") == "embedding":
                embedding_model = {
                    "provider": provider.get("name"),
                    "model_id": model.get("id"),
                }
                break
        if embedding_model is not None:
            break
    vector_status: object = None
    if params.project_id is not None:
        vector_status = await client.get(f"/projects/{params.project_id}/vector/status")
    return {
        "providers": providers,
        "embedding_model": embedding_model,
        "vector_status": vector_status,
    }


async def _route_log(client: _HTTPClient, params: ManageLogParams) -> object:
    """manage_log action 路由（#933 只读：GET /logs，from_ts/to_ts → from/to）。"""
    return await client.get(
        "/logs",
        params=_compact(
            {
                "level": params.level,
                "caller_type": params.caller_type,
                "project_id": params.project_id,
                "from": params.from_ts,
                "to": params.to_ts,
                "q": params.q,
                "correlation_id": params.correlation_id,
                "trace_id": params.trace_id,
                "page": params.page,
                "limit": params.limit,
            }
        ),
    )


def build_manage_config_tool() -> MCPTool:
    """环境自检（只读）：Provider 注册表 + embedding/向量状态摘要（#933）。"""

    @instrument(caller_type="mcp")
    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageConfigParams.model_validate(kwargs)
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
                data = await _route_config(client, params)
            return _ok(_serialize_data(data))
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
            name="manage_config",
            description=(
                "环境自检（只读）：Provider 注册表 + "
                "key_saved/embedding 注册态/向量状态摘要"
            ),
            input_schema=ManageConfigParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_log_tool() -> MCPTool:
    """日志巡检（只读）：结构化日志查询（level/caller_type/correlation/trace 过滤）。"""

    @instrument(caller_type="mcp")
    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageLogParams.model_validate(kwargs)
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
                data = await _route_log(client, params)
            return _ok(_serialize_data(data))
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
            name="manage_log",
            description=(
                "日志巡检（只读）：结构化日志查询"
                "（level/caller_type/correlation/trace 过滤）"
            ),
            input_schema=ManageLogParams.model_json_schema(),
        ),
        func=_impl,
    )
