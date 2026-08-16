"""_apply_agent_relations 执行层拓扑叠加契约（F46 #270，spec §5.3.1 + §13 M5）。

被测：agent_service 模块级纯函数
`_apply_agent_relations(stages, agent_relations, enabled_roles)` →
`tuple[list[PipelineStage], list[tuple[str, str]]]`
（spec §6：domain 服务层模块级函数，纯函数不依赖 infrastructure——测试只依赖
PipelineStage 与内置模板构造输入，镜像 test_agent_order_apply.py 形态）。

契约（spec §5.3.1 步骤 1-6）:
1. 输入：基线 stages（_apply_agent_order 输出，分层全连接 DAG）+ config.agent_relations
   （AgentRelation 列表）+ enabled_roles（启用角色字段名集合，同 F42 口径）
2. 空 agent_relations → 原样返回（stages, []）——纯基线，零迁移（§1.2.3 线性兼容）
3. 防御校验（warning + 原样返回，忽略关系）：① 死角色引用（from/to 去 agent_ 前缀后
   ∉ 启用角色集合）；② agent_relations 自身环；③ conditional 边多后继（B 非 A 唯一后继）
4. 逐边叠加（关系优先，边去前缀 = A/B）：
   - sequential A→B 同层（A ∉ B 传递前序）→ A.output_to 追加 B、B.input_from 不加 A；
     跨层（B 已在 A 后序）→ 基线已覆盖，无引擎增量（幂等）
   - data A→B 同层 → A.output_to 追加 B、B.input_from 追加 A；跨层 → 幂等确保
     A ∈ B.input_from
   - conditional A→B → B.input_from 追加 A；记录 (A, B) 进 conditional_edges 集合
5. 合成后环检测（Kahn，最终 input_from/output_to 图）——逆序边与基线层序冲突
   → warning + 回退纯基线（返回输入 stages + []）
6. 返回 (叠加后 stages, conditional_edges)

RED 形态（两阶段）：
- 阶段 1（纯 RED）：_apply_agent_relations 不存在 → 顶部 import 收集期 ImportError
  （cannot import name '_apply_agent_relations'，exit 2）
- 阶段 2（函数存在后）：各用例按真实行为判定（预期大多 FAIL 直至实现）

测试无网络约束：纯函数，无 LLM/DB 依赖。
"""

from __future__ import annotations

from inkflow.domain.models.project import AgentRelation
from inkflow.domain.ports.agent_pipeline import PipelineStage
from inkflow.domain.services.agent_service import _apply_agent_order, _apply_agent_relations
from inkflow.infrastructure.agent.pipeline_templates import get_template

# 内置 4 角色字段名（enabled_roles 口径：agent_* 字段名，带前缀）
F_ARCHITECT = "agent_architect"
F_WRITER = "agent_writer"
F_AUDITOR = "agent_auditor"
F_REVISER = "agent_reviser"
ALL_ENABLED = {F_ARCHITECT, F_WRITER, F_AUDITOR, F_REVISER}

# 默认模板 stages（builtin:write_chapter 四阶段链式）
DEFAULT_STAGES = get_template("builtin:write_chapter").stages

# 同层并行基线：[[architect],[writer,auditor],[reviser]]（F42 #269 M5 场景）——
# writer/auditor 同层并行（input_from=[architect]，output_to=[reviser]）
PARALLEL_BASELINE = _apply_agent_order(
    list(DEFAULT_STAGES),
    [[F_ARCHITECT], [F_WRITER, F_AUDITOR], [F_REVISER]],
    ALL_ENABLED,
)


def _stage_ids(stages: list[PipelineStage]) -> list[str]:
    """提取 stage.id 序列（顺序断言用）。"""
    return [s.id for s in stages]


def _rel(from_field: str, to_field: str, rel_type: str = "sequential") -> AgentRelation:
    """构造 AgentRelation（字段名形态）。"""
    return AgentRelation(from_=from_field, to=to_field, type=rel_type)


def _by_id(stages: list[PipelineStage]) -> dict[str, PipelineStage]:
    return {s.id: s for s in stages}


