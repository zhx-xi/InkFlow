"""F39 M2 工具目录契约测试 — ToolSpec.group 分组扩展 + 完整 34 工具目录（spec §2.3/§5.1）.

#955 迁移（RED-B）: 本文件从 26 自定义工具目录迁移至 34（−create_outline/update_outline
+ 10 新大纲工具），outline 读 3 属 retrieval、写 7 属 writing。

被测模块（全部已存在，本批为 MODIFY 追加段契约——顶部 import 可解析，
无收集期失败；RED 形态为用例体内 AttributeError/TypeError/断言失败混合）:
    from inkflow.domain.models.agent_tools import ToolSpec
    from inkflow.infrastructure.agent.tools import TOOL_REGISTRY
    from inkflow.infrastructure.agent.tools.save_draft_tool import (
        SaveDraftToolDeps, build_save_draft_tool,
    )

契约内容（父侧定稿，GREEN 按此实现）
------------------------------------
1. ToolSpec 增加 group 字段（domain/models/agent_tools.py MODIFY）:

       @dataclass
       class ToolSpec:
           name: str                 # 工具名（snake_case，稳定 id）
           description: str          # 用途描述（LLM 调用决策 + UI 勾选说明）
           input_schema: dict        # JSON Schema（Pydantic model_json_schema() 产物）
           group: str = "project"    # 分组键（writing/retrieval/audit/project）

2. 分组键与 UI 标签映射: writing→写作 / retrieval→检索 / audit→审计 / project→项目。
   project 组本期为空（预留未来项目域工具）。

3. TOOL_REGISTRY 升级为完整 34 工具目录（infrastructure/agent/tools/__init__.py
   MODIFY），顺序固定——按 ALL_TOOL_SPECS 过滤 allow_custom_agent 序:
       search_characters   retrieval    搜索项目内角色档案（既有）
       check_foreshadowing retrieval    列出未回收伏笔（既有）
       get_prior_summary   retrieval    获取前文摘要（既有）
       audit_chapter       audit        单章一致性审计（既有）
       count_words         audit        中英文混合字数统计（既有）
       save_draft          writing      保存章节草稿（既有）
       # #955: 设定写/设定改 各−1（−create_outline/update_outline）+ 新 outline 10
       #       + 世界读写 8 + 记忆 3 + 写作 3 = 34 项

4. save_draft ToolSpec 静态化入 TOOL_REGISTRY（name/description/input_schema/group
   常量），其 func 仍由 build_save_draft_tool 动态构建（依赖 draft_service /
   audit_service 注入）——动态构建的 Tool.spec 与静态常量同源（group 亦为
   "writing"，dataclass 值相等）。

RED 预期（当前实现形态，migrate 后因新目录未实现而部分 FAILED）
----------------------------------------------------------
- TOOL_REGISTRY 仅 26 项: len==34 / 顺序含新大纲工具 / TEST_GROUPS 集不等 → FAILED。
- 守护用例（既有 5 读工具名在注册表、注册表项均为 ToolSpec、动态 func 可调用）
  RED 阶段即 PASS（刻意，防父侧误判）。
- 预期总结形态: 目标用例 FAILED（AssertionError），无收集 ERROR；守护用例 PASSED。
"""
from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools import TOOL_REGISTRY
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftToolDeps,
    build_save_draft_tool,
)

# ── 常量 ──────────────────────────────────────

EXPECTED_READER_NAMES = [
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
]

# #955 迁移: 26→34（−create_outline/update_outline + 10 新大纲工具）
# #956 迁移: 34→39（reader 组内 +get_character/list_foreshadowing/get_foreshadowing/
#             list_world_settings/get_world_setting，§1.3 邻居序）
EXPECTED_CATALOG_NAMES = [
    "search_characters",
    "get_character",
    "check_foreshadowing",
    "list_foreshadowing",
    "get_foreshadowing",
    "list_world_settings",
    "get_world_setting",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
    "save_draft",
    "create_character",
    "create_world_setting",
    "update_character",
    "update_world_setting",
    "list_outlines",
    "get_outline",
    "list_plot_points",
    "create_overall_outline",
    "create_volume_outline",
    "create_chapter_outline",
    "update_volume_outline",
    "update_chapter_outline",
    "create_plot_point",
    "update_plot_point",
    "list_maps",
    "create_map",
    "update_map",
    "list_timeline_events",
    "create_timeline_event",
    "update_timeline_event",
    "create_foreshadowing",
    "update_foreshadowing",
    "memory_list",
    "memory_add",
    "memory_update",
    "generate",
    "continue",
    "revise",
]

