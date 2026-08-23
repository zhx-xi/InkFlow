"""F20 MCP 工具参数模型 —— 15 个工具 action 枚举 + 领域可选字段（Issue #49）。

每个模型：action: Literal[...] 必填（路由子操作）+ 领域可选字段默认 None；
model_json_schema() 产物直接映射 MCP 协议 inputSchema（spec §2.2，Q1=A）。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, WithJsonSchema

# Pydantic v2 对单值 Literal 的 schema 产物是 {"const": ...} 而非 {"enum": [...]}；
# MCP inputSchema 契约要求 action 枚举数组（test_mcp_schemas 断言 enum），
# 故单 action 模型用 WithJsonSchema 显式生成 {"type": "string", "enum": [...]}。


class ManageProjectParams(BaseModel):
    """项目管理工具参数：create/list/get/update/delete/restore。"""

    action: Literal["create", "list", "get", "update", "delete", "restore"]
    id: str | None = None
    name: str | None = None
    tags: list[str] | None = None
    language: str | None = None
    target_words: int | None = None
    search: str | None = None
    force: bool | None = None
    permanent: bool | None = None


class ManageChapterParams(BaseModel):
    """章节与卷管理工具参数：create/list/get/update/delete/move。"""

    action: Literal["create", "list", "get", "update", "delete", "move"]
    project_id: str | None = None
    id: str | None = None
    volume_id: str | None = None
    title: str | None = None
    order: int | None = None
    content: str | None = None
    status: str | None = None
    to_volume: str | None = None


class ManageCharacterParams(BaseModel):
    """角色管理工具参数：create/list/get/update/delete/restore。"""

    action: Literal["create", "list", "get", "update", "delete", "restore"]
    project_id: str | None = None
    id: str | None = None
    name: str | None = None
    personality: str | None = None
    background: str | None = None
    goals: str | None = None
    group_id: str | None = None
    search: str | None = None
    force: bool | None = None


class ManageRelationParams(BaseModel):
    """角色关系管理工具参数：create/list/get/update/delete。"""

    action: Literal["create", "list", "get", "update", "delete"]
    project_id: str | None = None
    character_id: str | None = None
    id: str | None = None
    source_id: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    description: str | None = None


class ManageTimelineParams(BaseModel):
    """时间线管理工具参数：create/list/get/update/delete/check。"""

    action: Literal["create", "list", "get", "update", "delete", "check"]
    project_id: str | None = None
    id: str | None = None
    title: str | None = None
    description: str | None = None
    time_value: float | None = None
    time_unit: str | None = None
    time_display: str | None = None
    narrative_position: int | None = None
    timeline_flag: bool | None = None
    search: str | None = None


class ManageWorldParams(BaseModel):
    """世界观管理工具参数：create/list/get/update/delete/restore。"""

    action: Literal["create", "list", "get", "update", "delete", "restore"]
    project_id: str | None = None
    id: str | None = None
    name: str | None = None
    category: str | None = None
    content: str | None = None
    parent: str | None = None
    search: str | None = None
    force: bool | None = None


class ManageOutlineParams(BaseModel):
    """大纲管理工具参数：create/list/get/update/delete/generate。"""

    action: Literal["create", "list", "get", "update", "delete", "generate"]
    project_id: str | None = None
    id: str | None = None
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    search: str | None = None
    force: bool | None = None
    prompt: str | None = None
    num_chapters: int | None = None


class ManageForeshadowingParams(BaseModel):
    """伏笔管理工具参数：create/list/get/update/delete/resolve/reopen。"""

    action: Literal["create", "list", "get", "update", "delete", "resolve", "reopen"]
    project_id: str | None = None
    id: str | None = None
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    location: str | None = None
    event_id: str | None = None
    status: str | None = None
    search: str | None = None
    force: bool | None = None


class WriteParams(BaseModel):
    """写作工具参数：generate/continue/revise（同步返回拼接结果，Q3=A）。"""

    action: Literal["generate", "continue", "revise"]
    project_id: str | None = None
    chapter_id: str | None = None
    outline: str | None = None
    existing_content: str | None = None
    content: str | None = None
    feedback: str | None = None
    instruction: str | None = None
    target_words: int | None = None
    context: str | None = None
    style_hint: str | None = None


class AuditParams(BaseModel):
    """审计工具参数：project/chapter。"""

    action: Literal["project", "chapter"]
    project_id: str | None = None
    chapter_id: str | None = None
    include_static: bool | None = None


class ExtractParams(BaseModel):
    """提取工具参数：extract/reindex/retrieve。"""

    action: Literal["extract", "reindex", "retrieve"]
    project_id: str | None = None
    content: str | None = None
    query: str | None = None
    entity_types: list[str] | None = None
    top_k: int | None = None
    min_score: float | None = None


class ExportParams(BaseModel):
    """导出工具参数：export（get_raw 原始文本）。"""

    action: Annotated[Literal["export"], WithJsonSchema({"type": "string", "enum": ["export"]})]
    project_id: str | None = None
    format: str | None = None
    output_path: str | None = None


class SearchParams(BaseModel):
    """搜索工具参数：search（GET /search）。"""

    action: Annotated[Literal["search"], WithJsonSchema({"type": "string", "enum": ["search"]})]
    project_id: str | None = None
    query: str | None = None
    content_type: str | None = None
    limit: int | None = None
    offset: int | None = None


class ManageSessionParams(BaseModel):
    """会话管理工具参数：create/list/get/pause/resume/complete/fail/add_log。"""

    action: Literal["create", "list", "get", "pause", "resume", "complete", "fail", "add_log"]
    project_id: str | None = None
    id: str | None = None
    session_type: str | None = None
    title: str | None = None
    description: str | None = None
    # status/search 为 manage_session list 查询参数（test_mcp_tools 契约；test_mcp_schemas
    # 只锁字段存在性与可选性，允许追加字段）。
    status: str | None = None
    search: str | None = None
    logs: str | None = None
    result_json: str | None = None


class ToolSearchParams(BaseModel):
    """工具发现工具参数：list（本地装配，不经 HTTP）。"""

    action: Annotated[Literal["list"], WithJsonSchema({"type": "string", "enum": ["list"]})]


ALL_SCHEMAS: dict[str, type[BaseModel]] = {
    "ManageProjectParams": ManageProjectParams,
    "ManageChapterParams": ManageChapterParams,
    "ManageCharacterParams": ManageCharacterParams,
    "ManageRelationParams": ManageRelationParams,
    "ManageTimelineParams": ManageTimelineParams,
    "ManageWorldParams": ManageWorldParams,
    "ManageOutlineParams": ManageOutlineParams,
    "ManageForeshadowingParams": ManageForeshadowingParams,
    "WriteParams": WriteParams,
    "AuditParams": AuditParams,
    "ExtractParams": ExtractParams,
    "ExportParams": ExportParams,
    "SearchParams": SearchParams,
    "ManageSessionParams": ManageSessionParams,
    "ToolSearchParams": ToolSearchParams,
}