class TestEmptyRelations:
    """空 agent_relations → 原样返回（纯基线，线性兼容）。"""

    def test_empty_returns_stages_unchanged(self) -> None:
        """空 relations → (原 stages, [])——顺序与边完全不变。"""
        result, conditional_edges = _apply_agent_relations(list(DEFAULT_STAGES), [], ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]
        assert conditional_edges == []
        # 边不变（reviser 原始 input_from）
        assert _by_id(result)["reviser"].input_from == ["writer", "auditor"]

    def test_empty_on_parallel_baseline_unchanged(self) -> None:
        """同层并行基线上空 relations → 边不变（并行保持）。"""
        result, conditional_edges = _apply_agent_relations(list(PARALLEL_BASELINE), [], ALL_ENABLED)
        assert conditional_edges == []
        by_id = _by_id(result)
        # writer/auditor 同层并行：input_from=[architect]，output_to=[reviser]
        assert by_id["writer"].input_from == ["architect"]
        assert by_id["writer"].output_to == ["reviser"]
        assert by_id["auditor"].input_from == ["architect"]
        assert by_id["auditor"].output_to == ["reviser"]


class TestDefensiveFallback:
    """防御校验：任何非法 → warning + 原样返回（忽略关系，永不抛错）。"""

    def test_dead_role_reference_falls_back(self) -> None:
        """引用未启用角色（不在 enabled_roles）→ 原样返回 + conditional_edges 空。"""
        stages = list(DEFAULT_STAGES)
        result, conditional_edges = _apply_agent_relations(
            stages,
            [_rel("agent_ghost", F_REVISER)],
            ALL_ENABLED,
        )
        assert result is stages  # 原对象返回（回退语义）
        assert conditional_edges == []

    def test_self_cycle_falls_back(self) -> None:
        """relations 自身有环 → 原样返回。"""
        stages = list(DEFAULT_STAGES)
        result, conditional_edges = _apply_agent_relations(
            stages,
            [_rel(F_AUDITOR, F_WRITER), _rel(F_WRITER, F_AUDITOR)],
            ALL_ENABLED,
        )
        assert result is stages
        assert conditional_edges == []

    def test_conditional_multi_successor_falls_back(self) -> None:
        """conditional 边 A→B 但 A 有其它出边 → 原样返回（唯一后继约束执行层防御）。"""
        stages = list(DEFAULT_STAGES)
        result, conditional_edges = _apply_agent_relations(
            stages,
            [
                _rel(F_AUDITOR, F_REVISER, "conditional"),
                _rel(F_AUDITOR, F_WRITER, "data"),
            ],
            ALL_ENABLED,
        )
        assert result is stages
        assert conditional_edges == []

    def test_synthesized_cycle_falls_back(self) -> None:
        """合成后完整图有环（逆序边与基线层序冲突）→ 回退纯基线 + 空 conditional_edges。

        构造：基线 = 链式（architect→writer→auditor→reviser）；关系定义逆序边
        reviser→writer（data）——基线已有 writer→…→reviser 路径，叠加 reviser→writer
        产生环 → 回退。
        """
        stages = list(DEFAULT_STAGES)
        result, conditional_edges = _apply_agent_relations(
            stages,
            [_rel(F_REVISER, F_WRITER, "data")],
            ALL_ENABLED,
        )
        assert result is stages
        assert conditional_edges == []


class TestSequentialEdge:
    """sequential：纯时序，不注入。"""

    def test_cross_layer_no_engine_change(self) -> None:
        """跨层 sequential（architect→writer 基线已覆盖）→ 幂等无引擎增量。"""
        stages = list(DEFAULT_STAGES)
        result, conditional_edges = _apply_agent_relations(
            stages, [_rel(F_ARCHITECT, F_WRITER)], ALL_ENABLED
        )
        by_id = _by_id(result)
        assert by_id["architect"].output_to == ["writer"]  # 不变（基线已有）
        assert by_id["writer"].input_from == ["architect"]  # 不变
        assert conditional_edges == []

    def test_same_layer_breaks_parallel(self) -> None:
        """同层 sequential（writer→auditor，平行基线）→ 打破并行：writer.output_to 追加
        auditor；auditor.input_from **不加** writer（纯时序不注入，§1.2.1）。"""
        result, conditional_edges = _apply_agent_relations(
            list(PARALLEL_BASELINE), [_rel(F_WRITER, F_AUDITOR)], ALL_ENABLED
        )
        by_id = _by_id(result)
        assert by_id["writer"].output_to == ["reviser", "auditor"]  # 追加同层 auditor
        assert by_id["auditor"].input_from == ["architect"]  # 不加 writer（纯时序）
        assert conditional_edges == []


