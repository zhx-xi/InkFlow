"""F20 MCP 工具参数模型 —— 19 个工具 action 枚举 + 领域可选字段（Issue #49/#933/#1359）。

每个模型：action: Literal[...] 必填（路由子操作）+ 领域可选字段默认 None；
model_json_schema() 产物直接映射 MCP 协议 inputSchema（spec §2.2，Q1=A）。

#1233 补面：19 个模型全部继承 `_MCPParams`（extra="forbid"，未声明字段 → INVALID_ARGS）；
`WriteParams` 增 mode（deterministic/agentic）与 show_context（均仅 action=generate）；
`ManageProjectParams` 增 config（create/update 字段级更新语义）。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, WithJsonSchema

# Pydantic v2 对单值 Literal 的 schema 产物是 {"const": ...} 而非 {"enum": [...]}；
# MCP inputSchema 契约要求 action 枚举数组（test_mcp_schemas 断言 enum），
# 故单 action 模型用 WithJsonSchema 显式生成 {"type": "string", "enum": [...]}。


class _MCPParams(BaseModel):
    """MCP 工具参数基类：未声明字段禁止静默丢弃（#1233）。"""

    model_config = ConfigDict(extra="forbid")


class ManageProjectParams(_MCPParams):
    """项目管理工具参数：create/list/get/update/delete/restore。

    config：项目配置子对象字段级更新（镜像 CLI `inkflow project update --config`，
    仅 create/update 写路径透传）。
    """

    action: Literal["create", "list", "get", "update", "delete", "restore"]
    id: str | None = None
    name: str | None = None
    tags: list[str] | None = None
    language: str | None = None
    target_words: int | None = None
    config: dict[str, Any] | None = None
    search: str | None = None
    force: bool | None = None
    permanent: bool | None = None


class ManageChapterParams(_MCPParams):
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


class ManageCharacterParams(_MCPParams):
    """角色管理工具参数：create/list/get/update/delete/restore。"""

    action: Literal["create", "list", "get", "update", "delete", "restore"]
    project_id: str | None = None
    id: str | None = None
    name: str | None = None
    personality: str | None = None
    background: str | None = None
    goals: str | None = None
    brief: str | None = None
    group_id: str | None = None
    extra: dict | None = None
    search: str | None = None
    force: bool | None = None


class ManageRelationParams(_MCPParams):
    """角色关系管理工具参数：create/list/get/update/delete。"""

    action: Literal["create", "list", "get", "update", "delete"]
    project_id: str | None = None
    character_id: str | None = None
    id: str | None = None
    source_id: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    description: str | None = None


class ManageKnowledgeRelationParams(_MCPParams):
    """跨实体图谱关系管理工具参数：create/list/graph/get/update/delete（#1359）。

    与 ``manage_relation``（F9 角色↔角色三端点）**边界区分**：本工具打
    ``knowledge_relations`` 表（图谱关系真实承载表，六类实体源/目标），
    即 character↔world / →foreshadow / →timeline / →outline / →map_pin。
    """

    action: Literal["create", "list", "graph", "get", "update", "delete"]
    project_id: str | None = None
    id: str | None = None
    # 六元组字段名与 KnowledgeRelationCreate 逐字对齐（防 schema 漂移静默丢数据）
    source_type: str | None = None
    source_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    description: str | None = None
    # list 过滤（source 为 #479 预留）+ graph scope + 分页
    source: str | None = None
    scope: str | None = None
    offset: int | None = None
    limit: int | None = None


class ManageTimelineParams(_MCPParams):
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


class ManageWorldParams(_MCPParams):
    """世界观管理工具参数：create/list/get/update/delete/restore。"""

    action: Literal["create", "list", "get", "update", "delete", "restore"]
    project_id: str | None = None
    id: str | None = None
    name: str | None = None
    category: str | None = None
    content: str | None = None
    parent_id: str | None = None
    search: str | None = None
    force: bool | None = None


class ManageOutlineParams(_MCPParams):
    """大纲管理工具参数：create/list/get/update/delete/generate。"""

    action: Literal["create", "list", "get", "update", "delete", "generate"]
    project_id: str | None = None
    id: str | None = None
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    level: str | None = None
    parent_id: str | None = None
    volume_id: str | None = None
    chapter_id: str | None = None
    search: str | None = None
    force: bool | None = None
    prompt: str | None = None
    num_chapters: int | None = None


class ManageForeshadowingParams(_MCPParams):
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


