"""F58 grants 授权数据面 — build_tools_by_grants 物化矩阵单元契约（contract-954 §2.5 / §7 语义）.

#955 迁移（RED-B）: UnifiedToolDeps 新增必填 `outline` 字段（`_make_unified_deps` 镜像
test_agent_tool_registry._make_unified_deps +outline=MagicMock()）；补 outline·read/write
物化用例（§3 三格中最先两格）。

被测模块（GREEN 全在 `inkflow.infrastructure.agent.tools.registry`，本批新建）:
    from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants
    from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp

既有可导入（顶部）: UnifiedToolDeps / build_tools_by_ids / ALL_TOOL_SPECS
（tools/__init__.py 及 registry.py 已有；本文件含【G】回归守护）。

GREEN 新符号（build_tools_by_grants/GrantEntry/ToolDomain/ToolOp）放用例体内 import，
与【G】守护用例隔离，防 collect 阶段炸掉守护测试。

契约内容（contract-954 §2.5 + §7 + contract-955 §3 + spec §2.2/§3.3）
---------------------------------------------------------------
1. build_tools_by_grants(grants, deps: UnifiedToolDeps, project_id=None):
   expand_grants(grants) → 10 组 build（None 子 deps 跳过该组，同旧）→ 按名过滤拼接；
   未知名防御忽略。grants 为空 → [].
2. 物化矩阵: 授予 (writing, read) → 恰 {get_prior_summary, audit_chapter, count_words}；
   只授予 character·read → search_characters 在列且 create_character 不在列（scope 未授予）；
   某子 deps=None → 该组工具跳过（delete deps None + 授予 outline·delete → []）。
   #955: outline·read → 恰 {list_outlines, get_outline, list_plot_points}；
         outline·write → 恰 7 名（§3 契约序）。
3. 旧 build_tools_by_ids 行为回归【G】: ["generate","revise"] → 精确 2 个不扩权；
   未知名忽略。契约 §7 同 (domain,op) 扩权只存在于新路径，旧路径精确白名单语义逐字不变。
4. §7 语义: delete 列授权只控暴露；None 子 deps 自然跳过（double gate 之一）。

RED 预期形态（当前实现）
------------------------
- build_tools_by_grants 未定义 → 用例体内 import 抛 ImportError → FAILED。
- #955 迁移后: `_make_unified_deps` 传 outline= → UnifiedToolDeps 无该字段 → TypeError FAILED
  （连【G】回归用例亦红——fixture 改动连带，UnifiedToolDeps 新增必填 outline 字段属契约）。
- 预期: 【R】与【G】用例均因 fixture/契约未落地而 FAILED；无收集 ERROR。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from inkflow.infrastructure.agent.tools import UnifiedToolDeps, build_tools_by_ids


def _make_unified_deps(**overrides) -> UnifiedToolDeps:
    """构造 UnifiedToolDeps（全 MagicMock；构建工具不需要真实 service）——镜像
    test_agent_tool_registry._make_unified_deps 形态；overrides 用于置 None 跳过组。
    #955 迁移: UnifiedToolDeps 新增必填 `outline` 字段（置于 setting_update 之后、world_rw 之前）。
    """
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


# ── TestBuildToolsByGrants ──────────────────────────


class TestBuildToolsByGrants:
    """build_tools_by_grants 物化矩阵（contract-954 §2.5）。"""

    def test_materializes_writing_read(self):  # 【R】
        """授予 (writing, read) → 恰 {get_prior_summary, audit_chapter, count_words}。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants

        grants = [GrantEntry(domain=ToolDomain.WRITING, ops=[ToolOp.READ])]
        tools = build_tools_by_grants(grants, _make_unified_deps())
        names = {t.spec.name for t in tools}
        assert names == {"get_prior_summary", "audit_chapter", "count_words"}

    def test_character_read_only_excludes_un_granted(self):  # 【R】
        """只授予 character·read → search_characters 在列，
        create_character 不在列（scope 未授予）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants

        grants = [GrantEntry(domain=ToolDomain.CHARACTER, ops=[ToolOp.READ])]
        tools = build_tools_by_grants(grants, _make_unified_deps())
        names = {t.spec.name for t in tools}
        assert "search_characters" in names
        assert "create_character" not in names

    def test_outline_read_materializes_three_tools(self):  # 【R】
        """#955: 授予 outline·read → 恰三读工具 {list_outlines, get_outline, list_plot_points}。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants

        grants = [GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.READ])]
        tools = build_tools_by_grants(grants, _make_unified_deps())
        names = [t.spec.name for t in tools]
        assert names == ["list_outlines", "get_outline", "list_plot_points"]

    def test_outline_write_materializes_seven_tools(self):  # 【R】
        """#955: 授予 outline·write → 恰 7 名（§3 契约序，create_overall_outline 起）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants

        grants = [GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE])]
        tools = build_tools_by_grants(grants, _make_unified_deps())
        names = [t.spec.name for t in tools]
        assert names == [
            "create_overall_outline", "create_volume_outline", "create_chapter_outline",
            "update_volume_outline", "update_chapter_outline", "create_plot_point",
            "update_plot_point",
        ]

    def test_empty_grants_returns_empty(self):  # 【R】
        """空 grants → []。"""
        from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants

        assert build_tools_by_grants([], _make_unified_deps()) == []

    def test_none_sub_deps_group_skipped(self):  # 【R】
        """某子 deps=None → 该组工具跳过（delete deps None + 授予 outline·delete → []）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import build_tools_by_grants

        grants = [GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.DELETE])]
        deps = _make_unified_deps(delete=None)
        tools = build_tools_by_grants(grants, deps)
        names = {t.spec.name for t in tools}
        assert "delete_outline" not in names
        assert tools == []


# ── TestBuildToolsByIdsRegression ───────────────────


class TestBuildToolsByIdsRegression:
    """旧 build_tools_by_ids 行为回归（contract-954 §2.5 / §7: 精确白名单 ∩ 设计，逐字不变）。"""

    def test_generate_revise_exact_two_no_expansion(self):  # 【G】
        """["generate","revise"] → 精确 2 个，不扩权（扩权只发生在新路径）。"""
        tools = build_tools_by_ids(["generate", "revise"], _make_unified_deps())
        names = [t.spec.name for t in tools]
        assert names == ["generate", "revise"]

    def test_unknown_tool_ids_ignored(self):  # 【G】
        """未知名忽略（防御），不影响已命中项。"""
        tools = build_tools_by_ids(["search_characters", "no_such_tool"], _make_unified_deps())
        names = [t.spec.name for t in tools]
        assert names == ["search_characters"]