class TestDataEdge:
    """data：数据流（隐含时序），注入 {from}_output。"""

    def test_cross_layer_idempotent_ensure(self) -> None:
        """跨层 data（writer→auditor 基线已注入）→ 幂等确保 A ∈ B.input_from。"""
        stages = list(DEFAULT_STAGES)
        result, conditional_edges = _apply_agent_relations(
            stages, [_rel(F_WRITER, F_AUDITOR, "data")], ALL_ENABLED
        )
        by_id = _by_id(result)
        assert by_id["auditor"].input_from == ["writer"]  # 不变（基线已有）
        assert conditional_edges == []

    def test_same_layer_breaks_parallel_and_injects(self) -> None:
        """同层 data（writer→auditor，平行基线）→ 打破并行 + 注入：writer.output_to 追加
        auditor；auditor.input_from 追加 writer。"""
        result, conditional_edges = _apply_agent_relations(
            list(PARALLEL_BASELINE), [_rel(F_WRITER, F_AUDITOR, "data")], ALL_ENABLED
        )
        by_id = _by_id(result)
        assert by_id["writer"].output_to == ["reviser", "auditor"]
        assert by_id["auditor"].input_from == ["architect", "writer"]  # 追加注入
        assert conditional_edges == []

    def test_cross_layer_non_baseline_edge_adds_sequential_only(self) -> None:
        """跨层 data 但基线无直接边（architect→auditor，基线 architect 只连 writer）→
        architect.output_to 追加 auditor + auditor.input_from 追加 architect（显式声明）。"""
        stages = list(DEFAULT_STAGES)
        result, conditional_edges = _apply_agent_relations(
            stages, [_rel(F_ARCHITECT, F_AUDITOR, "data")], ALL_ENABLED
        )
        by_id = _by_id(result)
        assert by_id["architect"].output_to == ["writer", "auditor"]
        assert by_id["auditor"].input_from == ["writer", "architect"]
        assert conditional_edges == []


class TestConditionalEdge:
    """conditional：条件分支，注入 + conditional_edges 集合。"""

    def test_marks_edge_and_injects(self) -> None:
        """conditional（writer→auditor）→ auditor.input_from 追加 writer + conditional_edges
        含 (writer, auditor)；A 出边不变（条件路由在引擎构建）。"""
        result, conditional_edges = _apply_agent_relations(
            list(PARALLEL_BASELINE), [_rel(F_WRITER, F_AUDITOR, "conditional")], ALL_ENABLED
        )
        by_id = _by_id(result)
        assert by_id["auditor"].input_from == ["architect", "writer"]  # 注入
        assert conditional_edges == [("writer", "auditor")]
        # A 出边不变（writer 仍指向 reviser；条件路由由引擎 add_conditional_edges 处理）
        assert by_id["writer"].output_to == ["reviser"]

    def test_conditional_edges_preserves_order(self) -> None:
        """多条 conditional 边 → conditional_edges 按声明序收集。"""
        _, conditional_edges = _apply_agent_relations(
            list(DEFAULT_STAGES),
            [
                _rel(F_WRITER, F_AUDITOR, "conditional"),
                _rel(F_AUDITOR, F_REVISER, "conditional"),
            ],
            ALL_ENABLED,
        )
        assert conditional_edges == [("writer", "auditor"), ("auditor", "reviser")]

    def test_default_template_baseline_conditional(self) -> None:
        """默认模板基线上 conditional auditor→reviser → 注入 + 标记（M5 场景）。"""
        result, conditional_edges = _apply_agent_relations(
            list(DEFAULT_STAGES),
            [_rel(F_AUDITOR, F_REVISER, "conditional")],
            ALL_ENABLED,
        )
        by_id = _by_id(result)
        assert by_id["reviser"].input_from == ["writer", "auditor"]  # 已含 auditor，幂等
        assert conditional_edges == [("auditor", "reviser")]