# #955 迁移: −create_outline/update_outline + 10 新大纲工具
#（outline 读 3=retrieval、写 7=writing；world_rw 8 / memory 3 / writing 3 不变）
EXPECTED_GROUPS = {
    "search_characters": "retrieval",
    "get_character": "retrieval",
    "check_foreshadowing": "retrieval",
    "list_foreshadowing": "retrieval",
    "get_foreshadowing": "retrieval",
    "list_world_settings": "retrieval",
    "get_world_setting": "retrieval",
    "get_prior_summary": "retrieval",
    "audit_chapter": "audit",
    "count_words": "audit",
    "save_draft": "writing",
    "create_character": "writing",
    "create_world_setting": "writing",
    "update_character": "writing",
    "update_world_setting": "writing",
    "list_outlines": "retrieval",
    "get_outline": "retrieval",
    "list_plot_points": "retrieval",
    "create_overall_outline": "writing",
    "create_volume_outline": "writing",
    "create_chapter_outline": "writing",
    "update_volume_outline": "writing",
    "update_chapter_outline": "writing",
    "create_plot_point": "writing",
    "update_plot_point": "writing",
    "list_maps": "retrieval",
    "create_map": "writing",
    "update_map": "writing",
    "list_timeline_events": "retrieval",
    "create_timeline_event": "writing",
    "update_timeline_event": "writing",
    "create_foreshadowing": "writing",
    "update_foreshadowing": "writing",
    "memory_list": "retrieval",
    "memory_add": "writing",
    "memory_update": "writing",
    "generate": "writing",
    "continue": "writing",
    "revise": "writing",
}

VALID_GROUPS = {"writing", "retrieval", "audit", "project"}

# ── 辅助 ──────────────────────────────────────


def _registry_spec(name: str) -> ToolSpec | None:
    """按 name 查注册表 spec（未注册返回 None，供断言判定）."""
    for spec in TOOL_REGISTRY:
        if spec.name == name:
            return spec
    return None


def _make_save_draft_deps() -> SaveDraftToolDeps:
    """构造 SaveDraftToolDeps（AsyncMock service；仅构建工具用，不调用 func）."""
    return SaveDraftToolDeps(draft_service=AsyncMock(), audit_service=AsyncMock())


# ── TestToolSpecGroup ──────────────────────────────


class TestToolSpecGroup:
    """ToolSpec 字段契约（spec §2.3 group 默认 'project'；#838 allow_custom_agent/is_core 标记）."""

    def test_group_default_is_project(self):
        """默认 group='project'（字段默认值契约）."""
        spec = ToolSpec(name="search_characters", description="搜索角色", input_schema={})
        assert spec.group == "project"
        # RED: 当前 ToolSpec 无 group 字段 → AttributeError FAILED

    def test_group_explicit_value(self):
        """构造时显式传 group='writing' 保留."""
        spec = ToolSpec(name="save_draft", description="保存草稿", input_schema={}, group="writing")
        assert spec.group == "writing"
        # RED: 当前无 group 字段 → 构造 TypeError（unexpected keyword）FAILED

    def test_group_field_declared_in_dataclass(self):
        """ToolSpec 声明 group 字段（dataclasses.fields 契约）."""
        field_names = {f.name for f in fields(ToolSpec)}
        assert "group" in field_names
        # RED: 无 group 字段 → AssertionError FAILED

    def test_marker_fields_defaults(self):
        """#838: ToolSpec 新增 allow_custom_agent（默认 True）/ is_core（默认 False）."""
        spec = ToolSpec(name="search_characters", description="搜索角色", input_schema={})
        assert spec.allow_custom_agent is True
        assert spec.is_core is False
        # RED: 当前 ToolSpec 无这两个字段 → AttributeError FAILED


# ── TestToolRegistryCatalog ─────────────────────────


