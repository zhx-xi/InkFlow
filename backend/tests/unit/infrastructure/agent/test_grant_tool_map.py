"""F58 grants 授权数据面 — GRANT_TOOL_MAP / 逆索引 / expand_grants 单元契约
（contract-954 §2.1/§2.2 / contract-955 §3 迁移 / §1 语义）.

#955 迁移（RED-B）: union(GRANT_TOOL_MAP)==42（−create_outline/update_outline + 10 新大纲
工具 + delete_plot_point，44 全集−{agent_run,agent_call}=42）；TOOL_NAME_TO_CELL 44 键
（42 目录名逆 + 2 别名 create_outline/update_outline）；outline 格三格（READ/WRITE/DELETE）
置于映射表最前，outline·write 展开序=§3 七名。

被测模块（GREEN 全在 `inkflow.infrastructure.agent.tools.registry`，本批新建）:
    from inkflow.infrastructure.agent.tools.registry import (
        GRANT_TOOL_MAP, TOOL_NAME_TO_CELL, expand_grants,
    )
    from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp

既有可导入（顶部）: ALL_TOOL_SPECS（registry.py:100-132 已有 44 工具名录）。

GREEN 新符号（GRANT_TOOL_MAP/TOOL_NAME_TO_CELL/expand_grants/GrantEntry/ToolDomain/ToolOp）
一律放用例体内 import —— 本文件【R】用例依赖它们，但为防单个 import 失败炸掉全文件收集、
拖累任何潜在守护用例，全部体导入。

契约内容（contract-954 §2.1/§2.2 + contract-955 §3 + §9 RED-1）
-------------------------------------------------------
1. GRANT_TOOL_MAP: dict[tuple[ToolDomain, ToolOp], list[str]]。插入序 = 展开序。
   - 空格子键不入表；(writing,delete) 本批缺席；agent_chain 域无条目。
   - agent_run/agent_call 不进映射；8 个核心删除工具进 delete 格（spec §2.5）,
     其中 delete_plot_point 属 (outline, delete) 格（#955 新）。
2. 完整性不变式:
   - union(values) == {ALL_TOOL_SPECS name} − {agent_run, agent_call}（= 42 名）。
   - 34 非核心（allow_custom_agent=True）名全部在映射恰一次；8 删除核心名也各恰一次。
   - 每格内无重复名；跨格无重复（同一工具恰属一格）。
   - 所有键 ∈ ToolDomain × ToolOp。
3. TOOL_NAME_TO_CELL: dict[str, tuple[ToolDomain, ToolOp]] = {**逐格反转
   GRANT_TOOL_MAP, **LEGACY_RENAMED_TOOL_NAMES}，与 GRANT_TOOL_MAP 逐名一致
   （恰 44 键 = 42 目录名 + 2 别名）。
4. expand_grants(grants): GRANT_TOOL_MAP 展开 → 按映射插入序拼接、去重保序；
   空 ops GrantEntry 不贡献任何工具名。

RED 预期形态（当前实现）
------------------------
- GRANT_TOOL_MAP/TOOL_NAME_TO_CELL/expand_grants 未定义 → 用例体内 import 抛
  ImportError → 用例 FAILED；ALL_TOOL_SPECS（既有）可正常导入，本文件可收集。
- #955 迁移后: 映射现 33 名 → ==42 FAILED；逆索引现 33 → ==44 FAILED；
  outline·write 现展开 [create_outline, update_outline] → ==七名 FAILED。
- 预期: 全部用例 FAILED（ImportError/AssertionError），无收集 ERROR。

全部用例【R】: GREEN 落地前必红。
"""

from __future__ import annotations

from collections import Counter

from inkflow.infrastructure.agent.tools import ALL_TOOL_SPECS

