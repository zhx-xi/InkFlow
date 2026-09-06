"""F58 #955 大纲域层级化工具矩阵 — GRANT_TOOL_MAP/registry 映射迁移 + 别名反查不变式契约.

契约来源: contract-955 §3（GRANT_TOOL_MAP 新格/退役别名 LEGACY_RENAMED_TOOL_NAMES/
TOOL_NAME_TO_CELL 44 键）+ §9（delete_plot_point 核心 strict 拒绝 / lenient 反查 outline·delete）。

被测模块（GREEN 新符号 `LEGACY_RENAMED_TOOL_NAMES` 用例体内 import；GRANT_TOOL_MAP/
TOOL_NAME_TO_CELL/expand_grants/grants_from_tool_ids/build_tools_by_grants/
build_tools_by_ids/ALL_TOOL_SPECS/UnifiedToolDeps 既有可导入）:
    from inkflow.infrastructure.agent.tools.registry import (
        GRANT_TOOL_MAP, TOOL_NAME_TO_CELL, LEGACY_RENAMED_TOOL_NAMES,
        expand_grants, grants_from_tool_ids, build_tools_by_grants, build_tools_by_ids,
    )
    from inkflow.infrastructure.agent.tools import ALL_TOOL_SPECS, UnifiedToolDeps
    from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp

GREEN 新符号（LEGACY_RENAMED_TOOL_NAMES）放用例体内 import，防收集期 import 失败炸掉全文件。

契约要点（contract-955 §3 / §9）
-------------------------------
- ALL_TOOL_SPECS 44；TOOL_REGISTRY 34；核心集 10（+delete_plot_point）。
- GRANT_TOOL_MAP 大纲三格（READ→WRITE→DELETE 枚举序，置映射表最前）:
  READ=[list_outlines, get_outline, list_plot_points]；
  WRITE=[create_overall_outline, create_volume_outline, create_chapter_outline,
         update_volume_outline, update_chapter_outline, create_plot_point, update_plot_point]；
  DELETE=[delete_outline, delete_plot_point]。
- LEGACY_RENAMED_TOOL_NAMES = {create_outline, update_outline} → (OUTLINE, WRITE)。
- TOOL_NAME_TO_CELL = 44 键（42 目录名逆 + 2 别名）。
- grants_from_tool_ids: 目录外但 ∈ LEGACY → strict/lenient 均按别名格命中；其余目录外名
  strict 抛 ToolReferenceError。
- build_tools_by_ids 不改（∩ 语义滤掉目录外别名）→ ["create_outline"] → []。
- delete_plot_point 是核心（is_core=True，非别名），strict 拒绝；lenient 反查 outline·delete。

RED 预期形态（当前实现，migrate 后因新契约未实现而 FAILED）
----------------------------------------------------------
- LEGACY_RENAMED_TOOL_NAMES 未定义 → 用例体内 import 抛 ImportError → FAILED。
- UnifiedToolDeps 无 outline 字段 → `_make_unified_deps()` TypeError → FAILED。
- GRANT_TOOL_MAP 现 33 名/大纲 2 格 → 44 键/三格等式 FAILED。
- 预期: 全部用例 FAILED（ImportError/TypeError/AssertionError），无收集 ERROR。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from inkflow.domain.ports.agent_errors import ToolReferenceError
from inkflow.infrastructure.agent.tools import UnifiedToolDeps

# ── 契约常量（contract-955 §3 大纲三格，逐字含序） ──

OUTLINE_READ_NAMES = ["list_outlines", "get_outline", "list_plot_points"]
OUTLINE_WRITE_NAMES = [
    "create_overall_outline",
    "create_volume_outline",
    "create_chapter_outline",
    "update_volume_outline",
    "update_chapter_outline",
    "create_plot_point",
    "update_plot_point",
]
OUTLINE_DELETE_NAMES = ["delete_outline", "delete_plot_point"]


def _make_unified_deps(**overrides) -> UnifiedToolDeps:
    """构造 UnifiedToolDeps（全 MagicMock；构建工具不需要真实 service）——镜像
    test_build_tools_by_grants._make_unified_deps 形态 + 【#955 迁移：UnifiedToolDeps
    新增必填 outline 字段（置于 setting_update 之后、world_rw 之前）】。"""
    defaults = {
        "reader": MagicMock(),
        "save_draft": MagicMock(),
        "setting_write": MagicMock(),
        "setting_update": MagicMock(),
        "outline": MagicMock(),  # #955 迁移: +outline 字段
        "world_rw": MagicMock(),
        "memory": MagicMock(),
        "writing": MagicMock(),
        "delete": MagicMock(),
        "agent_chain": MagicMock(),
    }
    defaults.update(overrides)
    return UnifiedToolDeps(**defaults)


# ── 1. 别名反查（LEGACY） ───────────────────────────


class TestLegacyAliasReverse:
    """退役别名 create_outline/update_outline → outline·[write]，strict/lenient 均命中。"""

    def test_create_outline_alias_lenient_maps_outline_write(self):  # 【R】
        """create_outline（别名）-> outline·[write]；strict=False（存量读取路径）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        assert grants_from_tool_ids(["create_outline"], strict=False) == [
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE])
        ]

    def test_create_outline_alias_strict_maps_outline_write(self):  # 【R】
        """create_outline（别名）strict=True 不 reject（目录外但 ∈ LEGACY 按别名格命中）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        assert grants_from_tool_ids(["create_outline"], strict=True) == [
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE])
        ]

    def test_update_outline_alias_maps_outline_write(self):  # 【R】
        """update_outline（别名）-> outline·[write]；strict=True 同结果。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        assert grants_from_tool_ids(["update_outline"], strict=True) == [
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE])
        ]

    def test_unknown_still_rejected_in_strict(self):  # 【R】
        """目录外且非 LEGACY 的名 strict 仍抛 ToolReferenceError（防别名分支过宽）。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        with pytest.raises(ToolReferenceError):
            grants_from_tool_ids(["no_such_tool"], strict=True)
        with pytest.raises(ToolReferenceError):
            grants_from_tool_ids(["no_such_alias"], strict=True)


# ── 2. TOOL_NAME_TO_CELL 49 键（#956 迁移: 44→49 = 47 目录名逆 + 2 别名） ──


class TestNameToCell44Keys:
    """TOOL_NAME_TO_CELL 49 键 = 47 目录名 + 2 别名；union == 47 名（#956 基线）."""

    def test_name_to_cell_has_44_keys(self):  # 【R】
        """逆索引 49 键（= 47 目录名 + 2 别名，#956 +5 读工具迁移）。"""
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert len(TOOL_NAME_TO_CELL) == 49

    def test_alias_cells_exact(self):  # 【R】
        """逐别名格值断言：create_outline/update_outline -> (OUTLINE, WRITE)。"""
        from inkflow.domain.models.agent_grants import ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert TOOL_NAME_TO_CELL["create_outline"] == (ToolDomain.OUTLINE, ToolOp.WRITE)
        assert TOOL_NAME_TO_CELL["update_outline"] == (ToolDomain.OUTLINE, ToolOp.WRITE)

    def test_union_is_42_catalog_minus_agent_chain(self):  # 【R】
        """union(GRANT_TOOL_MAP) == {ALL_TOOL_SPECS} − {agent_run, agent_call} = 47 名。"""
        from inkflow.infrastructure.agent.tools import ALL_TOOL_SPECS
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        mapped = {name for cell in GRANT_TOOL_MAP.values() for name in cell}
        expected = {s.name for s in ALL_TOOL_SPECS} - {"agent_run", "agent_call"}
        assert mapped == expected
        assert len(mapped) == 47


