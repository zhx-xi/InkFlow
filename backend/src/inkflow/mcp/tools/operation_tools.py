"""F20 MCP 操作工具工厂 —— write/audit/extract/export/search（Issue #49）。

骨架同 manage_tools：func 内延迟 import infrastructure.http/kernel
（load-bearing：测试 monkeypatch 模块属性动态生效）。
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.mcp.tools import MCPTool
from inkflow.mcp.tools.schemas import (
    AuditParams,
    ExportParams,
    ExtractParams,
    SearchParams,
    WriteParams,
)


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


def _fail(exc: Exception) -> str:
    """失败信封：{"ok": False, "error": "<异常消息>"}（对齐 F26）。"""
    return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def _fail_text(text: str) -> str:
    """失败信封：显式错误文本（如 "NOT_FOUND: ..."）。"""
    return json.dumps({"ok": False, "error": text}, ensure_ascii=False)


def _compact(mapping: dict[str, object]) -> dict[str, object]:
    """剔除值为 None 的键（httpx 会把 None 编码为空串 → 422，spec 固定陷阱）。"""
    return {key: value for key, value in mapping.items() if value is not None}


async def _route_write(client: _HTTPClient, params: WriteParams) -> object:
    """write action 路由：非流式端点同步返回（Q3=A，spec §2.2 映射表）。"""
    if params.action == "generate":
        return await client.post(
            "/writing/generate",
            json=_compact(
                {
                    "project_id": params.project_id,
                    "chapter_id": params.chapter_id,
                    "outline": params.outline,
                    "context": params.context,
                    "style_hint": params.style_hint,
                    "target_words": params.target_words,
                }
            ),
        )
    if params.action == "continue":
        return await client.post(
            "/writing/continue",
            json=_compact(
                {
                    "project_id": params.project_id,
                    "chapter_id": params.chapter_id,
                    "existing_content": params.existing_content,
                    "context": params.context,
                    "target_words": params.target_words,
                    "style_hint": params.style_hint,
                }
            ),
        )
    # revise：feedback 优先；instruction 仅校验用，不转发到端点
    return await client.post(
        "/writing/revise",
        json=_compact(
            {
                "project_id": params.project_id,
                "chapter_id": params.chapter_id,
                "content": params.content,
                "feedback": params.feedback,
            }
        ),
    )


async def _route_audit(client: _HTTPClient, params: AuditParams) -> object:
    """audit action 路由：项目级四维审计 / 单章一致性审计。"""
    if params.action == "project":
        return await client.get(f"/projects/{params.project_id}/audit")
    return await client.post(
        f"/projects/{params.project_id}/chapters/{params.chapter_id}/audit",
        json=_compact({"include_static": params.include_static}),
    )


async def _route_extract(client: _HTTPClient, params: ExtractParams) -> object:
    """extract action 路由：文本提取 / 向量重索引 / 语义检索。"""
    if params.action == "extract":
        return await client.post(
            "/extract",
            json=_compact({"content": params.content, "project_id": params.project_id}),
        )
    if params.action == "reindex":
        return await client.post(
            f"/projects/{params.project_id}/vector/reindex",
            json=_compact({"entity_types": params.entity_types}),
        )
    return await client.post(
        f"/projects/{params.project_id}/vector/retrieve",
        json=_compact(
            {"query": params.query, "top_k": params.top_k, "min_score": params.min_score}
        ),
    )


async def _route_export(client: _HTTPClient, params: ExportParams) -> object:
    """export action 路由：get_raw 返回原始导出文本（F21）。"""
    return await client.get_raw(
        f"/projects/{params.project_id}/export", params=_compact({"format": params.format})
    )


async def _route_search(client: _HTTPClient, params: SearchParams) -> object:
    """search action 路由：GET /search（F22，q/types 参数名映射）。"""
    return await client.get(
        "/search",
        params=_compact(
            {
                "q": params.query,
                "project_id": params.project_id,
                "types": params.content_type,
                "limit": params.limit,
                "offset": params.offset,
            }
        ),
    )


def build_write_tool() -> MCPTool:
    """写作：续写下一章 / 续写指定章 / 按指令修订（同步返回拼接结果）。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = WriteParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_write(client, params)
            return _ok(_serialize_data(data))
        except HttpApiError as exc:
            code, message = map_http_error(exc.status_code, exc.detail, exc.code)
            return _fail_text(f"{code}: {message}")
        except KernelStartupError as exc:
            return _fail_text(f"内核启动失败: {exc}")
        except Exception as exc:
            return _fail(exc)

    return MCPTool(
        spec=ToolSpec(
            name="write",
            description="写作：续写下一章 / 续写指定章 / 按指令修订",
            input_schema=WriteParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_audit_tool() -> MCPTool:
    """审计：项目级四维审计 / 单章一致性审计。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = AuditParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_audit(client, params)
            return _ok(_serialize_data(data))
        except HttpApiError as exc:
            code, message = map_http_error(exc.status_code, exc.detail, exc.code)
            return _fail_text(f"{code}: {message}")
        except KernelStartupError as exc:
            return _fail_text(f"内核启动失败: {exc}")
        except Exception as exc:
            return _fail(exc)

    return MCPTool(
        spec=ToolSpec(
            name="audit",
            description="审计：项目级四维审计 / 单章一致性审计",
            input_schema=AuditParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_extract_tool() -> MCPTool:
    """提取：从文本提取设定实体 / 向量重索引 / 语义检索。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ExtractParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_extract(client, params)
            return _ok(_serialize_data(data))
        except HttpApiError as exc:
            code, message = map_http_error(exc.status_code, exc.detail, exc.code)
            return _fail_text(f"{code}: {message}")
        except KernelStartupError as exc:
            return _fail_text(f"内核启动失败: {exc}")
        except Exception as exc:
            return _fail(exc)

    return MCPTool(
        spec=ToolSpec(
            name="extract",
            description="提取：从文本提取设定实体 / 向量重索引 / 语义检索",
            input_schema=ExtractParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_export_tool() -> MCPTool:
    """导出：项目导出为 EPUB/Markdown/TXT/DOCX（原始文本返回）。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ExportParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_export(client, params)
            return _ok(_serialize_data(data))
        except HttpApiError as exc:
            code, message = map_http_error(exc.status_code, exc.detail, exc.code)
            return _fail_text(f"{code}: {message}")
        except KernelStartupError as exc:
            return _fail_text(f"内核启动失败: {exc}")
        except Exception as exc:
            return _fail(exc)

    return MCPTool(
        spec=ToolSpec(
            name="export",
            description="导出：项目导出为 EPUB/Markdown/TXT/DOCX",
            input_schema=ExportParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_search_tool() -> MCPTool:
    """搜索：跨内容类型全文搜索（关键词 + 语义）。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = SearchParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_search(client, params)
            return _ok(_serialize_data(data))
        except HttpApiError as exc:
            code, message = map_http_error(exc.status_code, exc.detail, exc.code)
            return _fail_text(f"{code}: {message}")
        except KernelStartupError as exc:
            return _fail_text(f"内核启动失败: {exc}")
        except Exception as exc:
            return _fail(exc)

    return MCPTool(
        spec=ToolSpec(
            name="search",
            description="搜索：跨内容类型全文搜索（关键词 + 语义）",
            input_schema=SearchParams.model_json_schema(),
        ),
        func=_impl,
    )
