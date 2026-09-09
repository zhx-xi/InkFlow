"""F20 MCP 书级编排工具工厂 —— manage_book（#933，F44 零新增端点）。

访谈式 Planner（plan_start/plan_respond/plan_auto/plan_show/plan_confirm）+
书级运行（run/status/confirm/intervene/summary），经 HTTP 薄客户端访问内核。
骨架同 manage_tools/operation_tools：func 内延迟 import
infrastructure.http/kernel（load-bearing：测试 monkeypatch 模块属性动态生效）。
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.logging import instrument
from inkflow.mcp.tools import MCPTool
from inkflow.mcp.tools.schemas import ManageBookParams


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


#: 各 action 的本地必填字段（缺 → INVALID_ARGS 信封，零 HTTP 往返，spec §7 #16）。
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "plan_start": ("project_id", "one_liner"),
    "plan_respond": ("session_id",),
    "plan_auto": ("project_id", "one_liner"),
    "plan_show": ("session_id",),
    "plan_confirm": ("session_id",),
    "run": ("writing_plan_id",),
    "status": ("run_id",),
    "confirm": ("run_id",),
    "intervene": ("run_id", "intervene_action"),
    "summary": ("run_id",),
}


def _missing_required(params: ManageBookParams) -> list[str]:
    """返回当前 action 缺失的必填字段名列表（本地前置校验用）。"""
    required = _REQUIRED_FIELDS.get(params.action, ())
    return [field for field in required if getattr(params, field) is None]


async def _route_book(
    client: _HTTPClient, params: ManageBookParams, timeout: float | None
) -> object:
    """manage_book action 路由 → method/path/body/params（spec §2.2 映射表，#933）。"""
    if params.action == "plan_start":
        return await client.post(
            "/agent/books/planner",
            json=_compact(
                {
                    "project_id": params.project_id,
                    "one_liner": params.one_liner,
                    "mode": params.mode,
                    "source_outline_id": params.source_outline_id,
                }
            ),
            timeout=timeout,
        )
    if params.action == "plan_respond":
        return await client.post(
            f"/agent/books/planner/{params.session_id}/respond",
            json=_compact(
                {"answers": params.answers, "auto": params.auto, "confirm": params.confirm}
            ),
            timeout=timeout,
        )
    if params.action == "plan_auto":
        # 两步：start（镜像 plan_start body）→ respond auto=true（镜像 CLI plan auto）。
        first = await client.post(
            "/agent/books/planner",
            json=_compact(
                {
                    "project_id": params.project_id,
                    "one_liner": params.one_liner,
                    "mode": params.mode,
                    "source_outline_id": params.source_outline_id,
                }
            ),
            timeout=timeout,
        )
        session_id = first.get("session_id")
        if session_id is None:
            raise RuntimeError(f"planner start 响应缺少 session_id: {first!r}")
        return await client.post(
            f"/agent/books/planner/{session_id}/respond",
            json={"auto": True},
            timeout=timeout,
        )
    if params.action == "plan_show":
        return await client.get(f"/agent/books/planner/{params.session_id}")
    if params.action == "plan_confirm":
        return await client.post(
            f"/agent/books/planner/{params.session_id}/respond", json={"confirm": True}
        )
    if params.action == "run":
        return await client.post(
            "/agent/books/runs",
            json=_compact(
                {
                    "writing_plan_id": params.writing_plan_id,
                    "limits": params.limits,
                    "mode": params.mode,
                    "config": params.config,
                }
            ),
            timeout=timeout,
        )
    if params.action == "status":
        return await client.get(f"/agent/books/runs/{params.run_id}")
    if params.action == "confirm":
        return await client.post(
            f"/agent/books/runs/{params.run_id}/confirm",
            json={"approved": bool(params.approved), "decision": params.decision or ""},
        )
    if params.action == "intervene":
        return await client.post(
            f"/agent/books/runs/{params.run_id}/intervene",
            json=_compact(
                {
                    "action": params.intervene_action,
                    "target": params.target,
                    "to": params.to,
                    "payload": params.payload,
                }
            ),
        )
    return await client.get(f"/agent/books/runs/{params.run_id}/summary")


def build_manage_book_tool() -> MCPTool:
    """书级编排：访谈式 Planner + 书级运行（#933，F44 零新增端点）。"""

    @instrument(caller_type="mcp")
    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageBookParams.model_validate(kwargs)
        except ValidationError as exc:
            return _error(
                "INVALID_ARGS",
                str(exc),
                "请检查 action 枚举与必填字段（可经 tool_search 查询合法值），修正后重试",
            )
        missing = _missing_required(params)
        if missing:
            return _error(
                "INVALID_ARGS",
                f"缺少必填参数: {', '.join(missing)}",
                "请补充必填字段后重试（可经 tool_search 查询各 action 的字段面）",
            )
        try:
            from inkflow.infrastructure.http import (
                LLM_TASK_TIMEOUT,
                HttpApiError,
                InkFlowHTTPClient,
                map_http_error,
            )
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_book(client, params, LLM_TASK_TIMEOUT)
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
            name="manage_book",
            description=(
                "书级编排：访谈式 Planner（start/respond/auto/show/confirm）"
                "+ 书级运行（run/status/confirm/intervene/summary）"
            ),
            input_schema=ManageBookParams.model_json_schema(),
        ),
        func=_impl,
    )
