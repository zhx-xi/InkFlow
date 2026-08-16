"""agent_relations 存储层 + 语义校验契约（F46 #270，spec §2.1/§2.2/§2.3/§3/§7）。

被测：
- `AgentRelation`（domain/models/project.py 新增类，spec §2.1）：from_/to/type 三字段 +
  alias from + validator（from/to 非空、type 三值）
- `ProjectConfig.agent_relations`（spec §2.2）：list[AgentRelation] 字段 + mode="before"
  validator（结构/自环/重复边）
- `project_service._validate_agent_relations_config`（spec §2.3 API 层语义校验）：
  死角色引用（未知角色）/ agent_relations 自身环 / conditional 边唯一后继 → ValueError

RED 形态（两阶段）：
- 阶段 1（纯 RED）：`AgentRelation` 类不存在 → 顶部 import 收集期 ImportError
  （cannot import name 'AgentRelation'，exit 2）
- 阶段 2（实现补齐 AgentRelation + agent_relations 字段后，_validate_agent_relations_config
  仍未实现）：AgentRelation/ProjectConfig 用例转真实行为判定——Pydantic extra='ignore'
  静默丢 agent_relations 字段（现有 ProjectConfig 无 extra=forbid）→
  `model_dump()["agent_relations"]` KeyError / validator 用例 ValidationError；service 层
  `_validate_agent_relations_config` 不存在 → ImportError 或 ValueError 断言 FAIL

契约要点（spec §2.3 三层校验口径）：
- 存储层：结构（非 list → ValueError「agent_relations 必须为数组」）/ 自环（from==to →
  ValueError「agent_relations 自环非法: xxx」）/ 重复边（同 (from,to) → ValueError
  「agent_relations 重复边: xxx -> yyy」）/ type 非法 → ValueError「agent_relations 类型非法:
  xxx（应为 sequential/data/conditional）」/ from/to 空 → ValueError「agent_relations 的
  from/to 不能为空」；默认空列表（缺键 → []）
- API 层（service 校验，router catch ValueError → 422，镜像 F42 C1 _validate_agent_order_config
  同款落点）：死角色引用（from/to 去 agent_ 前缀后 ∉ 内置4 ∪ agent_roles）→ ValueError
  「agent_relations 引用了不存在的角色: xxx」；引用存在但未启用（agent_*=null）→ 允许保存；
  自身环（Kahn，relations 图有环）→ ValueError「agent_relations 存在循环依赖」；conditional
  边多后继（A 除 B 外还有其它出边，含基线全连接出边）→ ValueError「conditional 边 xxx->yyy
  要求 yyy 是 xxx 的唯一后继」

测试无网络约束：service 层校验为纯函数（只读 ProjectConfig），API 层形态镜像
test_project_service.py（真实 ProjectService + mock repo）。
"""

from __future__ import annotations

import pytest

# 🔴 AgentRelation 不存在 → 收集期 ImportError（阶段 1 RED）；GREEN 后正常解析
from inkflow.domain.models.project import (  # 契约主导入（RED 收集期 ImportError）
    AgentRelation,
    ProjectConfig,
)
from inkflow.domain.services.project_service import (  # 契约主导入（阶段 2 前 ImportError）
    _validate_agent_relations_config,
)

# ── 契约常量（spec §2.1 三类型 + §2.3 死角色口径）─────────────────────────
TYPE_SEQUENTIAL = "sequential"
TYPE_DATA = "data"
TYPE_CONDITIONAL = "conditional"

# 内置 4 角色字段名（§2.3 已知角色集合 = 内置4 ∪ agent_roles keys）
BUILTIN_ROLE_FIELDS = [
    "agent_architect",
    "agent_writer",
    "agent_auditor",
    "agent_reviser",
]


# ── AgentRelation 实体契约（spec §2.1）────────────────────────────────────


class TestAgentRelationModel:
    """AgentRelation 三字段 + alias + validator（spec §2.1 直译）。"""

    def test_from_alias_and_to_and_type_fields(self) -> None:
        """构造 {from, to, type}（JSON 形态）→ 字段解析正确。"""
        rel = AgentRelation.model_validate(
            {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}
        )
        assert rel.from_ == "agent_auditor"
        assert rel.to == "agent_reviser"
        assert rel.type == "conditional"

    def test_default_type_is_sequential(self) -> None:
        """type 缺省 → sequential（spec §2.4 默认 type 决策）。"""
        rel = AgentRelation(from_="agent_auditor", to="agent_reviser")
        assert rel.type == "sequential"

    def test_model_dump_by_alias_uses_from_key(self) -> None:
        """model_dump(by_alias=True) → {"from", "to", "type"}（issue #270 方案一致）。"""
        rel = AgentRelation(from_="agent_auditor", to="agent_reviser", type="data")
        dumped = rel.model_dump(by_alias=True)
        assert dumped == {"from": "agent_auditor", "to": "agent_reviser", "type": "data"}

    def test_from_to_whitespace_rejected(self) -> None:
        """from/to 全空白 → ValueError（§2.1 validator）。"""
        with pytest.raises(ValueError, match="from/to 不能为空"):
            AgentRelation(from_="   ", to="agent_reviser")

    def test_type_invalid_rejected(self) -> None:
        """type 非三值 → ValueError（§2.1 validator，消息含类型值 + 三值列表）。"""
        with pytest.raises(ValueError, match="agent_relations 类型非法: bogus"):
            AgentRelation(from_="agent_auditor", to="agent_reviser", type="bogus")


