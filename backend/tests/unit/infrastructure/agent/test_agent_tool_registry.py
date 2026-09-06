"""F39/#838 统一工具目录 + allow_custom_agent 标记 + build_tools_by_ids 运行时物化 — 契约测试.

#955 迁移（RED-B，2026-09-06）: 本文件从 9 组 35 工具契约迁移至 10 组 44 工具
（−create_outline/update_outline + 10 新大纲工具 + delete_plot_point 核心），
TOOL_REGISTRY 26→34，核心集 9→10。

被测模块（GREEN 实现，RED 阶段顶部 import 或属性访问失败 → 收集期 ERROR）:
    from inkflow.domain.models.agent_tools import ToolSpec
    from inkflow.infrastructure.agent.tools import (
        ALL_TOOL_SPECS, TOOL_REGISTRY, UnifiedToolDeps, build_tools_by_ids,
    )
    from inkflow.domain.services.agent_entity_service import _validate_tool_ids
    from inkflow.domain.ports.agent_errors import ToolReferenceError

契约内容（父侧定稿 #838, 2026-08-31 用户拍板 + #955 迁移）
------------------------------------------------------
1. ToolSpec 加标记: `allow_custom_agent: bool = True` + `is_core: bool = False`
   （dataclass 字段带默认值；既有构造处无需逐个传）。

2. ALL_TOOL_SPECS（统一目录）= 全部 10 组 44 个工具（reader/save_draft/
   setting_write/setting_update/outline/world_rw/memory/writing/delete/agent_chain），
   无遗漏、无重复 name。
   #955 迁移: −create_outline/update_outline + 10 新大纲工具 + delete_plot_point；count 35→44。

3. 标记规则:
   - `agent_run`/`agent_call`（agent 链）+ 8 个删除类（delete_character /
     delete_world_setting / delete_outline / delete_plot_point / delete_map /
     delete_timeline_event / delete_foreshadowing / memory_remove）=
     `allow_custom_agent=False, is_core=True`（#955 迁移: 核心集 9→10，+delete_plot_point）
   - `memory_*`（memory_list / memory_add / memory_update）+ `writing`（generate /
     continue / revise）暴露 = `allow_custom_agent=True, is_core=False`（默认值）
   - 其余读写工具均默认暴露（allow_custom_agent=True, is_core=False）
   - #955: 10 新大纲非核心工具均默认暴露（allow_custom_agent=True, is_core=False）

4. TOOL_REGISTRY = `[s for s in ALL_TOOL_SPECS if s.allow_custom_agent]`（34 个）——
   供 `_validate_tool_ids`/内置 seed/CLI tools list 消费（兼容别名）。
   #955 迁移: 26→34。

5. `_validate_tool_ids` 拒绝 `allow_custom_agent=False` 工具（自定义 agent 不可勾选
   目录内核心工具；目录外名亦拒绝——均为 ToolReferenceError）。

6. `build_tools_by_ids(tool_ids, deps)` 按 tool_ids 白名单物化工具（调 10 组 build
   后按 spec.name 过滤拼接；未知名忽略）。

RED 预期（当前实现形态，migrate 后因新契约未实现而整体 FAILED）
--------------------------------------------------------------
- UnifiedToolDeps 无 `outline` 字段: `_make_unified_deps` 传 outline= → TypeError FAILED。
- ALL_TOOL_SPECS 现为 35（缺 10 新大纲 + delete_plot_point）: len==44 → AssertionError FAILED。
- CORE_NAMES 集缺 delete_plot_point，TOOL_REGISTRY 现为 26: ==34 → AssertionError FAILED。
- 预期形态: 目标用例 FAILED（TypeError/AssertionError 混合），无收集 ERROR。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.ports.agent_errors import ToolReferenceError
from inkflow.domain.services.agent_entity_service import _validate_tool_ids
from inkflow.infrastructure.agent.tools import (
    ALL_TOOL_SPECS,
    TOOL_REGISTRY,
    UnifiedToolDeps,
    build_tools_by_ids,
)

# ── 契约常量 ──────────────────────────────────────

# 10 组 49 工具全集（按组，未锁定组内顺序）
# #955 迁移: 35→44（−create_outline/update_outline + 10 新大纲工具 + delete_plot_point）
# #956 迁移: 44→49（+5 读缺口补齐工具）
EXPECTED_ALL_NAMES = {
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
    # outline 10（#955 新）
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
    "delete_character",
    "delete_world_setting",
    "delete_outline",
    "delete_plot_point",  # #955 新增核心删除
    "delete_map",
    "delete_timeline_event",
    "delete_foreshadowing",
    "memory_remove",
    "agent_run",
    "agent_call",
}

# allow_custom_agent=False / is_core=True（系统内置核心，自定义 agent 不可勾选）
# #955 迁移: 9→10（+delete_plot_point）
CORE_NAMES = {
    "agent_run",
    "agent_call",
    "delete_character",
    "delete_world_setting",
    "delete_outline",
    "delete_plot_point",  # #955 新增
    "delete_map",
    "delete_timeline_event",
    "delete_foreshadowing",
    "memory_remove",
}

# 暴露（保持默认 allow_custom_agent=True / is_core=False）的自定义 agent 可勾选工具
EXPOSED_NAMES = {
    "memory_list",
    "memory_add",
    "memory_update",
    "generate",
    "continue",
    "revise",
}


def _spec_by_name(name: str) -> ToolSpec:
    """按 name 查统一目录 spec."""
    for spec in ALL_TOOL_SPECS:
        if spec.name == name:
            return spec
    raise AssertionError(f"未在 ALL_TOOL_SPECS 找到 {name}")


def _make_unified_deps() -> UnifiedToolDeps:
    """构造 UnifiedToolDeps（全 MagicMock；构建工具不需要真实 service）。

    #955 迁移: UnifiedToolDeps 新增必填 `outline` 字段（置于 setting_update 之后、world_rw 之前）。
    """
    return UnifiedToolDeps(
        reader=MagicMock(),
        save_draft=MagicMock(),
        setting_write=MagicMock(),
        setting_update=MagicMock(),
        outline=MagicMock(),  # #955 迁移: +outline 字段
        world_rw=MagicMock(),
        memory=MagicMock(),
        writing=MagicMock(),
        delete=MagicMock(),
        agent_chain=MagicMock(),
    )


# ── 1. 统一目录全集 ──────────────────────────────────


class TestUnifiedCatalog:
    """ALL_TOOL_SPECS 统一目录（#838：全部 10 组 44 工具，无遗漏无重复）。"""

    def test_all_tool_specs_len_is_49(self):
        """统一目录 = 49 工具（10 组全量，#955 35→44 + #956 44→49）。"""
        assert len(ALL_TOOL_SPECS) == 49

    def test_all_tool_specs_contains_new_tools(self):
        """目录含此前未注册的新工具（create_*/update_*/generate 等）。"""
        names = {spec.name for spec in ALL_TOOL_SPECS}
        for name in {"create_character", "create_map", "generate", "memory_add", "agent_run"}:
            assert name in names

    def test_all_tool_specs_names_match_expected(self):
        """目录 name 全集 = 契约全集（无遗漏无重复）。"""
        names = {spec.name for spec in ALL_TOOL_SPECS}
        assert names == EXPECTED_ALL_NAMES

    def test_all_tool_specs_unique_names(self):
        """目录 name 无重复（5 读兜底，防重复注册）。"""
        names = [spec.name for spec in ALL_TOOL_SPECS]
        assert len(names) == len(set(names))