# ── 3. GRANT_TOOL_MAP 大纲三格 / expand ─────────────


class TestOutlineGrantCells:
    """GRANT_TOOL_MAP 大纲三格逐字 + expand 展开序（contract-955 §3）。"""

    def test_outline_three_cells_exact_order(self):  # 【R】
        """大纲三格逐字 == 契约 §3 列表（含序），置于映射表最前（READ→WRITE→DELETE）。"""
        from inkflow.domain.models.agent_grants import ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        assert GRANT_TOOL_MAP[(ToolDomain.OUTLINE, ToolOp.READ)] == OUTLINE_READ_NAMES
        assert GRANT_TOOL_MAP[(ToolDomain.OUTLINE, ToolOp.WRITE)] == OUTLINE_WRITE_NAMES
        assert GRANT_TOOL_MAP[(ToolDomain.OUTLINE, ToolOp.DELETE)] == OUTLINE_DELETE_NAMES
        assert list(GRANT_TOOL_MAP)[:3] == [
            (ToolDomain.OUTLINE, ToolOp.READ),
            (ToolDomain.OUTLINE, ToolOp.WRITE),
            (ToolDomain.OUTLINE, ToolOp.DELETE),
        ]

    def test_expand_outline_write_seven_names_contract_order(self):  # 【R】
        """expand_grants(outline·write) == 7 名（契约 §3 序）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import expand_grants

        grants = [GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE])]
        assert expand_grants(grants) == OUTLINE_WRITE_NAMES

    def test_expand_outline_read_three_names(self):  # 【R】
        """expand_grants(outline·read) == [list_outlines, get_outline, list_plot_points]。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import expand_grants

        grants = [GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.READ])]
        assert expand_grants(grants) == OUTLINE_READ_NAMES

    def test_delete_cell_has_two(self):  # 【R】
        """outline·delete 格 == [delete_outline, delete_plot_point]。"""
        from inkflow.domain.models.agent_grants import ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        assert GRANT_TOOL_MAP[(ToolDomain.OUTLINE, ToolOp.DELETE)] == [
            "delete_outline",
            "delete_plot_point",
        ]


