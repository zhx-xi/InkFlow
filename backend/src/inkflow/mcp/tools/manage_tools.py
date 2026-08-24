"""F20 MCP manage_* 工具工厂 —— 8 个聚合管理工具，经 HTTP 薄客户端访问内核（Issue #49）。

每个工厂返回 MCPTool（ToolSpec + async func）；func 内延迟 import
infrastructure.http/kernel（load-bearing：测试 monkeypatch 模块属性动态生效，
禁模块级 from-import 绑定这两个包）。
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.mcp.tools import MCPTool
from inkflow.mcp.tools.schemas import (
    ManageChapterParams,
    ManageCharacterParams,
    ManageForeshadowingParams,
    ManageOutlineParams,
    ManageProjectParams,
    ManageRelationParams,
    ManageTimelineParams,
    ManageWorldParams,
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
    """失败信封：{"ok": False, "error": "<异常消息>"}；str(exc) 为空时兜底异常类型（#634）。"""
    message = str(exc) or f"{type(exc).__name__}: 内核调用失败"
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _fail_text(text: str) -> str:
    """失败信封：显式错误文本（如 "NOT_FOUND: ..."）。"""
    return json.dumps({"ok": False, "error": text}, ensure_ascii=False)


def _compact(mapping: dict[str, object]) -> dict[str, object]:
    """剔除值为 None 的键（httpx 会把 None 编码为空串 → 422，spec 固定陷阱）。"""
    return {key: value for key, value in mapping.items() if value is not None}


async def _route_project(client: _HTTPClient, params: ManageProjectParams) -> object:
    """manage_project action 路由 → method/path/body/params（spec §2.2 映射表）。"""
    if params.action == "create":
        return await client.post(
            "/projects",
            json=_compact(
                {
                    "name": params.name,
                    "tags": params.tags,
                    "language": params.language,
                    "target_words": params.target_words,
                }
            ),
        )
    if params.action == "list":
        return await client.get("/projects", params=_compact({"search": params.search}))
    if params.action == "get":
        return await client.get(f"/projects/{params.id}")
    if params.action == "update":
        return await client.patch(
            f"/projects/{params.id}",
            json=_compact(
                {
                    "name": params.name,
                    "tags": params.tags,
                    "language": params.language,
                    "target_words": params.target_words,
                }
            ),
        )
    if params.action == "delete":
        return await client.delete(
            f"/projects/{params.id}", params=_compact({"permanent": params.permanent})
        )
    return await client.post(f"/projects/{params.id}/restore")


async def _route_chapter(client: _HTTPClient, params: ManageChapterParams) -> object:
    """manage_chapter action 路由（spec §2.2 映射表）。"""
    if params.action == "create":
        return await client.post(
            f"/projects/{params.project_id}/chapters",
            json=_compact(
                {
                    "title": params.title,
                    "volume_id": params.volume_id,
                    "content": params.content,
                }
            ),
        )
    if params.action == "list":
        return await client.get(
            f"/projects/{params.project_id}/chapters",
            params=_compact({"volume_id": params.volume_id, "status": params.status}),
        )
    if params.action == "get":
        return await client.get(f"/chapters/{params.id}")
    if params.action == "update":
        return await client.patch(
            f"/chapters/{params.id}",
            json=_compact(
                {"title": params.title, "content": params.content, "status": params.status}
            ),
        )
    if params.action == "delete":
        return await client.delete(f"/chapters/{params.id}")
    return await client.post(
        f"/chapters/{params.id}/move", json=_compact({"to_volume": params.to_volume})
    )


async def _route_character(client: _HTTPClient, params: ManageCharacterParams) -> object:
    """manage_character action 路由（spec §2.2 映射表）。"""
    if params.action == "create":
        return await client.post(
            f"/projects/{params.project_id}/characters",
            json=_compact(
                {
                    "name": params.name,
                    "personality": params.personality,
                    "background": params.background,
                    "goals": params.goals,
                    "group_id": params.group_id,
                }
            ),
        )
    if params.action == "list":
        return await client.get(
            f"/projects/{params.project_id}/characters",
            params=_compact({"search": params.search, "group_id": params.group_id}),
        )
    if params.action == "get":
        return await client.get(f"/characters/{params.id}")
    if params.action == "update":
        return await client.patch(
            f"/characters/{params.id}",
            json=_compact(
                {
                    "name": params.name,
                    "personality": params.personality,
                    "background": params.background,
                    "goals": params.goals,
                    "group_id": params.group_id,
                }
            ),
        )
    if params.action == "delete":
        return await client.delete(f"/characters/{params.id}")
    return await client.post(f"/characters/{params.id}/restore")


