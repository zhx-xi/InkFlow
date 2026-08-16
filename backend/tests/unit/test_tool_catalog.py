"""F39 M2 工具目录契约测试 — ToolSpec.group 分组扩展 + 完整 6 工具目录（spec §2.3/§5.1）.

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
           group: str = "project"    # 新增：分组键（writing/retrieval/audit/project）

2. 分组键与 UI 标签映射: writing→写作 / retrieval→检索 / audit→审计 / project→项目。
   project 组本期为空（预留未来项目域工具）。

3. TOOL_REGISTRY 升级为完整 6 工具目录（infrastructure/agent/tools/__init__.py
   MODIFY），顺序固定——先 5 只读（_TOOL_SPECS 原序）后 save_draft:

       search_characters   retrieval    搜索项目内角色档案（既有）
       check_foreshadowing retrieval    列出未回收伏笔（既有）
       get_prior_summary   retrieval    获取前文摘要（既有）
       audit_chapter       audit        单章一致性审计（既有）
       count_words         audit        中英文混合字数统计（既有）
       save_draft          writing      保存章节草稿（agent 唯一写面，新增静态化）

4. save_draft ToolSpec 静态化入 TOOL_REGISTRY（name/description/input_schema/group
   常量），其 func 仍由 build_save_draft_tool 动态构建（依赖 draft_service /
   audit_service 注入）——动态构建的 Tool.spec 与静态常量同源（group 亦为
   "writing"，dataclass 值相等）。

RED 预期（当前实现形态）
------------------------
- ToolSpec 无 group 字段: 访问 .group → AttributeError（dataclass 无该属性）；
  构造传 group= → TypeError（unexpected keyword argument）；dataclasses.fields
  缺 group → 断言 FAILED。均为用例体内异常/断言失败（FAILED），非收集 ERROR。
- TOOL_REGISTRY 仅 5 只读: len==6 / 顺序含 save_draft / save_draft 静态 spec
  断言 → AssertionError FAILED。
- 守护用例（既有 5 工具名在注册表、注册表项均为 ToolSpec、动态 func 可调用）
  RED 阶段即 PASS（刻意，防父侧误判）。
- 预期总结形态: 目标用例 FAILED（AttributeError/TypeError/AssertionError 混合），
  无 ERRORS；部分守护用例 PASSED。

GREEN 适配预警（冲突清单，交付报告同步）
----------------------------------------
- tests/unit/test_reader_tools.py::TestToolRegistry::test_registry_has_five_specs
  （assert len(TOOL_REGISTRY) == 5）与 test_registry_names_set（== 5 名集合）在
  GREEN 后 TOOL_REGISTRY=6 时翻红——GREEN 任务书须含这两处适配（len 5→6、
  集合补 save_draft），本文件不修改既有测试文件。
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

EXPECTED_CATALOG_NAMES = [*EXPECTED_READER_NAMES, "save_draft"]

EXPECTED_GROUPS = {
    "search_characters": "retrieval",
    "check_foreshadowing": "retrieval",
    "get_prior_summary": "retrieval",
    "audit_chapter": "audit",
    "count_words": "audit",
    "save_draft": "writing",
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
    """ToolSpec.group 字段契约（spec §2.3：默认 'project' + 四分组键）."""

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


# ── TestToolRegistryCatalog ─────────────────────────


class TestToolRegistryCatalog:
    """TOOL_REGISTRY 完整 6 工具目录契约（spec §5.1：顺序固定 + save_draft 收尾）."""

    def test_registry_has_six_specs(self):
        """注册表长度 6（5 只读 + save_draft 静态 spec）."""
        assert len(TOOL_REGISTRY) == 6
        # RED: 当前 5 → assert 5 == 6 FAILED

    def test_registry_names_fixed_order(self):
        """目录顺序固定：先 5 只读（_TOOL_SPECS 原序）后 save_draft."""
        assert [spec.name for spec in TOOL_REGISTRY] == EXPECTED_CATALOG_NAMES
        # RED: 实际 5 项 → 列表不等 FAILED

    def test_save_draft_is_last(self):
        """save_draft 是注册表最后一项（§5.1 排序契约）."""
        assert TOOL_REGISTRY[-1].name == "save_draft"
        # RED: 实际末项 count_words → 断言 FAILED

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
    """6 工具分组映射契约（spec §2.3 表格：retrieval×3 / audit×2 / writing×1）."""

    def test_group_mapping(self):
        """每工具 group 与契约表一致."""
        by_name = {spec.name: spec for spec in TOOL_REGISTRY}
        assert set(by_name) == set(EXPECTED_GROUPS)
        # RED: 缺 save_draft → 集合不等 FAILED
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