# ── 2. allow_custom_agent=False 不暴露 ──────────────


class TestAllowCustomAgent:
    """allow_custom_agent=False 的工具不入自定义 agent 列表。"""

    def test_core_tools_not_in_custom_agent_registry(self):
        """TOOL_REGISTRY（兼容别名）= allow_custom_agent=True 子集，不含 agent_run/删除类。"""
        registry_names = {spec.name for spec in TOOL_REGISTRY}
        assert CORE_NAMES.isdisjoint(registry_names)
        assert len(TOOL_REGISTRY) == 39  # #955 迁移: 26→34；#956 迁移: 34→39

    def test_core_tools_marked_not_allowed(self):
        """核心工具标记 allow_custom_agent=False / is_core=True。"""
        for name in CORE_NAMES:
            spec = _spec_by_name(name)
            assert spec.allow_custom_agent is False
            assert spec.is_core is True

    def test_registry_names_all_allow_custom(self):
        """TOOL_REGISTRY 内每项 allow_custom_agent=True（兼容别名语义）。"""
        for spec in TOOL_REGISTRY:
            assert spec.allow_custom_agent is True


# ── 3. memory_*/writing 暴露 ────────────────────────


class TestExposedTools:
    """memory_* / writing 暴露（allow_custom_agent=True, is_core=False）。"""

    def test_memory_writing_exposed(self):
        """memory_list/memory_add/memory_update + generate/continue/revise 允许自定义 agent。"""
        for name in EXPOSED_NAMES:
            spec = _spec_by_name(name)
            assert spec.allow_custom_agent is True
            assert spec.is_core is False

    def test_exposed_tools_in_custom_agent_registry(self):
        """暴露工具均出现在自定义 agent 可用目录（TOOL_REGISTRY）。"""
        registry_names = {spec.name for spec in TOOL_REGISTRY}
        assert EXPOSED_NAMES.issubset(registry_names)


