"""F20 MCP 工具参数模型 schema 契约（M1 验收）— spec §2.2/§9（Issue #49，RED 阶段测试契约）。

15 个 MCP 工具参数模型（Q1=A 聚合 manage_*，action 枚举路由子操作）：
manage_project / manage_chapter / manage_character / manage_relation /
manage_timeline / manage_world / manage_outline / manage_foreshadowing /
write / audit / extract / export / search / manage_session / tool_search。

每个模型：action: Literal[...]（必填，枚举路由）+ 领域可选字段（str | None = None，
对某 action 无效的字段 LLM 不传）。模型生成 JSON Schema（model_json_schema()）
映射为 MCP 协议 inputSchema（spec §2.1 ToolSpec.input_schema 同源）。

── GREEN 实现契约 ────────────────────────────────────────────────
模块 inkflow.mcp.tools.schemas（CREATE，与 manage_tools.py/operation_tools.py/
session_tools.py 并列于 mcp/tools/）：
- 类名与 action 枚举（逐字对齐）：
  ManageProjectParams:      action=create/list/get/update/delete/restore
                            id, name, genre, language, target_words, search, force, permanent
  ManageChapterParams:      action=create/list/get/update/delete/move
                            project_id, id, volume_id, title, order, content, status, to_volume
  ManageCharacterParams:    action=create/list/get/update/delete/restore
                            project_id, id, name, personality, background, goals,
                            group_id, search, force
  ManageRelationParams:     action=create/list/get/update/delete
                            project_id, character_id, id, source_id, target_id,
                            relation_type, description
  ManageTimelineParams:     action=create/list/get/update/delete/check
                            project_id, id, title, description, time_value, time_unit,
                            time_display, narrative_position, timeline_flag, search
  ManageWorldParams:        action=create/list/get/update/delete/restore
                            project_id, id, name, category, content, parent, search, force
  ManageOutlineParams:      action=create/list/get/update/delete/generate
                            project_id, id, name, description, sort_order, search, force,
                            prompt, num_chapters
  ManageForeshadowingParams: action=create/list/get/update/delete/resolve/reopen
                            project_id, id, title, description, priority, location,
                            event_id, status, search, force
  WriteParams:              action=generate/continue/revise
                            project_id, chapter_id, outline, existing_content, content,
                            feedback, instruction, target_words, context, style_hint
  AuditParams:              action=project/chapter
                            project_id, chapter_id, include_static
  ExtractParams:            action=extract/reindex/retrieve
                            project_id, content, query, entity_types, top_k, min_score
  ExportParams:             action=export
                            project_id, format, output_path
  SearchParams:             action=search
                            project_id, query, content_type, limit, offset
  ManageSessionParams:      action=create/list/get/pause/resume/complete/fail/add_log
                            project_id, id, session_type, title, description, logs, result_json
  ToolSearchParams:         action=list
- action 字段类型 Literal[...]（str 子集，model_json_schema 生成 enum 数组）。
- 领域字段全部可选（str | int | bool | None，默认 None）；id/project_id 等 ID 字段
  为 str（LLM 透传 JSON 字符串，工具层直接拼端点路径）。
- 模块还导出 ALL_SCHEMAS: dict[str, type[BaseModel]]（15 模型名→类，供注册表/
  tools/list 生成 inputSchema）。

── RED 形态说明 ─────────────────────────────────────────────────
inkflow.mcp.tools.schemas 模块整个不存在 → 顶部 import 收集期
ModuleNotFoundError（exit 2，规则 1c 整模块 RED 首选形态）。
GREEN 落地后整文件自动转绿。

── 测试约定 ─────────────────────────────────────────────────────
- pytest-asyncio 1.x STRICT 模式：async 用例显式 @pytest.mark.asyncio。
- 非法 action 断言用 pytest.raises(ValidationError)（Pydantic Literal 校验）。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from inkflow.mcp.tools.schemas import (
    ALL_SCHEMAS,
    AuditParams,
    ExportParams,
    ExtractParams,
    ManageChapterParams,
    ManageCharacterParams,
    ManageForeshadowingParams,
    ManageOutlineParams,
    ManageProjectParams,
    ManageRelationParams,
    ManageSessionParams,
    ManageTimelineParams,
    ManageWorldParams,
    SearchParams,
    ToolSearchParams,
    WriteParams,
)

# ── 契约表：模型名 → (action 枚举, 关键字段集合) ──────────────────

_CONTRACT: dict[str, tuple[list[str], list[str]]] = {
    "ManageProjectParams": (
        ["create", "list", "get", "update", "delete", "restore"],
        ["id", "name", "genre", "language", "target_words", "search", "force", "permanent"],
    ),
    "ManageChapterParams": (
        ["create", "list", "get", "update", "delete", "move"],
        ["project_id", "id", "volume_id", "title", "order", "content", "status", "to_volume"],
    ),
    "ManageCharacterParams": (
        ["create", "list", "get", "update", "delete", "restore"],
        [
            "project_id",
            "id",
            "name",
            "personality",
            "background",
            "goals",
            "group_id",
            "search",
            "force",
        ],
    ),
    "ManageRelationParams": (
        ["create", "list", "get", "update", "delete"],
        [
            "project_id",
            "character_id",
            "id",
            "source_id",
            "target_id",
            "relation_type",
            "description",
        ],
    ),
    "ManageTimelineParams": (
        ["create", "list", "get", "update", "delete", "check"],
        [
            "project_id",
            "id",
            "title",
            "description",
            "time_value",
            "time_unit",
            "time_display",
            "narrative_position",
            "timeline_flag",
            "search",
        ],
    ),
    "ManageWorldParams": (
        ["create", "list", "get", "update", "delete", "restore"],
        ["project_id", "id", "name", "category", "content", "parent", "search", "force"],
    ),
    "ManageOutlineParams": (
        ["create", "list", "get", "update", "delete", "generate"],
        [
            "project_id",
            "id",
            "name",
            "description",
            "sort_order",
            "search",
            "force",
            "prompt",
            "num_chapters",
        ],
    ),
    "ManageForeshadowingParams": (
        ["create", "list", "get", "update", "delete", "resolve", "reopen"],
        [
            "project_id",
            "id",
            "title",
            "description",
            "priority",
            "location",
            "event_id",
            "status",
            "search",
            "force",
        ],
    ),
    "WriteParams": (
        ["generate", "continue", "revise"],
        [
            "project_id",
            "chapter_id",
            "outline",
            "existing_content",
            "content",
            "feedback",
            "instruction",
            "target_words",
            "context",
            "style_hint",
        ],
    ),
    "AuditParams": (
        ["project", "chapter"],
        ["project_id", "chapter_id", "include_static"],
    ),
    "ExtractParams": (
        ["extract", "reindex", "retrieve"],
        ["project_id", "content", "query", "entity_types", "top_k", "min_score"],
    ),
    "ExportParams": (
        ["export"],
        ["project_id", "format", "output_path"],
    ),
    "SearchParams": (
        ["search"],
        ["project_id", "query", "content_type", "limit", "offset"],
    ),
    "ManageSessionParams": (
        ["create", "list", "get", "pause", "resume", "complete", "fail", "add_log"],
        ["project_id", "id", "session_type", "title", "description", "logs", "result_json"],
    ),
    "ToolSearchParams": (
        ["list"],
        [],
    ),
}

_MODEL_ATTR: dict[str, Any] = {
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


class TestSchemasContract:
    """15 参数模型：action 枚举 + 关键字段 + JSON Schema 生成（M1）。"""

    def test_all_models_present(self):
        """ALL_SCHEMAS 恰好 15 个模型名，与契约表一致。"""
        assert set(ALL_SCHEMAS) == set(_CONTRACT)
        assert len(ALL_SCHEMAS) == 15

    @pytest.mark.parametrize("model_name", list(_CONTRACT))
    def test_action_enum_valid_values(self, model_name):
        """action 字段 Literal 枚举合法值 = 契约表（model_json_schema enum）。"""
        model = _MODEL_ATTR[model_name]
        schema = model.model_json_schema()
        properties = schema["properties"]
        assert "action" in properties
        assert properties["action"]["type"] == "string"
        expected, _ = _CONTRACT[model_name]
        assert properties["action"]["enum"] == expected

    @pytest.mark.parametrize("model_name", list(_CONTRACT))
    def test_action_required(self, model_name):
        """action 是必填字段（schema required 含 action）。"""
        model = _MODEL_ATTR[model_name]
        schema = model.model_json_schema()
        assert "action" in schema.get("required", [])

    @pytest.mark.parametrize("model_name", list(_CONTRACT))
    def test_domain_fields_present(self, model_name):
        """契约表关键字段全部出现在 properties（可空字段）。"""
        model = _MODEL_ATTR[model_name]
        _, fields = _CONTRACT[model_name]
        properties = model.model_json_schema()["properties"]
        for field in fields:
            assert field in properties, f"{model_name} 缺字段 {field}"

    @pytest.mark.parametrize("model_name", list(_CONTRACT))
    def test_fields_optional(self, model_name):
        """领域字段全部可选（不在 required 中），默认 None。"""
        model = _MODEL_ATTR[model_name]
        _, fields = _CONTRACT[model_name]
        schema = model.model_json_schema()
        required = set(schema.get("required", []))
        for field in fields:
            assert field not in required, f"{model_name}.{field} 不应必填"

    @pytest.mark.parametrize("model_name", list(_CONTRACT))
    def test_json_schema_is_object(self, model_name):
        """model_json_schema() 为 object 类型，映射 MCP inputSchema（spec §2.1）。"""
        schema = _MODEL_ATTR[model_name].model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


class TestActionValidation:
    """非法 action → ValidationError（spec §7 #12：协议层校验）。"""

    def test_manage_project_invalid_action(self):
        with pytest.raises(ValidationError):
            ManageProjectParams(action="frobnicate", name="x")

    def test_write_invalid_action(self):
        with pytest.raises(ValidationError):
            WriteParams(action="rewind", project_id="p1", chapter_id="c1")

    def test_audit_invalid_action(self):
        with pytest.raises(ValidationError):
            AuditParams(action="all", project_id="p1")

    def test_tool_search_invalid_action(self):
        with pytest.raises(ValidationError):
            ToolSearchParams(action="find")

    def test_manage_session_invalid_action(self):
        with pytest.raises(ValidationError):
            ManageSessionParams(action="abort", id="s1")

    def test_valid_action_constructs(self):
        """合法 action 构造成功（正例守护）。"""
        p = ManageProjectParams(action="create", name="新项目", genre="玄幻")
        assert p.action == "create"
        assert p.name == "新项目"

    def test_empty_action_rejected(self):
        """action 缺省（无默认值）→ ValidationError。"""
        with pytest.raises(ValidationError):
            ManageProjectParams(name="x")  # type: ignore[call-arg]  # 契约：action 必填


class TestSchemaSubclass:
    """模型均为 Pydantic BaseModel 子类（input_schema 生成前提，spec §2.2）。"""

    def test_all_base_model(self):
        for name, model in ALL_SCHEMAS.items():
            assert issubclass(model, BaseModel), f"{name} 不是 BaseModel 子类"

    def test_field_defaults_none(self):
        """关键字段默认 None（str | None = None）。"""
        p = ManageChapterParams(action="list", project_id="p1")
        assert p.title is None
        assert p.volume_id is None
