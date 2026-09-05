"""F58 grants 授权数据面 — GRANT_TOOL_MAP / 逆索引 / expand_grants 单元契约
（contract-954 §2.1/§2.2 / §1 语义）.

被测模块（GREEN 全在 `inkflow.infrastructure.agent.tools.registry`，本批新建）:
    from inkflow.infrastructure.agent.tools.registry import (
        GRANT_TOOL_MAP, TOOL_NAME_TO_CELL, expand_grants,
    )
    from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp

既有可导入（顶部）: ALL_TOOL_SPECS（registry.py:100-132 已有 35 工具名录）。

GREEN 新符号（GRANT_TOOL_MAP/TOOL_NAME_TO_CELL/expand_grants/GrantEntry/ToolDomain/ToolOp）
一律放用例体内 import —— 本文件【R】用例依赖它们，但为防单个 import 失败炸掉全文件收集、
拖累任何潜在守护用例，全部体导入。

契约内容（contract-954 §2.1/§2.2 + §9 RED-1）
----------------------------------------
1. GRANT_TOOL_MAP: dict[tuple[ToolDomain, ToolOp], list[str]]。插入序 = 展开序。
   - 空格子键不入表；(outline,read)/(writing,delete) 本批缺席；agent_chain 域无条目。
   - agent_run/agent_call 不进映射；7 个核心删除工具进 delete 格（spec §2.5）。
2. 完整性不变式:
   - union(values) == {ALL_TOOL_SPECS name} − {agent_run, agent_call}（= 33 名）。
   - 26 非核心（allow_custom_agent=True）名全部在映射恰一次；7 删除核心名也各恰一次。
   - 每格内无重复名；跨格无重复（同一工具恰属一格）。
   - 所有键 ∈ ToolDomain × ToolOp。
3. TOOL_NAME_TO_CELL: dict[str, tuple[ToolDomain, ToolOp]] = _invert(GRANT_TOOL_MAP)，
   与 GRANT_TOOL_MAP 逐名一致（恰 33 键）。
4. expand_grants(grants): GRANT_TOOL_MAP 展开 → 按映射插入序拼接、去重保序；
   空 ops GrantEntry 不贡献任何工具名。

RED 预期形态（当前实现）
------------------------
- GRANT_TOOL_MAP/TOOL_NAME_TO_CELL/expand_grants 未定义 → 用例体内 import 抛
  ImportError → 用例 FAILED；ALL_TOOL_SPECS（既有）可正常导入，本文件可收集。
- 预期: 全部用例 FAILED（ImportError/AssertionError），无收集 ERROR。

全部用例【R】: GREEN 落地前必红。
"""

from __future__ import annotations

from collections import Counter

from inkflow.infrastructure.agent.tools import ALL_TOOL_SPECS

# 35 全集 − {agent_run, agent_call} = 33 名（7 删除核心 + 26 非核心）
EXPECTED_MAPPED_NAMES = {
    "search_characters", "check_foreshadowing", "get_prior_summary", "audit_chapter",
    "count_words", "save_draft", "create_character", "create_world_setting",
    "create_outline", "update_character", "update_world_setting", "update_outline",
    "list_maps", "create_map", "update_map", "list_timeline_events",
    "create_timeline_event", "update_timeline_event", "create_foreshadowing",
    "update_foreshadowing", "memory_list", "memory_add", "memory_update", "generate",
    "continue", "revise", "delete_character", "delete_world_setting", "delete_outline",
    "delete_map", "delete_timeline_event", "delete_foreshadowing", "memory_remove",
}

# 26 非核心（allow_custom_agent=True）名，供「恰一次」断言（含在 ALL_TOOL_SPECS 中）


def _all_spec_names() -> set[str]:
    """从既有 ALL_TOOL_SPECS 派生 35 工具名（GREEN 后仍稳定）。"""
    return {s.name for s in ALL_TOOL_SPECS}


def _mapped_names(map_impl) -> list[str]:
    """展平 GRANT_TOOL_MAP 全部格值为工具名列表。"""
    return [name for cell in map_impl.values() for name in cell]


def _non_core_names() -> set[str]:
    """26 非核心（allow_custom_agent=True）工具名集合。"""
    return {s.name for s in ALL_TOOL_SPECS if s.allow_custom_agent}


# ── TestGrantToolMapInvariants ──────────────────────


class TestGrantToolMapInvariants:
    """GRANT_TOOL_MAP 完整性三式（contract-954 §2.1 RED 锁死）。"""

    def test_union_equals_catalog_minus_agent_chain(self):  # 【R】
        """union(values) == ALL_TOOL_SPECS 35 名 − {agent_run, agent_call} = 33 名。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        mapped = set(_mapped_names(GRANT_TOOL_MAP))
        assert mapped == _all_spec_names() - {"agent_run", "agent_call"}
        assert len(mapped) == 33

    def test_union_count_is_33_distinct(self):  # 【R】
        """展开扁平化后恰 33 项且无重复（每工具恰属一格）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        names = _mapped_names(GRANT_TOOL_MAP)
        assert len(names) == 33
        assert len(names) == len(set(names))

    def test_all_non_core_names_mapped_exactly_once(self):  # 【R】
        """26 非核心名全部出现在映射且恰一次。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        counter = Counter(_mapped_names(GRANT_TOOL_MAP))
        non_core = _non_core_names()
        assert len(non_core) == 26
        for name in non_core:
            assert counter[name] == 1

    def test_delete_core_tools_mapped(self):  # 【R】
        """7 个核心删除工具进 delete 格（spec §2.5: delete op 授权控挂载）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP

        mapped = set(_mapped_names(GRANT_TOOL_MAP))
        delete_tools = {
            "delete_character", "delete_world_setting", "delete_outline", "delete_map",
            "delete_timeline_event", "delete_foreshadowing", "memory_remove",
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
    """TOOL_NAME_TO_CELL 逆索引与 GRANT_TOOL_MAP 一致（contract-954 §2.2）。"""

    def test_inverse_consistent_with_map(self):  # 【R】
        """逐名逆索引与映射键完全一致（双向）。"""
        from inkflow.infrastructure.agent.tools.registry import GRANT_TOOL_MAP, TOOL_NAME_TO_CELL

        for (domain, op), names in GRANT_TOOL_MAP.items():
            for name in names:
                assert TOOL_NAME_TO_CELL[name] == (domain, op)

    def test_inverse_has_33_entries(self):  # 【R】
        """逆索引恰 33 键（= 映射工具名总数）。"""
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert len(TOOL_NAME_TO_CELL) == 33

    def test_inverse_no_agent_run_call(self):  # 【R】
        """逆索引不含核心链工具。"""
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert "agent_run" not in TOOL_NAME_TO_CELL
        assert "agent_call" not in TOOL_NAME_TO_CELL

    def test_inverse_maps_write_domain_cells(self):  # 【R】
        """代表性反查: create_outline -> outline·write；search_characters -> character·read。"""
        from inkflow.domain.models.agent_grants import ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import TOOL_NAME_TO_CELL

        assert TOOL_NAME_TO_CELL["create_outline"] == (ToolDomain.OUTLINE, ToolOp.WRITE)
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
        assert expand_grants(grants) == [
            "create_outline", "update_outline",
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
