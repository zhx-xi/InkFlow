"""_apply_agent_order 执行层拓扑契约（F42 #269，spec §5.3.1 + §13 M5）。

被测：agent_service 模块级纯函数 _apply_agent_order(stages, agent_order, enabled_roles)
（spec §6：domain 服务层模块级函数，纯函数不依赖 infrastructure——测试只依赖
PipelineStage 与内置模板构造输入）。

契约（spec §5.3.1 步骤 2-8 + v1.3 B1/F3/F4/F5 修正）:
1. 输入：模板 stages（4 阶段链式）+ 项目 config.agent_order（层级嵌套角色字段名数组，
   带 agent_ 前缀）+ enabled_roles（启用角色字段名集合，来自 agent_* 非 null）
2. 双模式分派（B1）：agent_order 空 = 默认模板模式 → 原样返回（null 不触发跳过）；
   非空 = 配置驱动模式 → 继续
3. 语义校验（防御）：缺启用角色 / 长度 >10 / 跨层重复 → 记 warning + 原样返回（回退默认）
4. 跳过过滤（Q2 + B1）：配置驱动模式下 enabled_roles 不含的角色（null）从拓扑摘除
   （无论是否在 agent_order 中；§2.3 关闭角色语义）
5. 层级映射：agent_xxx → xxx（stage.id）；自定义角色（非内置且模板无此 stage，
   prompt 无来源）→ 跳过 + warning（§5.3.4 过渡期防御）
6. 全连接边重建：第 i 层每节点 input_from = 前序全部非空层所有角色；
   output_to = 后序全部非空层所有角色（空槽不改变前序全层成员集合，v1.3 F7）
7. 拓扑-引用一致性校验（F4/F5）：静态扫描各角色 prompt 的 {role}_output 占位符，
   被引用角色（存在于 stages）必须位于该角色的严格前序层；违规（含同层互引）→
   回退默认拓扑 + warning
8. 终点角色校验（成品身份，§5.6）：重排后终点角色为 architect/auditor（非内容产出）
   → 回退默认拓扑 + warning
9. 返回重排后 stages（供 _merge_role_configs 装配）

RED 形态：_apply_agent_order 不存在 → 本文件顶部 import → 收集期 ImportError
（cannot import name _apply_agent_order，exit 2）——两阶段 RED：实现补齐函数后
各用例按真实行为判定。
"""

from __future__ import annotations

from inkflow.domain.ports.agent_pipeline import PipelineStage
from inkflow.domain.services.agent_service import _apply_agent_order
from inkflow.infrastructure.agent.pipeline_templates import get_template

# 内置 4 角色字段名（enabled_roles 口径：agent_* 字段名，带前缀）
F_ARCHITECT = "agent_architect"
F_WRITER = "agent_writer"
F_AUDITOR = "agent_auditor"
F_REVISER = "agent_reviser"
ALL_ENABLED = {F_ARCHITECT, F_WRITER, F_AUDITOR, F_REVISER}

# 默认模板 stages（builtin:write_chapter 四阶段链式）
DEFAULT_STAGES = get_template("builtin:write_chapter").stages


def _stage_ids(stages: list[PipelineStage]) -> list[str]:
    """提取 stage.id 序列（重排顺序断言用）。"""
    return [s.id for s in stages]


def _make_custom_stage(stage_id: str, prompt: str) -> PipelineStage:
    """构造非内置角色 stage（模拟模板 roles 提供的自定义角色）。"""
    from inkflow.domain.ports.agent_pipeline import AgentRole

    role = AgentRole(
        id=stage_id,
        name=stage_id,
        system_prompt=prompt,
        model="openai/gpt-4o",
    )
    return PipelineStage(id=stage_id, name=stage_id, agent=role)