class WriteParams(_MCPParams):
    """写作工具参数：generate/continue/revise + 草稿确认（#933，Q3=A）。

    mode=agentic 走 F27 自主编排（仅 action=generate）；
    show_context=True 返回上下文装配结果（仅 action=generate，镜像 CLI --show-context）。
    """

    action: Literal["generate", "continue", "revise", "confirm_draft", "reject_draft", "draft_list"]
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
    draft_id: str | None = None
    status: str | None = None
    source_outline_id: str | None = None
    title: str | None = None
    mode: Literal["deterministic", "agentic"] | None = None
    show_context: bool | None = None


class ManageBookParams(_MCPParams):
    """书级编排工具参数：访谈式 Planner + 书级运行（#933，F44 零新增端点）。"""

    action: Literal[
        "plan_start",
        "plan_respond",
        "plan_auto",
        "plan_show",
        "plan_confirm",
        "run",
        "status",
        "confirm",
        "intervene",
        "summary",
    ]
    project_id: str | None = None
    one_liner: str | None = None
    mode: str | None = None
    source_outline_id: str | None = None
    session_id: str | None = None
    answers: dict[str, str] | None = None
    auto: bool | None = None
    confirm: bool | None = None
    writing_plan_id: str | None = None
    limits: dict[str, int] | None = None
    config: dict | None = None
    run_id: str | None = None
    approved: bool | None = None
    decision: str | None = None
    intervene_action: str | None = None
    target: str | None = None
    to: str | None = None
    payload: dict | None = None
    # #1430：仅 `run` 用；成对（只给其一 → 服务端 422）
    force: bool | None = None
    confirm_overwrite: bool | None = None


class ManageConfigParams(_MCPParams):
    """环境自检工具参数（只读）：provider_list / llm_status（#933）。"""

    action: Literal["provider_list", "llm_status"]
    project_id: str | None = None


class ManageLogParams(_MCPParams):
    """日志巡检工具参数（只读）：query（#933，结构化日志查询）。"""

    action: Annotated[Literal["query"], WithJsonSchema({"type": "string", "enum": ["query"]})]
    level: str | None = None
    caller_type: str | None = None
    project_id: str | None = None
    from_ts: str | None = None
    to_ts: str | None = None
    q: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    page: int | None = None
    limit: int | None = None


class AuditParams(_MCPParams):
    """审计工具参数：project/chapter。"""

    action: Literal["project", "chapter"]
    project_id: str | None = None
    chapter_id: str | None = None
    include_static: bool | None = None


class ExtractParams(_MCPParams):
    """提取工具参数：extract/reindex/retrieve。"""

    action: Literal["extract", "reindex", "retrieve"]
    project_id: str | None = None
    content: str | None = None
    query: str | None = None
    entity_types: list[str] | None = None
    top_k: int | None = None
    min_score: float | None = None


class ExportParams(_MCPParams):
    """导出工具参数：export（get_raw 原始文本）。"""

    action: Annotated[Literal["export"], WithJsonSchema({"type": "string", "enum": ["export"]})]
    project_id: str | None = None
    format: str | None = None
    output_path: str | None = None


class SearchParams(_MCPParams):
    """搜索工具参数：search（GET /search）。"""

    action: Annotated[Literal["search"], WithJsonSchema({"type": "string", "enum": ["search"]})]
    project_id: str | None = None
    query: str | None = None
    content_type: str | None = None
    limit: int | None = None
    offset: int | None = None


class ManageSessionParams(_MCPParams):
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


class ToolSearchParams(_MCPParams):
    """工具发现工具参数：list（本地装配，不经 HTTP）。"""

    action: Annotated[Literal["list"], WithJsonSchema({"type": "string", "enum": ["list"]})]


ALL_SCHEMAS: dict[str, type[BaseModel]] = {
    "ManageProjectParams": ManageProjectParams,
    "ManageChapterParams": ManageChapterParams,
    "ManageCharacterParams": ManageCharacterParams,
    "ManageRelationParams": ManageRelationParams,
    "ManageKnowledgeRelationParams": ManageKnowledgeRelationParams,
    "ManageTimelineParams": ManageTimelineParams,
    "ManageWorldParams": ManageWorldParams,
    "ManageOutlineParams": ManageOutlineParams,
    "ManageForeshadowingParams": ManageForeshadowingParams,
    "WriteParams": WriteParams,
    "ManageBookParams": ManageBookParams,
    "ManageConfigParams": ManageConfigParams,
    "ManageLogParams": ManageLogParams,
    "AuditParams": AuditParams,
    "ExtractParams": ExtractParams,
    "ExportParams": ExportParams,
    "SearchParams": SearchParams,
    "ManageSessionParams": ManageSessionParams,
    "ToolSearchParams": ToolSearchParams,
}