async def _route_relation(client: _HTTPClient, params: ManageRelationParams) -> object:
    """manage_relation action 路由（F9 relations 三端点 + update）。"""
    if params.action == "create":
        return await client.post(
            f"/characters/{params.character_id}/relations",
            json=_compact(
                {
                    "source_id": params.source_id,
                    "target_id": params.target_id,
                    "relation_type": params.relation_type,
                    "description": params.description,
                }
            ),
        )
    if params.action == "list":
        return await client.get(f"/characters/{params.character_id}/relations")
    if params.action == "update":
        return await client.patch(
            f"/characters/{params.character_id}/relations/{params.id}",
            json=_compact(
                {"relation_type": params.relation_type, "description": params.description}
            ),
        )
    return await client.delete(f"/characters/{params.character_id}/relations/{params.id}")


async def _route_timeline(client: _HTTPClient, params: ManageTimelineParams) -> object:
    """manage_timeline action 路由（spec §2.2 映射表）。"""
    body_fields = (
        "title",
        "description",
        "time_value",
        "time_unit",
        "time_display",
        "narrative_position",
        "timeline_flag",
    )
    if params.action == "create":
        return await client.post(
            f"/projects/{params.project_id}/timeline/events",
            json=_compact({field: getattr(params, field) for field in body_fields}),
        )
    if params.action == "list":
        return await client.get(
            f"/projects/{params.project_id}/timeline/events",
            params=_compact({"search": params.search}),
        )
    if params.action == "get":
        return await client.get(f"/timeline/events/{params.id}")
    if params.action == "update":
        return await client.patch(
            f"/timeline/events/{params.id}",
            json=_compact({field: getattr(params, field) for field in body_fields}),
        )
    if params.action == "delete":
        return await client.delete(f"/timeline/events/{params.id}")
    return await client.get(f"/projects/{params.project_id}/timeline/check")


async def _route_world(client: _HTTPClient, params: ManageWorldParams) -> object:
    """manage_world action 路由（spec §2.2 映射表）。"""
    if params.action == "create":
        return await client.post(
            f"/projects/{params.project_id}/world-settings",
            json=_compact(
                {
                    "name": params.name,
                    "category": params.category,
                    "content": params.content,
                    "parent": params.parent,
                }
            ),
        )
    if params.action == "list":
        return await client.get(
            f"/projects/{params.project_id}/world-settings",
            params=_compact({"search": params.search, "category": params.category}),
        )
    if params.action == "get":
        return await client.get(f"/world-settings/{params.id}")
    if params.action == "update":
        return await client.patch(
            f"/world-settings/{params.id}",
            json=_compact(
                {
                    "name": params.name,
                    "category": params.category,
                    "content": params.content,
                    "parent": params.parent,
                }
            ),
        )
    if params.action == "delete":
        return await client.delete(f"/world-settings/{params.id}")
    return await client.post(f"/world-settings/{params.id}/restore")


async def _route_outline(client: _HTTPClient, params: ManageOutlineParams) -> object:
    """manage_outline action 路由（spec §2.2 映射表）。"""
    if params.action == "create":
        return await client.post(
            f"/projects/{params.project_id}/outlines",
            json=_compact(
                {
                    "name": params.name,
                    "description": params.description,
                    "sort_order": params.sort_order,
                }
            ),
        )
    if params.action == "list":
        return await client.get(
            f"/projects/{params.project_id}/outlines", params=_compact({"search": params.search})
        )
    if params.action == "get":
        return await client.get(f"/outlines/{params.id}")
    if params.action == "update":
        return await client.patch(
            f"/outlines/{params.id}",
            json=_compact(
                {
                    "name": params.name,
                    "description": params.description,
                    "sort_order": params.sort_order,
                }
            ),
        )
    if params.action == "delete":
        return await client.delete(f"/outlines/{params.id}")
    return await client.post(
        "/outlines/generate",
        json=_compact(
            {
                "project_id": params.project_id,
                "name": params.name,
                "prompt": params.prompt,
                "num_chapters": params.num_chapters,
            }
        ),
    )