class TestDefaultTemplateMode:
    """双模式分派 ①：agent_order 空 = 默认模板模式（B1）。"""

    def test_empty_order_returns_stages_unchanged(self) -> None:
        """agent_order=[] → 原样返回（模板默认拓扑，零迁移）。"""
        result = _apply_agent_order(list(DEFAULT_STAGES), [], ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_empty_order_null_roles_not_skipped(self) -> None:
        """默认模板模式：enabled_roles 为空（全 null）也不跳过任何角色（v1.0 语义）。"""
        result = _apply_agent_order(list(DEFAULT_STAGES), [], set())
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_empty_order_edge_references_untouched(self) -> None:
        """默认模板模式：模板边（input_from/output_to）原样保留（不重建）。"""
        result = _apply_agent_order(list(DEFAULT_STAGES), [], ALL_ENABLED)
        by_id = {s.id: s for s in result}
        # 模板原始值（F42 #269 F4 修正后 reviser 同时依赖 writer + auditor）
        assert by_id["reviser"].input_from == ["writer", "auditor"]


class TestHierarchicalReorder:
    """配置驱动模式：层级重排（Q1 拍板：层间串行 + 同层并行）。"""

    def test_default_hierarchy_order(self) -> None:
        """显式化默认拓扑 [[architect],[writer],[auditor],[reviser]] → 顺序不变。"""
        order = [[F_ARCHITECT], [F_WRITER], [F_AUDITOR], [F_REVISER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_parallel_layer_reorder(self) -> None:
        """writer+auditor 并行：[[architect],[writer,auditor],[reviser]]（M5 场景）。"""
        order = [[F_ARCHITECT], [F_WRITER, F_AUDITOR], [F_REVISER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]
        # 层序断言：architect（层 0）→ writer/auditor（层 1）→ reviser（层 2）
        idx = {sid: i for i, sid in enumerate(_stage_ids(result))}
        assert idx["architect"] < idx["writer"]
        assert idx["architect"] < idx["auditor"]
        assert idx["writer"] < idx["reviser"]
        assert idx["auditor"] < idx["reviser"]

    def test_reversed_order(self) -> None:
        """逆序重排（终点合法——writer 为终点，architect 不落末位）：按配置重排。"""
        order = [[F_REVISER], [F_AUDITOR], [F_ARCHITECT], [F_WRITER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["reviser", "auditor", "architect", "writer"]

    def test_empty_slot_skipped(self) -> None:
        """空槽（[]）正常跳过：[[architect],[],[reviser]] → 无 writer/auditor 角色？"""
        # 注意：agent_order 缺 writer/auditor 但 enabled 含全部 → 缺启用角色 → 回退！
        # 空槽跳号场景必须 enabled 不含该角色（见 test_skip_filter）——此处验证
        # 「enabled 也缺」时跳号正常：只重排启用角色
        order = [[F_ARCHITECT], [], [F_REVISER]]
        enabled = {F_ARCHITECT, F_REVISER}
        result = _apply_agent_order(list(DEFAULT_STAGES), order, enabled)
        assert _stage_ids(result) == ["architect", "reviser"]


class TestSkipFilter:
    """配置驱动模式跳过过滤：null 角色从拓扑摘除（Q2 真禁用 + B1 限定）。"""

    def test_null_role_removed_from_order(self) -> None:
        """agent_order 含 4 角色但 auditor null → auditor 摘除，其余按序。"""
        order = [[F_ARCHITECT], [F_WRITER], [F_AUDITOR], [F_REVISER]]
        enabled = {F_ARCHITECT, F_WRITER, F_REVISER}
        result = _apply_agent_order(list(DEFAULT_STAGES), order, enabled)
        assert _stage_ids(result) == ["architect", "writer", "reviser"]

    def test_null_role_present_in_order_still_skipped(self) -> None:
        """null 角色即使保留在 agent_order 中仍被摘除（null 优先于拓扑，§2.3）。"""
        order = [[F_ARCHITECT], [F_WRITER, F_AUDITOR], [F_REVISER]]
        enabled = {F_ARCHITECT, F_WRITER, F_REVISER}
        result = _apply_agent_order(list(DEFAULT_STAGES), order, enabled)
        assert _stage_ids(result) == ["architect", "writer", "reviser"]

    def test_disabled_all_roles_returns_empty(self) -> None:
        """全部角色关闭（enabled 空）→ 配置驱动模式无角色可执行 → 空列表。"""
        order = [[F_ARCHITECT], [F_WRITER], [F_AUDITOR], [F_REVISER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, set())
        assert result == []


class TestInvalidFallback:
    """语义校验（执行层防御）：任何非法 → 记 warning + 原样返回（回退默认拓扑）。"""

    def test_missing_enabled_role_falls_back(self) -> None:
        """agent_order 缺启用角色（writer 启用但不在 order）→ 回退默认拓扑。"""
        order = [[F_ARCHITECT], [F_AUDITOR], [F_REVISER]]
        enabled = ALL_ENABLED  # writer 启用但 order 缺失
        result = _apply_agent_order(list(DEFAULT_STAGES), order, enabled)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_too_many_layers_falls_back(self) -> None:
        """长度 >10（执行层防御，存储层已拦的损坏数据）→ 回退默认拓扑。"""
        order = [[f"agent_{i}"] for i in range(11)]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_duplicate_role_falls_back(self) -> None:
        """跨层重复（执行层防御）→ 回退默认拓扑。"""
        order = [[F_WRITER], [F_ARCHITECT, F_WRITER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]


class TestFullConnectEdges:
    """全连接边重建（步骤 6）：input_from=前序全部非空层、output_to=后序全部非空层。"""

    def test_parallel_layer_edges(self) -> None:
        """[[architect],[writer,auditor],[reviser]] → 全连接边断言（M5）。"""
        order = [[F_ARCHITECT], [F_WRITER, F_AUDITOR], [F_REVISER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        by_id = {s.id: s for s in result}
        # writer/auditor（层 1）：input_from = 前序全部（architect）
        assert by_id["writer"].input_from == ["architect"]
        assert by_id["auditor"].input_from == ["architect"]
        # reviser（层 2）：input_from = 前序全部（architect + writer + auditor）
        assert sorted(by_id["reviser"].input_from) == ["architect", "auditor", "writer"]
        # architect（层 0）：output_to = 后序全部
        assert sorted(by_id["architect"].output_to) == ["auditor", "reviser", "writer"]
        # writer/auditor（层 1）：output_to = 后序全部（reviser）
        assert by_id["writer"].output_to == ["reviser"]
        assert by_id["auditor"].output_to == ["reviser"]

    def test_empty_slot_does_not_break_full_connect(self) -> None:
        """空槽不改变前序全层成员集合（v1.3 F7）：[[architect],[],[reviser]]。"""
        order = [[F_ARCHITECT], [], [F_REVISER]]
        enabled = {F_ARCHITECT, F_REVISER}
        result = _apply_agent_order(list(DEFAULT_STAGES), order, enabled)
        by_id = {s.id: s for s in result}
        assert by_id["reviser"].input_from == ["architect"]  # 前序非空层全连接
        assert by_id["architect"].output_to == ["reviser"]

    def test_reordered_edges(self) -> None:
        """重排 [[reviser],[auditor],[architect],[writer]] → 边随重排重建（终点 writer 合法）。"""
        order = [[F_REVISER], [F_AUDITOR], [F_ARCHITECT], [F_WRITER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        by_id = {s.id: s for s in result}
        # reviser（层 0）→ output_to = 后序全部
        assert sorted(by_id["reviser"].output_to) == ["architect", "auditor", "writer"]
        # auditor（层 1）→ input_from = 前序（reviser）；output_to = 后序（architect+writer）
        assert by_id["auditor"].input_from == ["reviser"]
        assert sorted(by_id["auditor"].output_to) == ["architect", "writer"]
        # architect（层 2）→ input_from = 前序两层
        assert by_id["architect"].input_from == ["reviser", "auditor"]
        # writer（层 3）→ input_from = 前序全部；终点
        assert by_id["writer"].input_from == ["reviser", "auditor", "architect"]
        assert by_id["writer"].output_to == []

    def test_reordered_passes_engine_validate(self) -> None:
        """重排后 validate() 恒通过（M5：全连接边无环 + 入口/终点合法）。"""
        from inkflow.domain.ports.llm_client import LLMClientProtocol
        from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline

        class _DummyLLM(LLMClientProtocol):  # type: ignore[misc]
            async def chat(
                self, messages, *, model=None, temperature=None, max_tokens=None, **kwargs
            ):
                from inkflow.domain.ports.llm_client import ChatResponse

                return ChatResponse(content="ok", model=model or "mock")

        order = [[F_REVISER], [F_AUDITOR, F_WRITER], [F_ARCHITECT]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        pipeline = LangGraphAgentPipeline(_DummyLLM())
        assert pipeline.validate(result) == []


class TestReferenceSoftDegrade:
    """引用不一致 = 空注入软降级（v1.3 B8 定稿 + §9/M4/§7 一致：未来层/同层引用
    → 空串，不拒绝不回退；用户自由排序 Q1 的明确代价）。

    ⚠️ 与 spec 步骤 7「违规回退默认」表述冲突（F4/F5 残留）——裁定取 B8 定稿 +
    M4 验收（「变量空注入防御（未来层/同层 → 空串）」）+ §7 错误表（软降级），
    已在 Plan C3 留痕回报 TODO。空注入机制由 pipeline_nodes 层测试覆盖。
    """

    def test_future_layer_reference_kept(self) -> None:
        """auditor 排 writer 前（auditor prompt 引用 {writer_output} = 未来层）
        → 不因引用回退，重排保持（执行时空注入）。"""
        order = [[F_AUDITOR], [F_WRITER], [F_ARCHITECT], [F_REVISER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["auditor", "writer", "architect", "reviser"]

    def test_same_layer_reference_kept(self) -> None:
        """writer/auditor 同层（M5 并行场景 [[architect],[writer,auditor],[reviser]]）
        → 不因同层互引回退，并行拓扑保持（同层不可见 = 空注入）。"""
        order = [[F_ARCHITECT], [F_WRITER, F_AUDITOR], [F_REVISER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_consistent_dependency_order_not_fallback(self) -> None:
        """依赖序拓扑（architect < writer < auditor < reviser 各层）引用全部在严格前序
        → 按配置执行（默认拓扑显式化的等价场景）。"""
        order = [[F_ARCHITECT], [F_WRITER], [F_AUDITOR], [F_REVISER]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]


class TestTerminalRoleCheck:
    """终点角色校验（成品身份，§5.6 🔴-1）：终点为 architect/auditor → 回退默认。"""

    def test_terminal_auditor_falls_back(self) -> None:
        """auditor 排最后（终点非内容产出）→ 回退默认拓扑。"""
        order = [[F_ARCHITECT], [F_WRITER], [F_REVISER], [F_AUDITOR]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_terminal_architect_falls_back(self) -> None:
        """architect 排最后 → 回退默认拓扑。"""
        order = [[F_WRITER], [F_AUDITOR], [F_REVISER], [F_ARCHITECT]]
        result = _apply_agent_order(list(DEFAULT_STAGES), order, ALL_ENABLED)
        assert _stage_ids(result) == ["architect", "writer", "auditor", "reviser"]

    def test_terminal_writer_valid(self) -> None:
        """writer 为终点（无 auditor/reviser）→ 合法（成品 = 最后一个内容角色）。"""
        order = [[F_ARCHITECT], [F_WRITER]]
        enabled = {F_ARCHITECT, F_WRITER}
        result = _apply_agent_order(list(DEFAULT_STAGES), order, enabled)
        assert _stage_ids(result) == ["architect", "writer"]


class TestCustomRoleDefense:
    """自定义角色（v1.2/v1.3）：agent_order 支持任意角色名；prompt 缺失 → 跳过 + warning。"""

    def test_custom_role_missing_prompt_skipped(self) -> None:
        """agent_order 含 custom_role 且模板无此 stage（prompt 无来源）→ 跳过 + 其余正常。"""
        order = [[F_ARCHITECT], [F_WRITER], ["custom_role"]]
        enabled = {F_ARCHITECT, F_WRITER, "custom_role"}
        result = _apply_agent_order(list(DEFAULT_STAGES), order, enabled)
        # custom_role 无 stage 可映射 → 跳过；architect/writer 保留
        assert _stage_ids(result) == ["architect", "writer"]

    def test_custom_role_with_stage_participates(self) -> None:
        """自定义角色在 stages 中存在（模板 roles 已装配）且引用前序层（一致性 OK）
        → 参与重排与全连接边。"""
        stages = [
            *DEFAULT_STAGES,
            _make_custom_stage("custom_role", "你是架构规划检查员，依据 {architect_output} 检查"),
        ]
        order = [[F_ARCHITECT], [F_WRITER, "custom_role"]]
        enabled = {F_ARCHITECT, F_WRITER, "custom_role"}
        result = _apply_agent_order(stages, order, enabled)
        assert _stage_ids(result) == ["architect", "writer", "custom_role"]
        by_id = {s.id: s for s in result}
        # custom_role 与 writer 同层 → input_from = 前序全部（architect）
        assert by_id["custom_role"].input_from == ["architect"]
        assert by_id["writer"].input_from == ["architect"]
        # architect（层 0）→ output_to = 后序全部（writer + custom_role）
        assert sorted(by_id["architect"].output_to) == ["custom_role", "writer"]