# 49 全集 − {agent_run, agent_call} = 47 名（8 删除核心 + 39 非核心）
# #955 迁移: 33→42；#956 迁移: 42→47（+get_character/list/get_foreshadowing/list/get_world_setting）
EXPECTED_MAPPED_NAMES = {
    "list_outlines", "get_outline", "list_plot_points",
    "create_overall_outline", "create_volume_outline", "create_chapter_outline",
    "update_volume_outline", "update_chapter_outline", "create_plot_point",
    "update_plot_point",
    "delete_outline", "delete_plot_point",
    "search_characters", "get_character", "create_character", "update_character",
    "delete_character",
    "list_maps", "list_world_settings", "get_world_setting", "create_world_setting",
    "update_world_setting", "create_map", "update_map", "delete_world_setting", "delete_map",
    "list_timeline_events", "create_timeline_event", "update_timeline_event",
    "delete_timeline_event",
    "check_foreshadowing", "list_foreshadowing", "get_foreshadowing",
    "create_foreshadowing", "update_foreshadowing",
    "delete_foreshadowing",
    "memory_list", "memory_add", "memory_update", "memory_remove",
    "get_prior_summary", "audit_chapter", "count_words", "save_draft",
    "generate", "continue", "revise",
}

# 39 非核心（allow_custom_agent=True）名，供「恰一次」断言（含在 ALL_TOOL_SPECS 中）


def _all_spec_names() -> set[str]:
    """从既有 ALL_TOOL_SPECS 派生 49 工具名（GREEN 后仍稳定）。"""
    return {s.name for s in ALL_TOOL_SPECS}


def _mapped_names(map_impl) -> list[str]:
    """展平 GRANT_TOOL_MAP 全部格值为工具名列表。"""
    return [name for cell in map_impl.values() for name in cell]


def _non_core_names() -> set[str]:
    """39 非核心（allow_custom_agent=True）工具名集合。"""
    return {s.name for s in ALL_TOOL_SPECS if s.allow_custom_agent}


# ── TestGrantToolMapInvariants ──────────────────────


