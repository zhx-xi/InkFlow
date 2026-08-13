"""ProjectConfig.agent_order 存储层校验契约（F42 #269，spec §2.1 + §13 M4）。

被测：domain/models/project.py ProjectConfig.agent_order（list[list[str]]）+
@field_validator（存储层：结构 + 去重 + 长度上限；语义校验在 API 层与执行层 §2.3）。

契约（spec §2.1 逐字）:
- agent_order: list[list[str]] = Field(default_factory=list)（空 = 默认模板模式）
- 长度 ≤ 10（槽位编号 0-9）→ ValueError("agent_order 最多 10 层（槽位编号 0-9）")
- 每层必须为数组 → ValueError("agent_order 每层必须为数组")
- 元素必须为非空字符串（strip 后判空）→ ValueError("agent_order 元素必须为非空字符串")
- 跨层全局去重 → ValueError("agent_order 角色重复: {x}")
- 空层（[]）= 空槽，允许（保留）；元素 strip 规范化
- 默认值 default_factory=list → 存量项目零迁移（无键自动空）

RED 形态（当前字段不存在，Pydantic extra='ignore' 静默丢弃）:
- `"agent_order" in ProjectConfig().model_dump()` → AssertionError（字段缺失）
- ProjectConfig(agent_order=非法值) 不抛 → pytest.raises 用例 DID NOT RAISE
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.project import ProjectConfig


class TestAgentOrderDefault:
    """默认值语义：无 agent_order 键 → 空列表（默认模板模式，零迁移）。"""

    def test_default_empty_list(self) -> None:
        """ProjectConfig() → model_dump() 含 agent_order == []（默认模板模式）。"""
        cfg = ProjectConfig()
        dumped = cfg.model_dump()
        # RED：字段不存在 → KeyError/AssertionError（extra='ignore' 静默丢弃）
        assert "agent_order" in dumped
        assert dumped["agent_order"] == []

    def test_explicit_empty_list(self) -> None:
        """显式传 agent_order=[] → 空列表（默认模板模式，与缺省等价）。"""
        cfg = ProjectConfig(agent_order=[])
        assert cfg.model_dump()["agent_order"] == []


class TestAgentOrderValidStructure:
    """合法结构：层级嵌套 + 空槽 + strip 规范化。"""

    def test_valid_hierarchy_preserved(self) -> None:
        """合法四层链（默认拓扑显式化）→ 原样保留。"""
        order = [["agent_architect"], ["agent_writer"], ["agent_auditor"], ["agent_reviser"]]
        cfg = ProjectConfig(agent_order=order)
        assert cfg.model_dump()["agent_order"] == order

    def test_parallel_layer_preserved(self) -> None:
        """并行层（同层多角色）→ 原样保留（Q1 拍板：同层并行）。"""
        order = [["agent_architect"], ["agent_writer", "agent_auditor"], ["agent_reviser"]]
        cfg = ProjectConfig(agent_order=order)
        assert cfg.model_dump()["agent_order"] == order

    def test_empty_layer_allowed(self) -> None:
        """空层（[]）= 空槽，允许（v1.2 跳号语义）；保留空层不压缩。"""
        order = [["agent_architect"], [], ["agent_writer"]]
        cfg = ProjectConfig(agent_order=order)
        assert cfg.model_dump()["agent_order"] == order

    def test_ten_layers_max_ok(self) -> None:
        """恰好 10 层（槽位 0-9 上限）→ 合法。"""
        order = [[f"agent_architect_{i}"] for i in range(10)]
        cfg = ProjectConfig(agent_order=order)
        assert len(cfg.model_dump()["agent_order"]) == 10

    def test_items_stripped(self) -> None:
        """元素带空白 → strip 规范化（校验后去除空白）。"""
        cfg = ProjectConfig(agent_order=[["  agent_architect  "], ["agent_writer"]])
        assert cfg.model_dump()["agent_order"] == [["agent_architect"], ["agent_writer"]]

    def test_arbitrary_role_names_allowed(self) -> None:
        """角色名任意字符串（内置 4 + 自定义，v1.2 执行解锁）→ 合法。"""
        cfg = ProjectConfig(agent_order=[["agent_architect"], ["custom_agent_1", "custom_agent_2"]])
        assert cfg.model_dump()["agent_order"] == [
            ["agent_architect"],
            ["custom_agent_1", "custom_agent_2"],
        ]


class TestAgentOrderInvalid:
    """非法结构：长度超限 / 层非数组 / 元素非字符串 / 跨层重复。"""

    def test_too_many_layers_rejected(self) -> None:
        """长度 >10（槽位 0-9 超限）→ ValueError 中文消息。"""
        with pytest.raises(ValueError, match="agent_order 最多 10 层"):
            ProjectConfig(agent_order=[[f"agent_{i}"] for i in range(11)])

    def test_layer_not_list_rejected(self) -> None:
        """层不是数组（字符串）→ ValueError「每层必须为数组」。"""
        with pytest.raises(ValueError, match="agent_order 每层必须为数组"):
            ProjectConfig(agent_order=["agent_architect"])

    def test_empty_string_item_rejected(self) -> None:
        """元素为空字符串 → ValueError「非空字符串」。"""
        with pytest.raises(ValueError, match="agent_order 元素必须为非空字符串"):
            ProjectConfig(agent_order=[["agent_architect"], [""]])

    def test_whitespace_item_rejected(self) -> None:
        """元素为纯空白 → ValueError「非空字符串」。"""
        with pytest.raises(ValueError, match="agent_order 元素必须为非空字符串"):
            ProjectConfig(agent_order=[["   "]])

    def test_non_string_item_rejected(self) -> None:
        """元素非字符串（数字）→ ValueError「非空字符串」。"""
        with pytest.raises(ValueError, match="agent_order 元素必须为非空字符串"):
            ProjectConfig(agent_order=[[1]])

    def test_duplicate_across_layers_rejected(self) -> None:
        """同角色跨层出现两次 → ValueError「角色重复」（防歧义）。"""
        with pytest.raises(ValueError, match="agent_order 角色重复: agent_writer"):
            ProjectConfig(agent_order=[["agent_writer"], ["agent_architect", "agent_writer"]])

    def test_duplicate_within_layer_rejected(self) -> None:
        """同角色同层内重复 → ValueError「角色重复」。"""
        with pytest.raises(ValueError, match="agent_order 角色重复: agent_writer"):
            ProjectConfig(agent_order=[["agent_writer", "agent_writer"]])


class TestAgentRolesField:
    """F42 #295 ProjectConfig 自定义角色三态字段 agent_roles（spec §5.3.4 数据面第 2 点）。

    契约：agent_roles: dict[str, str | None]（key 带 agent_ 前缀，value 三态）：
    - 默认空 dict（零迁移）
    - value 三态语义与 agent_* 对齐：None=关闭 / "__default__"=跟随默认 / 字符串非空
    - 空字符串值 → ValueError「Agent 模型不能为空字符串」
    - 值 strip 规范化

    RED 形态：agent_roles 字段不存在（extra='ignore' 静默丢弃）→
    `"agent_roles" in model_dump()` AssertionError；非法值用例 pytest.raises DID NOT RAISE。
    """

    def test_default_empty_dict(self) -> None:
        """默认 agent_roles == {}（零迁移：旧 config JSON 无键 → 空 dict）。"""
        cfg = ProjectConfig()
        dumped = cfg.model_dump()
        assert "agent_roles" in dumped
        assert dumped["agent_roles"] == {}

    def test_explicit_custom_role_preserved(self) -> None:
        """显式 agent_roles（自定义角色字段名 → provider/model）保留。"""
        cfg = ProjectConfig(agent_roles={"agent_researcher": "zhipu/glm-4.5"})
        assert cfg.model_dump()["agent_roles"] == {"agent_researcher": "zhipu/glm-4.5"}

    def test_null_value_disables(self) -> None:
        """value None = 关闭（与 agent_* 同三态语义）。"""
        cfg = ProjectConfig(agent_roles={"agent_researcher": None})
        assert cfg.model_dump()["agent_roles"] == {"agent_researcher": None}

    def test_sentinel_follows_default(self) -> None:
        """value "__default__" = 跟随默认（AGENT_DEFAULT_SENTINEL 语义）。"""
        cfg = ProjectConfig(agent_roles={"agent_researcher": "__default__"})
        assert cfg.model_dump()["agent_roles"] == {"agent_researcher": "__default__"}

    def test_empty_string_rejected(self) -> None:
        """空字符串 value → ValueError「Agent 模型不能为空字符串」（三态校验）。"""
        with pytest.raises(ValueError, match="Agent 模型不能为空字符串"):
            ProjectConfig(agent_roles={"agent_researcher": ""})

    def test_whitespace_value_stripped(self) -> None:
        """value 带空白 → strip 规范化（与 agent_* 对齐）。"""
        cfg = ProjectConfig(agent_roles={"agent_researcher": "  zhipu/glm-4.5  "})
        assert cfg.model_dump()["agent_roles"] == {"agent_researcher": "zhipu/glm-4.5"}