# ── 4. _validate_tool_ids 拒绝 allow_custom_agent=False ──


class TestValidateToolIds:
    """_validate_tool_ids 拒绝 allow_custom_agent=False 工具（自定义 agent 不可勾选核心）。"""

    def test_rejects_allow_custom_agent_false_tool(self):
        """核心工具（delete_character / agent_run）→ ToolReferenceError。"""
        with pytest.raises(ToolReferenceError):
            _validate_tool_ids(["delete_character"])
        with pytest.raises(ToolReferenceError):
            _validate_tool_ids(["agent_run"])
        with pytest.raises(ToolReferenceError):
            _validate_tool_ids(["memory_remove"])

    def test_rejects_unknown_tool(self):
        """目录外名 → ToolReferenceError（既有语义保留）。"""
        with pytest.raises(ToolReferenceError):
            _validate_tool_ids(["no_such_tool"])

    def test_accepts_custom_agent_visible_tools(self):
        """允许自定义 agent 的工具（search_characters / memory_add / generate）→ 不抛。"""
        _validate_tool_ids(["search_characters", "memory_add", "generate"])

    def test_accepts_empty(self):
        """空列表 → 不抛。"""
        _validate_tool_ids([])


# ── 5. build_tools_by_ids 运行时物化 ────────────────


class TestBuildToolsByIds:
    """build_tools_by_ids 按 tool_ids 白名单物化工具（调 10 组 build 后按 spec.name 过滤）。"""

    def test_materializes_by_tool_ids(self):
        """只物化 tool_ids 命中的工具（含跨组工具）。"""
        tools = build_tools_by_ids(["search_characters", "create_character"], _make_unified_deps())
        names = {t.spec.name for t in tools}
        assert names == {"search_characters", "create_character"}

    def test_materializes_multiple_groups(self):
        """跨多组工具一次物化（读 + 写 + 记忆）。"""
        tools = build_tools_by_ids(
            ["check_foreshadowing", "save_draft", "generate", "memory_add"],
            _make_unified_deps(),
        )
        names = {t.spec.name for t in tools}
        assert names == {"check_foreshadowing", "save_draft", "generate", "memory_add"}

    def test_ignores_unknown_tool_ids(self):
        """未知名忽略（防御），不影响已命中项。"""
        tools = build_tools_by_ids(["search_characters", "no_such_tool"], _make_unified_deps())
        names = [t.spec.name for t in tools]
        assert names == ["search_characters"]

    def test_empty_tool_ids_returns_empty(self):
        """空 tool_ids → 空列表。"""
        assert build_tools_by_ids([], _make_unified_deps()) == []
