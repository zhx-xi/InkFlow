"""F58 grants 授权数据面 — grants_from_tool_ids 反查 / resolve_grants
统一读取单元契约（contract-954 §2.3/§2.4 / contract-955 §3 迁移 / §7 语义）。

#955 迁移（RED-B）: create_outline 反查格不变（别名）；expand 结果含新写工具
（create_overall_outline 等 7 名），旧名 create_outline/update_outline 不在展开结果
（展开自映射表值）。

被测模块（GREEN 全在 `inkflow.infrastructure.agent.tools.registry`，本批新建）:
    from inkflow.infrastructure.agent.tools.registry import (
        grants_from_tool_ids, resolve_grants, expand_grants,
    )
    from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp

既有可导入（顶部）: ToolReferenceError（domain/ports/agent_errors.py 已有）。

GREEN 新符号（grants_from_tool_ids/resolve_grants/expand_grants/GrantEntry/ToolDomain/ToolOp）
一律放用例体内 import —— 全部【R】用例依赖它们；体导入防单个 import 失败炸掉文件收集。

契约内容（contract-954 §2.3/§2.4 + §9 RED-1）
----------------------------------------
1. grants_from_tool_ids(tool_ids, *, strict):
   - 逐名查 TOOL_NAME_TO_CELL；命中格按首次出现序收集；**按域分组**合并 ops，
     ops 按 ToolOp 枚举序（read<write<delete）。
   - strict=True（API 写路径）: 目录外名或核心名（agent_run/agent_call 或
     allow_custom_agent=False，如 delete_* / memory_remove）→ ToolReferenceError。
   - strict=False（存量读取路径）: 未识别名 → 忽略 + logging.warning(含未识别名, 不阻塞)。
   - 代表性反查: count_words→writing·[read]；create_outline（别名）→outline·[write]
     且 resolve 后展开含 create_overall_outline 等新写工具（旧名 create_outline 不在
     展开结果——展开自映射表值，见 #955 迁移）;
     search_characters+create_character→character·[read,write] 同域合并。
2. resolve_grants(agent)（鸭子 getattr，镜像 deps_chat_agent 形态）:
   - agent.grants 非空 → 原样返回；
   - 否则 tool_ids 非空 → grants_from_tool_ids(tool_ids, strict=False)；
   - 都空 / 无 grants 属性 → []。接受 Agent | SimpleNamespace | MagicMock 等鸭子。
3. §7 语义: 同 (domain,op) 扩权语义只存在于新路径（grants/build_tools_by_grants/resolve）。

RED 预期形态（当前实现）
------------------------
- grants_from_tool_ids/resolve_grants 未定义 → 用例体内 import 抛 ImportError → FAILED。
- ToolReferenceError（既有）可导入，本文件可收集。
- 预期: 全部用例 FAILED（ImportError/AttributeError），无收集 ERROR。

全部用例【R】: GREEN 落地前必红。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from inkflow.domain.ports.agent_errors import ToolReferenceError


def _grant(domain_value, ops_values):
    """构造 GrantEntry 的便捷封装（GREEN 符号体导入，防文件收集炸掉）。"""
    from inkflow.domain.models.agent_grants import GrantEntry

    return GrantEntry(domain=domain_value, ops=ops_values)


# ── TestGrantsFromToolIdsStrict ─────────────────────


class TestGrantsFromToolIdsStrict:
    """strict=True 拒绝非法名（contract-954 §2.3: 目录外/核心名 → ToolReferenceError）。"""

    def test_rejects_unknown_name(self):  # 【R】
        """目录外名（no_such_tool）→ ToolReferenceError。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        with pytest.raises(ToolReferenceError):
            grants_from_tool_ids(["no_such_tool"], strict=True)

    def test_rejects_core_delete_tool(self):  # 【R】
        """核心删除名 delete_character（allow_custom_agent=False）→ strict 拒绝。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        with pytest.raises(ToolReferenceError):
            grants_from_tool_ids(["delete_character"], strict=True)

    def test_rejects_agent_run(self):  # 【R】
        """核心链工具 agent_run → strict 拒绝。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        with pytest.raises(ToolReferenceError):
            grants_from_tool_ids(["agent_run"], strict=True)

    def test_strict_accepts_valid_exposed_tools(self):  # 【R】
        """允许的暴露工具（count_words / create_character）→ 不抛并返回合并 grants。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        grants = grants_from_tool_ids(["count_words"], strict=True)
        assert grants == [GrantEntry(domain=ToolDomain.WRITING, ops=[ToolOp.READ])]


# ── TestGrantsFromToolIdsLenient ────────────────────


class TestGrantsFromToolIdsLenient:
    """strict=False 忽略未识别名（contract-954 §2.3: 忽略 + logging.warning 诊断）。"""

    def test_ignores_unknown_and_logs_warning(self, caplog):  # 【R】
        """未识别名忽略 + 发出含未识别名的 WARNING 诊断（spec §5.2 不阻塞）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        with caplog.at_level(logging.WARNING):
            grants = grants_from_tool_ids(["count_words", "no_such_tool"], strict=False)

        assert grants == [GrantEntry(domain=ToolDomain.WRITING, ops=[ToolOp.READ])]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "strict=False 遇到未识别名应发出 WARNING 诊断"
        assert any("no_such_tool" in r.getMessage() for r in warnings)

    def test_lenient_strict_equal_on_valid_input(self):  # 【R】
        """合法输入下 strict 与 lenient 结果一致（无未识别名时行为无 diff）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        strict = grants_from_tool_ids(["count_words"], strict=True)
        lenient = grants_from_tool_ids(["count_words"], strict=False)
        assert strict == lenient == [GrantEntry(domain=ToolDomain.WRITING, ops=[ToolOp.READ])]


# ── TestGrantsFromToolIdsReverse ────────────────────


class TestGrantsFromToolIdsReverse:
    """代表性反查用例（contract-954 §2.3 样例 + spec §5.2 扩权映射）。"""

    def test_count_words_maps_to_writing_read(self):  # 【R】
        """count_words -> writing·[read]。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        assert grants_from_tool_ids(["count_words"], strict=False) == [
            _grant(domain_value="writing", ops_values=["read"])
        ]

    def test_create_outline_maps_to_outline_write_and_expands(self):  # 【R】
        """create_outline（别名）-> outline·[write]；展开自映射表值，旧名不在展开结果。"""
        from inkflow.infrastructure.agent.tools.registry import expand_grants, grants_from_tool_ids

        grants = grants_from_tool_ids(["create_outline"], strict=False)
        assert grants == [_grant(domain_value="outline", ops_values=["write"])]
        expanded = expand_grants(grants)
        # #955 迁移: 展开自映射表值（不含旧名 create_outline/update_outline），含 7 新写工具
        assert "create_overall_outline" in expanded
        assert "update_chapter_outline" in expanded
        assert "create_outline" not in expanded  # 旧名不在展开结果——展开自映射表值

    def test_search_and_create_character_merge_same_domain(self):  # 【R】
        """search_characters + create_character -> character·[read, write]
        （同域合并，ops 按枚举序）。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        grants = grants_from_tool_ids(["search_characters", "create_character"], strict=False)
        assert grants == [_grant(domain_value="character", ops_values=["read", "write"])]

    def test_multiple_domains_first_appearance_order(self):  # 【R】
        """跨域工具按首次出现序生成多 GrantEntry（ops 各域独立按枚举序）。"""
        from inkflow.infrastructure.agent.tools.registry import grants_from_tool_ids

        grants = grants_from_tool_ids(["create_character", "count_words"], strict=False)
        assert grants == [
            _grant(domain_value="character", ops_values=["write"]),
            _grant(domain_value="writing", ops_values=["read"]),
        ]


# ── TestResolveGrants ───────────────────────────────


class TestResolveGrants:
    """resolve_grants 三分支（contract-954 §2.4: grants 优先 / tool_ids 回退 / 双空 []）。"""

    def test_grants_non_empty_priority(self):  # 【R】
        """agent.grants 非空 → 原样返回（不读 tool_ids）。"""
        from inkflow.infrastructure.agent.tools.registry import resolve_grants

        agent = SimpleNamespace(
            grants=[_grant(domain_value="outline", ops_values=["write"])],
            tool_ids=["count_words"],
        )
        assert resolve_grants(agent) == [_grant(domain_value="outline", ops_values=["write"])]

    def test_empty_grants_fall_back_to_tool_ids(self):  # 【R】
        """grants 空 + tool_ids 非空 → grants_from_tool_ids(tool_ids, strict=False)。"""
        from inkflow.infrastructure.agent.tools.registry import resolve_grants

        agent = SimpleNamespace(grants=[], tool_ids=["count_words"])
        assert resolve_grants(agent) == [_grant(domain_value="writing", ops_values=["read"])]

    def test_both_empty_returns_empty(self):  # 【R】
        """grants 空且 tool_ids 空 → []。"""
        from inkflow.infrastructure.agent.tools.registry import resolve_grants

        agent = SimpleNamespace(grants=[], tool_ids=[])
        assert resolve_grants(agent) == []

    def test_resolve_accepts_duck_object_without_grants_attr(self):  # 【R】
        """鸭子对象无 grants 属性（getattr 缺省 []）→ 走 tool_ids 回退或 []。"""
        from inkflow.infrastructure.agent.tools.registry import resolve_grants

        duck = SimpleNamespace(tool_ids=["count_words"])
        assert resolve_grants(duck) == [_grant(domain_value="writing", ops_values=["read"])]
        empty_duck = SimpleNamespace(tool_ids=[])
        assert resolve_grants(empty_duck) == []
