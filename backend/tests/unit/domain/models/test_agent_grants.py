"""F58 grants 授权数据面 — grants 领域模型单元契约（contract-954 §1 / §9 RED-1 / §7 语义）.

被测模块（GREEN 实现，RED 期全【R】→ 本文件允许顶部 import GREEN 符号，
模块 `inkflow.domain.models.agent_grants` 不存在 → 收集期 ERROR）:
    from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
    from inkflow.domain.models.agent import Agent, AgentCreate, AgentUpdate

契约内容（contract-954 §1 + spec §2.1）
------------------------------------
1. ToolDomain(StrEnum) 8 域值（枚举序）: outline/character/world/timeline/
   foreshadowing/memory/writing/agent_chain。
2. ToolOp(StrEnum) 3 操作值（枚举序）: read/write/delete。
3. GrantEntry(BaseModel): domain: ToolDomain; ops: list[ToolOp] = Field(default_factory=list)。
   非法 domain 字符串 / 非法 op 字符串构造 → pydantic ValidationError。
   ops 未显式传 → []（空列表 = 该域无授权）。
4. Agent 实体（domain/models/agent.py）: grants: list[GrantEntry] = Field(default_factory=list)，
   tool_ids 保留。AgentCreate.grants: list[GrantEntry] | None = None；
   AgentUpdate.grants: list[GrantEntry] | None = None。

RED 预期形态（当前实现）
------------------------
- `inkflow.domain.models.agent_grants` 模块不存在 → 顶部 import 抛 ModuleNotFoundError
  → 本文件收集期 ERROR（0 收集）。
- Agent/AgentCreate/AgentUpdate 尚无 grants 字段 → 用例体内访问 `.grants`
  → AttributeError（RED 期直接断字段，不用 getattr 兜底——契约第四形态）。

全部用例【R】: GREEN 落地（agent_grants.py 新建 + agent.py 补 grants 字段）前必红。
"""

from __future__ import annotations

import pytest
from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
from pydantic import ValidationError

from inkflow.domain.models.agent import Agent, AgentCreate, AgentUpdate

# ── TestToolDomain ──────────────────────────────────


class TestToolDomain:
    """ToolDomain 枚举 8 域值契约（spec §2.1 逐字）。"""

    def test_eight_domain_values_in_order(self):  # 【R】
        """8 域按声明序枚举（顺序：outline/character/world/timeline/
        foreshadowing/memory/writing/agent_chain）."""
        assert [e.value for e in ToolDomain] == [
            "outline",
            "character",
            "world",
            "timeline",
            "foreshadowing",
            "memory",
            "writing",
            "agent_chain",
        ]

    def test_enum_is_str_enum(self):  # 【R】
        """ToolDomain 继承 StrEnum（值时即字符串，API json 序列化得裸字符串）。"""
        for e in ToolDomain:
            assert isinstance(e.value, str)
            assert ToolDomain(e.value) is e


# ── TestToolOp ──────────────────────────────────────


class TestToolOp:
    """ToolOp 枚举 3 操作值契约（spec §2.1）。"""

    def test_three_op_values_in_order(self):  # 【R】
        """3 操作按声明序枚举: read/write/delete."""
        assert [e.value for e in ToolOp] == ["read", "write", "delete"]

    def test_enum_is_str_enum(self):  # 【R】
        """ToolOp 继承 StrEnum（ops 序列化为裸字符串列表）。"""
        for e in ToolOp:
            assert isinstance(e.value, str)
            assert ToolOp(e.value) is e


# ── TestGrantEntry ──────────────────────────────────


class TestGrantEntry:
    """GrantEntry 结构契约（spec §2.1: domain + ops 缺省 []）。"""

    def test_valid_construction(self):  # 【R】
        """合法 domain/ops 构造成功并保留枚举成员。"""
        entry = GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE, ToolOp.DELETE])
        assert entry.domain == ToolDomain.OUTLINE
        assert entry.ops == [ToolOp.WRITE, ToolOp.DELETE]

    def test_invalid_domain_string_raises(self):  # 【R】
        """非法 domain 字符串 → pydantic ValidationError（枚举天然拒绝，
        API 层表现为 422 detail 列表）。"""
        with pytest.raises(ValidationError):
            GrantEntry(domain="bad_domain")

    def test_invalid_op_string_raises(self):  # 【R】
        """非法 op 字符串 → pydantic ValidationError。"""
        with pytest.raises(ValidationError):
            GrantEntry(domain=ToolDomain.OUTLINE, ops=["bad_op"])

    def test_partially_invalid_ops_raises(self):  # 【R】
        """ops 列表中仅一项非法 → ValidationError（整单拒绝，不静默丢弃）。"""
        with pytest.raises(ValidationError):
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.READ, "bad_op"])

    def test_ops_defaults_to_empty_list(self):  # 【R】
        """ops 缺省 = []（空列表 = 该域无授权，非 None）。"""
        entry = GrantEntry(domain=ToolDomain.OUTLINE)
        assert entry.ops == []
        assert entry.ops is not None


# ── TestAgentEntityGrants ───────────────────────────


class TestAgentEntityGrants:
    """Agent 实体/请求 DTO grants 字段契约（contract-954 §1: 实体默认 [] / DTO 默认 None）。"""

    def test_agent_entity_grants_default_empty(self):  # 【R】
        """Agent 实体 grants 默认 []（Field(default_factory=list)）。"""
        agent = Agent(name="架构师")
        assert agent.grants == []

    def test_agent_entity_grants_accepts_grant_entries(self):  # 【R】
        """Agent 实体 grants 可容纳 GrantEntry 列表（模型层结构契约）。"""
        agent = Agent(
            name="架构师",
            grants=[GrantEntry(domain=ToolDomain.CHARACTER, ops=[ToolOp.READ])],
        )
        assert len(agent.grants) == 1
        assert agent.grants[0].domain == ToolDomain.CHARACTER

    def test_agent_create_grants_default_none(self):  # 【R】
        """AgentCreate.grants 字段存在且默认 None（RED 期访问 →
        AttributeError，勿 getattr 兜底）。"""
        create = AgentCreate(name="写手")
        assert create.grants is None

    def test_agent_update_grants_default_none(self):  # 【R】
        """AgentUpdate.grants 字段存在且默认 None（全可选 DTO）。"""
        update = AgentUpdate()
        assert update.grants is None