# ── 4. build_tools_by_grants(outline·write) → 7 工具 ──


class TestBuildToolsByGrantsOutlineWrite:
    """build_tools_by_grants 物化 outline·write（镜像 test_build_tools_by_grants 现有形态）。"""

    def test_build_outline_write_materializes_seven_tools(self):  # 【R】
        """build_tools_by_grants([outline·write], deps with outline=MagicMock()) 物化 7 工具。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants

        grants = [GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE])]
        tools = build_tools_by_grants(grants, _make_unified_deps())
        names = [t.spec.name for t in tools]
        assert names == OUTLINE_WRITE_NAMES


# ── 5. build_tools_by_ids 滤别名（∩ 语义） ──────────


class TestBuildToolsByIdsFiltersAlias:
    """旧 build_tools_by_ids 不改（∩ 语义自然滤掉目录外别名）。"""

    def test_build_tools_by_ids_filters_alias(self):  # 【R】
        """build_tools_by_ids(["create_outline"], deps) == []（旧名不在目录、展开集无别名）。"""
        from inkflow.infrastructure.agent.tools import build_tools_by_ids

        tools = build_tools_by_ids(["create_outline"], _make_unified_deps())
        assert tools == []


# ── 6. delete_plot_point 核心标记 / strict 拒绝 ─────


class TestDeletePlotPointCore:
    """delete_plot_point 核心（非别名），strict 拒绝、lenient 反查 outline·delete（§9）。"""

    def test_core_marked_and_not_in_legacy(self):  # 【R】
        """delete_plot_point 是核心（allow_custom_agent=False, is_core=True），非退役别名。"""
        from inkflow.infrastructure.agent.tools import ALL_TOOL_SPECS
        from inkflow.infrastructure.agent.tools.registry import LEGACY_RENAMED_TOOL_NAMES

        spec = next(s for s in ALL_TOOL_SPECS if s.name == "delete_plot_point")
        assert spec.allow_custom_agent is False
        assert spec.is_core is True
        assert "delete_plot_point" not in LEGACY_RENAMED_TOOL_NAMES  # 核心非别名

    def test_delete_plot_point_maps_to_outline_delete(self):  # 【R】
        """TOOL_NAME_TO_CELL["delete_plot_point"] == (OUTLINE, DELETE)（非别名）。"""
        from inkflow.domain.models.agent_grants import ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert TOOL_NAME_TO_CELL["delete_plot_point"] == (ToolDomain.OUTLINE, ToolOp.DELETE)

    def test_strict_rejects_core_delete_plot_point(self):  # 【R】
        """【R】delete_plot_point strict=True 抛 ToolReferenceError（§9 核心 strict 拒绝）。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        with pytest.raises(ToolReferenceError):
            grants_from_tool_ids(["delete_plot_point"], strict=True)

    def test_lenient_reverses_outline_delete(self):  # 【R】
        """strict=False 反查命中 outline·delete（§9 核心 lenient 反查）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        assert grants_from_tool_ids(["delete_plot_point"], strict=False) == [
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.DELETE])
        ]