class TestGrantToolMapInvariants:
    """GRANT_TOOL_MAP 完整性三式（contract-954 §2.1 RED 锁死）。"""

    def test_union_equals_catalog_minus_agent_chain(self):  # 【R】
        """union(values) == ALL_TOOL_SPECS 49 名 − {agent_run, agent_call} = 47 名。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        mapped = set(_mapped_names(GRANT_TOOL_MAP))
        assert mapped == _all_spec_names() - {"agent_run", "agent_call"}
        assert len(mapped) == 47

    def test_union_count_is_47_distinct(self):  # 【R】
        """展开扁平化后恰 47 项且无重复（每工具恰属一格，#956 42→47）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        names = _mapped_names(GRANT_TOOL_MAP)
        assert len(names) == 47
        assert len(names) == len(set(names))

    def test_all_non_core_names_mapped_exactly_once(self):  # 【R】
        """39 非核心名全部出现在映射且恰一次（#956 34→39）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        counter = Counter(_mapped_names(GRANT_TOOL_MAP))
        non_core = _non_core_names()
        assert len(non_core) == 39
        for name in non_core:
            assert counter[name] == 1

    def test_delete_core_tools_mapped(self):  # 【R】
        """8 个核心删除工具进 delete 格（spec §2.5: delete op 授权控挂载）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        mapped = set(_mapped_names(GRANT_TOOL_MAP))
        delete_tools = {
            "delete_character", "delete_world_setting", "delete_outline",
            "delete_plot_point",  # #955 新增
            "delete_map", "delete_timeline_event", "delete_foreshadowing",
            "memory_remove",
        }
        assert delete_tools <= mapped

    def test_no_duplicate_within_cell(self):  # 【R】
        """每格内无重复工具名。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        for cell in GRANT_TOOL_MAP.values():
            assert len(cell) == len(set(cell))

    def test_no_empty_cells(self):  # 【R】
        """空格子键不入表（每格至少一工具）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        for cell in GRANT_TOOL_MAP.values():
            assert len(cell) >= 1

    def test_keys_are_domain_op_pairs(self):  # 【R】
        """所有键 ∈ ToolDomain × ToolOp（二元组，域与操作均属枚举）。"""
        from inkflow.domain.models.agent_grants import ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        for key in GRANT_TOOL_MAP:
            assert isinstance(key, tuple)
            assert len(key) == 2
            assert isinstance(key[0], ToolDomain)
            assert isinstance(key[1], ToolOp)

    def test_excludes_agent_run_and_call(self):  # 【R】
        """核心链工具 agent_run/agent_call 不进映射。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        mapped = set(_mapped_names(GRANT_TOOL_MAP))
        assert "agent_run" not in mapped
        assert "agent_call" not in mapped


# ── TestToolNameToCell ──────────────────────────────


class TestToolNameToCell:
    """TOOL_NAME_TO_CELL 逆索引与 GRANT_TOOL_MAP 一致（contract-954 §2.2 + §3 别名）。"""

    def test_inverse_consistent_with_map(self):  # 【R】
        """逐名逆索引与映射键完全一致（双向）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP, TOOL_NAME_TO_CELL

        for (domain, op), names in GRANT_TOOL_MAP.items():
            for name in names:
                assert TOOL_NAME_TO_CELL[name] == (domain, op)

    def test_inverse_has_49_entries(self):  # 【R】
        """逆索引恰 49 键（= 47 目录名 + 2 别名，#956 迁移 44→49）。"""
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert len(TOOL_NAME_TO_CELL) == 49

    def test_inverse_no_agent_run_call(self):  # 【R】
        """逆索引不含核心链工具。"""
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert "agent_run" not in TOOL_NAME_TO_CELL
        assert "agent_call" not in TOOL_NAME_TO_CELL

    def test_inverse_maps_write_domain_cells(self):  # 【R】
        """代表性反查: create_overall_outline 与新名同落 outline·write；角色读同理。"""
        from inkflow.domain.models.agent_grants import ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        # #955 迁移: 代表反查改 `create_overall_outline→(outline,write)`
        # + 保留 `create_outline→(outline,write)`（别名）
        assert TOOL_NAME_TO_CELL["create_overall_outline"] == (ToolDomain.OUTLINE, ToolOp.WRITE)
        assert TOOL_NAME_TO_CELL["create_outline"] == (
            ToolDomain.OUTLINE,
            ToolOp.WRITE,
        )  # #955 别名
        assert TOOL_NAME_TO_CELL["search_characters"] == (ToolDomain.CHARACTER, ToolOp.READ)


# ── TestExpandGrants ────────────────────────────────


class TestExpandGrants:
    """expand_grants 展开语义（contract-954 §2.2: 保序 / 去重 / 空格子容忍）。"""

    def test_expand_preserves_order_and_dedups(self):  # 【R】
        """按映射插入序拼接、去重保序（重复授予同格不重复）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import expand_grants

        grants = [
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE]),
            GrantEntry(domain=ToolDomain.WRITING, ops=[ToolOp.READ]),
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE]),  # 重复格 -> 去重
        ]
        # #955 迁移: outline·write 展开序 == §3 七名
        assert expand_grants(grants) == [
            "create_overall_outline", "create_volume_outline", "create_chapter_outline",
            "update_volume_outline", "update_chapter_outline", "create_plot_point",
            "update_plot_point",
            "get_prior_summary", "audit_chapter", "count_words",
        ]

    def test_expand_empty_ops_contributes_nothing(self):  # 【R】
        """空 ops GrantEntry 不贡献任何工具名（空格子容忍）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import expand_grants

        grants = [
            GrantEntry(domain=ToolDomain.MEMORY, ops=[]),  # 空 -> 不贡献 memory_list 等
            GrantEntry(domain=ToolDomain.WRITING, ops=[ToolOp.READ]),
        ]
        assert expand_grants(grants) == [
            "get_prior_summary", "audit_chapter", "count_words",
        ]

    def test_expand_empty_grants_empty(self):  # 【R】
        """空 grants -> 空清单。"""
        from inkflow.infrastructure.agent.tools.registry import expand_grants

        assert expand_grants([]) == []