class TestToolRegistryCatalog:
    """TOOL_REGISTRY 完整 39 自定义工具目录契约（#838：ALL_TOOL_SPECS 过滤 allow_custom_agent）."""

    def test_registry_has_thirty_nine_specs(self):
        """注册表长度 39（49 统一目录 - 10 核心工具，#955 34 + #956 +5）."""
        assert len(TOOL_REGISTRY) == 39

    def test_registry_names_fixed_order(self):
        """目录顺序固定：39 自定义工具按 ALL_TOOL_SPECS 过滤序
        （读者 10 → save_draft → 设定写 2 → 设定改 2 → outline 10
        → 世界读写 8 → 记忆 3 → 写作 3）."""
        assert [spec.name for spec in TOOL_REGISTRY] == EXPECTED_CATALOG_NAMES

    def test_revise_is_last(self):
        """revise 是注册表最后一项（39 自定义工具排序契约）."""
        assert TOOL_REGISTRY[-1].name == "revise"
        # RED: 实际末项 save_draft → 断言 FAILED

    def test_registry_contains_five_reader_tools(self):
        """守护：既有 5 只读工具名全部在注册表中（RED 阶段即 PASS）."""
        names = {spec.name for spec in TOOL_REGISTRY}
        assert set(EXPECTED_READER_NAMES) <= names

    def test_registry_items_are_tool_specs(self):
        """守护：注册表每项均为 ToolSpec 实例（RED 阶段即 PASS）."""
        for spec in TOOL_REGISTRY:
            assert isinstance(spec, ToolSpec)


# ── TestToolGroupMapping ────────────────────────────


class TestToolGroupMapping:
    """39 工具分组映射契约（#838：retrieval×14 / audit×2 / writing×23）. """

    def test_group_mapping(self):
        """每工具 group 与契约表一致."""
        by_name = {spec.name: spec for spec in TOOL_REGISTRY}
        assert set(by_name) == set(EXPECTED_GROUPS)
        # RED: TOOL_REGISTRY=26 → 集合不等 FAILED
        for name, group in EXPECTED_GROUPS.items():
            assert by_name[name].group == group
            # RED: 即便集合相等，.group → AttributeError FAILED

    def test_valid_group_keys_only(self):
        """全部 group 值 ∈ {writing, retrieval, audit, project}."""
        for spec in TOOL_REGISTRY:
            assert spec.group in VALID_GROUPS
        # RED: .group → AttributeError FAILED

    def test_project_group_empty(self):
        """project 组本期为空：无任何工具 group='project'."""
        assert all(spec.group != "project" for spec in TOOL_REGISTRY)
        # RED: .group → AttributeError FAILED


# ── TestSaveDraftStaticSpec ─────────────────────────


class TestSaveDraftStaticSpec:
    """save_draft 静态 spec 契约（spec §5.1：静态化入 TOOL_REGISTRY）."""

    def test_save_draft_spec_registered(self):
        """save_draft 静态 spec 在注册表中（按 name 命中）."""
        spec = _registry_spec("save_draft")
        assert spec is not None
        # RED: save_draft 未注册 → None → 断言 FAILED

    def test_save_draft_spec_fields(self):
        """save_draft spec 常量字段完整：name/description 非空、input_schema 为 dict."""
        spec = _registry_spec("save_draft")
        assert spec is not None
        assert spec.name == "save_draft"
        assert isinstance(spec.description, str) and spec.description
        assert isinstance(spec.input_schema, dict)
        # RED: 未注册 → None → 首个断言 FAILED

    def test_save_draft_group_writing(self):
        """save_draft 属于 writing 组（agent 唯一写面）."""
        spec = _registry_spec("save_draft")
        assert spec is not None
        assert spec.group == "writing"
        # RED: 未注册 → None → 断言 FAILED（GREEN 后 .group 亦校验）


# ── TestSaveDraftDynamicFunc ────────────────────────


class TestSaveDraftDynamicFunc:
    """save_draft func 仍动态构建（spec §5.1：依赖 draft_service 注入，不进注册表）."""

    def test_build_save_draft_tool_spec_group(self):
        """动态构建的 Tool.spec 与静态化常量同源：group='writing'."""
        tool = build_save_draft_tool(_make_save_draft_deps())
        assert tool.spec.name == "save_draft"  # 守护：当前实现 PASS
        assert tool.spec.group == "writing"  # RED: .group → AttributeError FAILED

    def test_dynamic_spec_matches_registry_constants(self):
        """动态构建 spec 与注册表静态 spec 同源（同字段值，dataclass 相等）."""
        static = _registry_spec("save_draft")
        assert static is not None
        tool = build_save_draft_tool(_make_save_draft_deps())
        assert tool.spec == static
        # RED: save_draft 未注册 → static None → 首个断言 FAILED

    def test_build_save_draft_tool_func_callable(self):
        """守护：动态构建返回可调用 func（func 不进注册表，RED 阶段即 PASS）."""
        tool = build_save_draft_tool(_make_save_draft_deps())
        assert callable(tool.func)