async def _route_foreshadowing(client: _HTTPClient, params: ManageForeshadowingParams) -> object:
    """manage_foreshadowing action 路由（spec §2.2 映射表）。"""
    if params.action == "create":
        return await client.post(
            f"/projects/{params.project_id}/foreshadowings",
            json=_compact(
                {
                    "title": params.title,
                    "description": params.description,
                    "priority": params.priority,
                    "location": params.location,
                    "event_id": params.event_id,
                }
            ),
        )
    if params.action == "list":
        return await client.get(
            f"/projects/{params.project_id}/foreshadowings",
            params=_compact({"status": params.status, "search": params.search}),
        )
    if params.action == "get":
        return await client.get(f"/foreshadowings/{params.id}")
    if params.action == "update":
        return await client.patch(
            f"/foreshadowings/{params.id}",
            json=_compact(
                {
                    "title": params.title,
                    "description": params.description,
                    "priority": params.priority,
                    "location": params.location,
                    "event_id": params.event_id,
                }
            ),
        )
    if params.action == "delete":
        return await client.delete(f"/foreshadowings/{params.id}")
    if params.action == "resolve":
        return await client.post(f"/foreshadowings/{params.id}/resolve")
    return await client.post(f"/foreshadowings/{params.id}/reopen")


def build_manage_project_tool() -> MCPTool:
    """项目管理：创建/列出/查看/更新/删除/恢复项目。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageProjectParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_project(client, params)
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
            name="manage_project",
            description="项目管理：创建/列出/查看/更新/删除/恢复项目",
            input_schema=ManageProjectParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_chapter_tool() -> MCPTool:
    """章节与卷管理：创建/列出/查看/更新/删除/移动章节。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageChapterParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_chapter(client, params)
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
            name="manage_chapter",
            description="章节与卷管理：创建/列出/查看/更新/删除/移动章节",
            input_schema=ManageChapterParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_character_tool() -> MCPTool:
    """角色管理：创建/列出/查看/更新/删除/恢复角色档案。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageCharacterParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_character(client, params)
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
            name="manage_character",
            description="角色管理：创建/列出/查看/更新/删除/恢复角色档案",
            input_schema=ManageCharacterParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_relation_tool() -> MCPTool:
    """角色关系管理：创建/列出/查看/更新/删除角色间关系。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageRelationParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_relation(client, params)
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
            name="manage_relation",
            description="角色关系管理：创建/列出/查看/更新/删除角色间关系",
            input_schema=ManageRelationParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_timeline_tool() -> MCPTool:
    """时间线管理：创建/列出/查看/更新/删除时间线事件 + 一致性检查。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageTimelineParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_timeline(client, params)
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
            name="manage_timeline",
            description="时间线管理：创建/列出/查看/更新/删除时间线事件 + 一致性检查",
            input_schema=ManageTimelineParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_world_tool() -> MCPTool:
    """世界观管理：创建/列出/查看/更新/删除/恢复世界观设定。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageWorldParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_world(client, params)
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
            name="manage_world",
            description="世界观管理：创建/列出/查看/更新/删除/恢复世界观设定",
            input_schema=ManageWorldParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_outline_tool() -> MCPTool:
    """大纲管理：创建/列出/查看/更新/删除大纲 + AI 生成。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageOutlineParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_outline(client, params)
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
            name="manage_outline",
            description="大纲管理：创建/列出/查看/更新/删除大纲 + AI 生成",
            input_schema=ManageOutlineParams.model_json_schema(),
        ),
        func=_impl,
    )


def build_manage_foreshadowing_tool() -> MCPTool:
    """伏笔管理：创建/列出/查看/更新/删除伏笔 + 回收/重开。"""

    async def _impl(**kwargs: object) -> str:
        try:
            params = ManageForeshadowingParams.model_validate(kwargs)
        except ValidationError as exc:
            return _fail(exc)
        try:
            from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
            from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

            handle = await ensure_kernel()
            async with InkFlowHTTPClient(handle) as client:
                data = await _route_foreshadowing(client, params)
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
            name="manage_foreshadowing",
            description="伏笔管理：创建/列出/查看/更新/删除伏笔 + 回收/重开",
            input_schema=ManageForeshadowingParams.model_json_schema(),
        ),
        func=_impl,
    )