# ── ProjectConfig.agent_relations 存储层校验契约（spec §2.2）────────────────


class TestProjectConfigAgentRelations:
    """ProjectConfig.agent_relations 字段 + mode=before validator（spec §2.2）。"""

    def test_default_empty_list(self) -> None:
        """缺键 → 默认空列表（零迁移，旧 config 无此键）。"""
        cfg = ProjectConfig()
        assert cfg.agent_relations == []

    def test_parse_valid_relations(self) -> None:
        """合法 relations 数组 → 解析为 list[AgentRelation]。"""
        cfg = ProjectConfig(
            agent_relations=[
                {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"},
                {"from": "agent_writer", "to": "agent_reviser", "type": "data"},
            ]
        )
        assert len(cfg.agent_relations) == 2
        assert cfg.agent_relations[0].from_ == "agent_auditor"
        assert cfg.agent_relations[1].type == "data"

    def test_non_list_rejected(self) -> None:
        """agent_relations 非数组 → ValueError「agent_relations 必须为数组」。"""
        with pytest.raises(ValueError, match="agent_relations 必须为数组"):
            ProjectConfig(agent_relations={"from": "agent_auditor", "to": "agent_reviser"})

    def test_self_loop_rejected(self) -> None:
        """自环（from == to）→ ValueError「agent_relations 自环非法: xxx」。"""
        with pytest.raises(ValueError, match="agent_relations 自环非法: agent_auditor"):
            ProjectConfig(agent_relations=[{"from": "agent_auditor", "to": "agent_auditor"}])

    def test_duplicate_edge_rejected(self) -> None:
        """重复边（同 from,to 不同 type）→ ValueError「agent_relations 重复边: xxx -> yyy」。"""
        with pytest.raises(
            ValueError, match=r"agent_relations 重复边: agent_auditor -> agent_reviser"
        ):
            ProjectConfig(
                agent_relations=[
                    {"from": "agent_auditor", "to": "agent_reviser", "type": "sequential"},
                    {"from": "agent_auditor", "to": "agent_reviser", "type": "data"},
                ]
            )

    def test_same_edge_different_type_is_duplicate(self) -> None:
        """同 (from,to) 不同 type = 重复边（§2.2 明确拒绝，防歧义）。"""
        with pytest.raises(ValueError, match="重复边"):
            ProjectConfig(
                agent_relations=[
                    {"from": "agent_writer", "to": "agent_auditor", "type": "data"},
                    {"from": "agent_writer", "to": "agent_auditor", "type": "conditional"},
                ]
            )

    def test_roundtrip_model_dump(self) -> None:
        """model_dump() 序列化 → from 键名（by_alias 传播到 config dump）。"""
        cfg = ProjectConfig(
            agent_relations=[
                {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}
            ]
        )
        dumped = cfg.model_dump()
        assert dumped["agent_relations"] == [
            {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}
        ]


# ── _validate_agent_relations_config API 层语义校验（spec §2.3 API 层）────────


def _cfg(**overrides: object) -> ProjectConfig:
    """构造带默认启用角色的 ProjectConfig（内置 4 全启用，供死引用/环/后继校验）。"""
    defaults: dict[str, object] = {
        "agent_architect": "openai/gpt-4o",
        "agent_writer": "openai/gpt-4o",
        "agent_auditor": "openai/gpt-4o",
        "agent_reviser": "openai/gpt-4o",
    }
    defaults.update(overrides)
    return ProjectConfig(**defaults)


class TestValidateAgentRelationsConfig:
    """_validate_agent_relations_config（spec §2.3 API 层）→ ValueError（router 转 422）。"""

    def test_empty_relations_noop(self) -> None:
        """空 relations → 不抛错（零迁移）。"""
        _validate_agent_relations_config(_cfg(agent_relations=[]))

    def test_dead_role_reference_rejected(self) -> None:
        """from/to 引用未知角色（非内置4非agent_roles）→ ValueError「引用了不存在的角色」。"""
        with pytest.raises(ValueError, match="agent_relations 引用了不存在的角色: agent_ghost"):
            _validate_agent_relations_config(
                _cfg(
                    agent_relations=[
                        {"from": "agent_ghost", "to": "agent_reviser", "type": "sequential"}
                    ]
                )
            )

    def test_dead_role_reference_in_to_rejected(self) -> None:
        """to 引用未知角色 → 同样拒绝（from/to 双向口径）。"""
        with pytest.raises(ValueError, match="agent_relations 引用了不存在的角色: agent_ghost"):
            _validate_agent_relations_config(
                _cfg(
                    agent_relations=[
                        {"from": "agent_auditor", "to": "agent_ghost", "type": "sequential"}
                    ]
                )
            )

    def test_custom_role_from_agent_roles_known(self) -> None:
        """引用 agent_roles 自定义角色 → 通过（agent_roles 是引用面，F42 #295）。"""
        _validate_agent_relations_config(
            _cfg(
                agent_roles={"agent_researcher": "openai/gpt-4o"},
                agent_relations=[
                    {"from": "agent_researcher", "to": "agent_reviser", "type": "data"}
                ],
            )
        )

    def test_disabled_role_reference_allowed(self) -> None:
        """引用存在但未启用角色（agent_*=null）→ 允许保存（§2.3 软降级，前端提示）。"""
        _validate_agent_relations_config(
            _cfg(
                agent_auditor=None,  # 存在但未启用
                agent_relations=[
                    {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}
                ],
            )
        )

    def test_self_cycle_rejected(self) -> None:
        """relations 图自身有环（a→b, b→a）→ ValueError「存在循环依赖」。"""
        with pytest.raises(ValueError, match="agent_relations 存在循环依赖"):
            _validate_agent_relations_config(
                _cfg(
                    agent_relations=[
                        {"from": "agent_auditor", "to": "agent_writer", "type": "sequential"},
                        {"from": "agent_writer", "to": "agent_auditor", "type": "sequential"},
                    ]
                )
            )

    def test_longer_cycle_rejected(self) -> None:
        """三节点环（a→b, b→c, c→a）→ 拒绝。"""
        with pytest.raises(ValueError, match="agent_relations 存在循环依赖"):
            _validate_agent_relations_config(
                _cfg(
                    agent_relations=[
                        {"from": "agent_architect", "to": "agent_writer", "type": "sequential"},
                        {"from": "agent_writer", "to": "agent_auditor", "type": "sequential"},
                        {"from": "agent_auditor", "to": "agent_architect", "type": "sequential"},
                    ]
                )
            )

    def test_acyclic_relations_pass(self) -> None:
        """无环 DAG（architect→writer→auditor→reviser）→ 通过。"""
        _validate_agent_relations_config(
            _cfg(
                agent_relations=[
                    {"from": "agent_architect", "to": "agent_writer", "type": "sequential"},
                    {"from": "agent_writer", "to": "agent_auditor", "type": "data"},
                    {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"},
                ]
            )
        )

    def test_conditional_multi_successor_rejected(self) -> None:
        """conditional 边 A→B 但 A 有其它出边（relations 出边，基线同层）→ ValueError
        「conditional 边 xxx->yyy 要求 yyy 是 xxx 的唯一后继」。

        构造：auditor→reviser conditional + auditor→writer data——auditor 除 reviser 外
        还有 writer 出边 → 多后继违反唯一后继约束（spec §2.3 ③）。
        """
        with pytest.raises(
            ValueError,
            match=(
                "conditional 边 agent_auditor->agent_reviser 要求 "
                "agent_reviser 是 agent_auditor 的唯一后继"
            ),
        ):
            _validate_agent_relations_config(
                _cfg(
                    agent_relations=[
                        {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"},
                        {"from": "agent_auditor", "to": "agent_writer", "type": "data"},
                    ]
                )
            )

    def test_conditional_single_successor_pass(self) -> None:
        """conditional 边 A→B 且 A 仅此一条出边 → 通过。"""
        _validate_agent_relations_config(
            _cfg(
                agent_relations=[
                    {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}
                ]
            )
        )

    def test_dict_elements_normalized(self) -> None:
        """PATCH 合并路径（model_copy 不触发 validator）→ 元素是裸 dict 也能校验。

        真实 API 路径 `existing.config.model_copy(update={"agent_relations": [dict...]})`
        不经过 Pydantic validator（model_copy 浅拷贝不重新校验）——`_validate_agent_relations_config`
        必须内部规范化 dict → AgentRelation，不能假设元素已是实例（否则 AttributeError
        而非 422，M7 API 层验证实证 2026-08-16）。
        """
        config = _cfg()
        config.agent_relations = [
            {"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}
        ]  # type: ignore[assignment]  # 契约：裸 dict 元素形态（model_copy 产物）
        # 不应抛 AttributeError；死引用仍应 422 语义
        _validate_agent_relations_config(config)

    def test_dict_elements_dead_ref_still_rejected(self) -> None:
        """裸 dict 元素 + 死引用 → 仍拒绝（规范化后校验语义不变）。"""
        config = _cfg()
        config.agent_relations = [
            {"from": "agent_ghost", "to": "agent_writer", "type": "sequential"}
        ]  # type: ignore[assignment]  # 契约：裸 dict 元素形态
        with pytest.raises(ValueError, match="agent_relations 引用了不存在的角色: agent_ghost"):
            _validate_agent_relations_config(config)
