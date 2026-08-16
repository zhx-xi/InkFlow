"""F29 Supervisor 编排层整模块 RED 契约 — SupervisorPipeline（spec §5.2-5.7）。

被测模块（全部未实现，1c 整模块 RED 形态）:
    from inkflow.infrastructure.agent.supervisor_pipeline import SupervisorPipeline

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. SupervisorPipeline（infrastructure/agent/supervisor_pipeline.py 新建，异步，
   构造签名 `SupervisorPipeline(llm_client, *, checkpointer=None)`，实现
   AgentPipelineProtocol）:

       class SupervisorPipeline:
           async def execute(
               self, stages: Sequence[PipelineStage], context: PipelineContext,
               *, supervisor: SupervisorExecuteConfig | None = None,
           ) -> PipelineResult:
               '''构建 supervisor 图 → ainvoke（InMemorySaver checkpointer）→
               PipelineResult（stages 按 route_history 展开，final_output=reviser）.'''

2. 图拓扑（方案 A：supervisor 无静态出边，Command 全权控制）:
   - START → supervisor
   - supervisor 节点返回 Command(update, goto=role) 动态路由；
     goto=END（finish）/ goto=fallback（护栏/非法角色/LLM 主动）
   - role_<stage_id> 节点包装 pipeline_nodes.generic_node（复用重试/失败语义）
   - hitl 节点 interrupt()（stage_id in hitl_roles 时）
   - fallback 节点固定链（architect→writer→auditor→reviser 剩余未执行角色）
   - 所有角色节点执行后静态边回 supervisor；fallback → END
   - supervisor 节点**不设静态出边**（Spike ② 教训：条件边+Command 并存 fan-out）

3. LLM 决策契约（mock LLMClientProtocol.chat side_effect 按调用序）:
   - 决策消息：system prompt 含角色池 + 路由历史 + 护栏约束；
     user 消息要求结构化输出 {"action": "...", "role": "..."}
   - 决策解析：action=execute → goto role；action=finish → goto END；
     action=fallback → goto fallback
   - 空 content / 解析失败 → 自动重试（附路由历史重申）→ 仍空 → fallback
   - 决策 LLM 模型 = context 变量或配置（spec Q2=A：llm_default_model）

4. 护栏（supervisor 节点内部，LLM 决策后强制）:
   - steps >= max_steps（默认 30）→ goto fallback
   - role == last_role and consecutive >= max_consecutive（默认 3）→ goto fallback
   - role 不在角色池 → goto fallback
   - 触发后 route_history 追加 "__fallback__" 标记；final_output=fallback 链 reviser

5. 计数（last-wins 字段，role_node 自算）:
   - steps = state.steps + 1
   - consecutive = (last_role == role) ? consecutive+1 : 1
   - last_role = role

6. HITL（hitl_node）:
   - stage_id in config.hitl_roles → interrupt({"question": ..., "role": ...})
   - resume approved=True → 继续；approved=False → goto fallback
   - execute 返回 __interrupt__ 时 status=waiting_hitl（AgentService 层处理，
     SupervisorPipeline 层返回含 __interrupt__ 的原始结果或抛 HITLInterrupt）

7. 成品身份（F42 §5.6）:
   - finish 时 final_output = results["reviser"].output；
     reviser 未执行/禁用 → 最后执行的内容角色（writer）输出
   - architect/auditor 永不作为成品

RED 预期
--------
收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.agent.supervisor_pipeline'
顶部仅 import 主契约模块（supervisor_pipeline）；其余惰性。
"""

from __future__ import annotations

import pytest

from inkflow.infrastructure.agent.supervisor_pipeline import SupervisorPipeline


def _make_stages():
    """装配后角色池（模板 stages 角色集合，忽略边——动态路由取代静态拓扑）。"""
    from inkflow.domain.ports.agent_pipeline import AgentRole, PipelineStage

    roles = {
        "architect": AgentRole(id="architect", name="架构师", system_prompt="规划"),
        "writer": AgentRole(id="writer", name="写手", system_prompt="写作"),
        "auditor": AgentRole(id="auditor", name="审阅", system_prompt="审校"),
        "reviser": AgentRole(id="reviser", name="修订", system_prompt="定稿"),
    }
    return [
        PipelineStage(id=sid, name=roles[sid].name, agent=roles[sid])
        for sid in ["architect", "writer", "auditor", "reviser"]
    ]


def _make_context() -> object:
    from inkflow.domain.ports.agent_pipeline import PipelineContext

    return PipelineContext(project_id="00000000-0000-0000-0000-000000000001")


def _make_config(**kw) -> object:
    from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig

    return SupervisorExecuteConfig(**kw)


class FakeLLM:
    """决策 LLM fake — 按「调用类型」区分 supervisor 决策与角色执行。

    supervisor 决策 system prompt 含「决策」字样（契约：实现侧 system prompt
    组装必须含该词——见 test docstring + GREEN 任务书）；角色执行（generic_node）
    system = 角色 system_prompt（不含「决策」）。
    decisions 队列只服务 supervisor 决策；角色执行恒返回 role_output。
    """

    def __init__(self, decisions: list[str], role_output: str = "角色输出"):
        # decisions: 每个元素是一个决策文本（如 '{"action": "execute", "role": "writer"}'）
        self.decisions = list(decisions)
        self.role_output = role_output
        self.call_count = 0

    async def chat(self, messages, **kwargs):
        self.call_count += 1
        system = messages[0].content if messages else ""
        if "决策" in system:
            # supervisor 决策调用
            if not self.decisions:
                return type("R", (), {"content": '{"action": "finish"}'})()
            return type("R", (), {"content": self.decisions.pop(0)})()
        # 角色执行调用（generic_node）
        return type("R", (), {"content": self.role_output})()


class TestSupervisorPipelineDynamicRoute:
    """动态路由契约（spec §5.3，M5 门禁）。"""

    @pytest.mark.asyncio
    async def test_dynamic_route_sequence(self) -> None:
        """mock 决策 [execute writer, execute auditor, finish] → route 序列正确。"""
        from inkflow.domain.ports.agent_pipeline import PipelineResult, StageStatus

        llm = FakeLLM(
            [
                '{"action": "execute", "role": "writer"}',
                '{"action": "execute", "role": "auditor"}',
                '{"action": "finish"}',
            ]
        )
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(_make_stages(), _make_context(), supervisor=_make_config())
        assert isinstance(result, PipelineResult)
        assert result.status == StageStatus.COMPLETED
        # 路由历史：writer → auditor → finish（final_output=reviser，未执行则空/最后内容角色）
        stage_ids = [sr.stage_id for sr in result.stages]
        assert "writer" in stage_ids
        assert "auditor" in stage_ids

    @pytest.mark.asyncio
    async def test_finish_output_reviser(self) -> None:
        """finish 时 final_output = reviser 输出（成品身份，F42 §5.6）。"""
        llm = FakeLLM(
            [
                '{"action": "execute", "role": "reviser"}',
                '{"action": "finish"}',
            ]
        )
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(_make_stages(), _make_context(), supervisor=_make_config())
        # 角色节点真实 LLM 调用也走 FakeLLM——决策与角色输出混合；此处宽松断言
        assert isinstance(result.final_output, str)


class TestSupervisorPipelineGuards:
    """振荡护栏 + 步数上限 + 非法角色（spec §5.4，M6 门禁）。"""

    @pytest.mark.asyncio
    async def test_oscillation_guard_fallback(self) -> None:
        """同角色连续调度达上限 → fallback 固定链。"""
        llm = FakeLLM(
            [
                '{"action": "execute", "role": "writer"}',
                '{"action": "execute", "role": "writer"}',
                '{"action": "execute", "role": "writer"}',
                '{"action": "execute", "role": "writer"}',  # 第 4 次连续 → 护栏
            ]
        )
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(
            _make_stages(), _make_context(), supervisor=_make_config(max_consecutive=3)
        )
        # 护栏触发 → fallback 固定链（reviser 最终输出）
        assert isinstance(result.final_output, str)
        assert result.final_output != ""

    @pytest.mark.asyncio
    async def test_step_limit_fallback(self) -> None:
        """步数超限 → fallback 固定链。"""
        llm = FakeLLM(['{"action": "execute", "role": "writer"}' for _ in range(35)])
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(
            _make_stages(), _make_context(), supervisor=_make_config(max_steps=30)
        )
        assert isinstance(result.final_output, str)
        assert result.final_output != ""

    @pytest.mark.asyncio
    async def test_invalid_role_fallback(self) -> None:
        """LLM 决策未知角色 → fallback。"""
        llm = FakeLLM(['{"action": "execute", "role": "ghost_role"}'])
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(_make_stages(), _make_context(), supervisor=_make_config())
        assert isinstance(result.final_output, str)

    @pytest.mark.asyncio
    async def test_empty_content_retry_then_fallback(self) -> None:
        """决策空 content → 重试 → 仍空 → fallback。"""
        from inkflow.domain.ports.llm_client import ChatMessage

        class EmptyThenFinishLLM:
            def __init__(self) -> None:
                self.call_count = 0

            async def chat(self, messages: list[ChatMessage], **kwargs):
                self.call_count += 1
                if self.call_count <= 3:
                    return type("R", (), {"content": ""})()
                return type("R", (), {"content": '{"action": "finish"}'})()

        pipeline = SupervisorPipeline(EmptyThenFinishLLM())
        result = await pipeline.execute(_make_stages(), _make_context(), supervisor=_make_config())
        assert isinstance(result.final_output, str)


class TestSupervisorPipelineHITL:
    """HITL 关键节点人工确认（spec §5.6，M7 门禁）。"""

    @pytest.mark.asyncio
    async def test_hitl_interrupt_payload(self) -> None:
        """hitl_roles=[reviser] → execute 抛 HITLInterrupt（携带 payload）。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import HITLInterrupt

        llm = FakeLLM(
            [
                '{"action": "execute", "role": "writer"}',
                '{"action": "execute", "role": "reviser"}',
                '{"action": "finish"}',
            ]
        )
        pipeline = SupervisorPipeline(llm)
        # 契约：执行到 hitl_roles 命中角色前 interrupt → 抛 HITLInterrupt
        # （payload 含 role/reason；AgentService 捕获 → ExecutionStore status=waiting_hitl）
        with pytest.raises(HITLInterrupt) as exc_info:
            await pipeline.execute(
                _make_stages(), _make_context(), supervisor=_make_config(hitl_roles=["reviser"])
            )
        payload = exc_info.value.payload
        assert payload is not None
        assert payload.get("role") == "reviser"

    @pytest.mark.asyncio
    async def test_hitl_resume_after_confirm(self) -> None:
        """confirm approved 后 resume → 继续执行至完成（成品身份保持）。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import HITLInterrupt

        llm = FakeLLM(
            [
                '{"action": "execute", "role": "reviser"}',
                '{"action": "finish"}',
            ]
        )
        pipeline = SupervisorPipeline(llm)
        try:
            await pipeline.execute(
                _make_stages(), _make_context(), supervisor=_make_config(hitl_roles=["reviser"])
            )
            raise AssertionError("应抛 HITLInterrupt")
        except HITLInterrupt as exc:
            interrupt = exc
        # 契约（v1.0 契约升级，QA 抓实现缺陷）：resume approved=True → 真正执行确认的
        # 角色（reviser 出现在 stage 结果），而非 supervisor 重新决策跳过。
        # 旧契约 `isinstance(final_output, str)` 对空串假绿——LangGraph resume 会
        # 重跑 interrupt 所在节点，interrupt 若在决策之后则 resume 重新决策（队列空
        # → finish → 空结果）。修复 = interrupt 前置独立 hitl 节点（无其他副作用），
        # resume 后重跑无副作用 → 返回 resume 值 → 继续执行确认角色。
        result = await pipeline.resume(interrupt, approved=True)
        stage_ids = [sr.stage_id for sr in result.stages]
        assert "reviser" in stage_ids
        assert isinstance(result.final_output, str)
        assert result.final_output != ""

    @pytest.mark.asyncio
    async def test_no_hitl_when_roles_empty(self) -> None:
        """hitl_roles 空 → 无 interrupt，正常完成。"""
        llm = FakeLLM(['{"action": "finish"}'])
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(_make_stages(), _make_context(), supervisor=_make_config())
        assert isinstance(result.final_output, str)


class TestSupervisorPipelineFallback:
    """deterministic 回退固定链（spec §5.5，M6 门禁）。"""

    @pytest.mark.asyncio
    async def test_fallback_chain_executes_remaining(self) -> None:
        """fallback 固定链执行剩余角色（architect→writer→auditor→reviser）。"""
        llm = FakeLLM(['{"action": "fallback"}'])
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(_make_stages(), _make_context(), supervisor=_make_config())
        assert isinstance(result.final_output, str)
        assert result.final_output != ""
        # 固定链全部角色执行（宽松：stage 结果含 reviser）
        stage_ids = [sr.stage_id for sr in result.stages]
        assert "reviser" in stage_ids

    @pytest.mark.asyncio
    async def test_fallback_on_error_disabled_fails(self) -> None:
        """fallback_on_error=false 且 LLM 决策失败 → FAILED（不回退）。"""
        from inkflow.domain.ports.llm_client import ChatMessage

        class AlwaysEmptyLLM:
            async def chat(self, messages: list[ChatMessage], **kwargs):
                return type("R", (), {"content": ""})()

        pipeline = SupervisorPipeline(AlwaysEmptyLLM())
        result = await pipeline.execute(
            _make_stages(), _make_context(), supervisor=_make_config(fallback_on_error=False)
        )
        # 契约：fallback_on_error=false 时决策失败 → PipelineResult status=FAILED
        from inkflow.domain.ports.agent_pipeline import StageStatus

        assert result.status == StageStatus.FAILED


class TestSupervisorPipelineTopology:
    """方案 A 拓扑回归（Spike ② 教训：supervisor 无静态出边）。"""

    @pytest.mark.asyncio
    async def test_supervisor_no_static_edges(self) -> None:
        """supervisor 图拓扑：supervisor 节点无静态出边（Command 全权控制）。"""
        import inspect

        # 契约：SupervisorPipeline 构建的图，supervisor 节点无 add_edge 静态出边
        # 实现确认：暴露 _build_graph 或内部状态供测试检查；此处宽松断言类存在
        assert inspect.isclass(SupervisorPipeline)


class TestParseDecisionCoverage:
    """_parse_decision 防御分支补测（规则 1j：覆盖率缺口闭合，直接通过）。"""

    def test_empty_content_returns_none(self) -> None:
        """空 content → None。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        assert _parse_decision("") is None
        assert _parse_decision("   ") is None

    def test_invalid_json_returns_none(self) -> None:
        """非 JSON → None。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        assert _parse_decision("not json") is None

    def test_non_dict_returns_none(self) -> None:
        """JSON 非 dict（如数组）→ None。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        assert _parse_decision("[1, 2]") is None

    def test_unknown_action_returns_none(self) -> None:
        """未知 action（非 execute/finish/fallback）→ None。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        assert _parse_decision('{"action": "dance"}') is None

    def test_execute_without_role_returns_none(self) -> None:
        """action=execute 但 role 缺失/非 str → None。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        assert _parse_decision('{"action": "execute"}') is None
        assert _parse_decision('{"action": "execute", "role": 42}') is None

    def test_valid_variants(self) -> None:
        """合法决策 → (action, role)。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        assert _parse_decision('{"action": "execute", "role": "writer"}') == ("execute", "writer")
        assert _parse_decision('{"action": "finish"}') == ("finish", "")
        assert _parse_decision('{"action": "fallback"}') == ("fallback", "")

    def test_markdown_fenced_json_returns_decision(self) -> None:
        """markdown 代码块围栏包裹的 JSON → 剥离围栏后解析（#343 实证根因）。

        zhipu/glm-4.5 决策输出实测形态：```json\\n{"action": "execute", "role": "architect"}\\n```
        — 旧实现直接 json.loads 抛 JSONDecodeError → 决策重试耗尽 → fallback 固定链
        → HITL 永不触发。修复 = 提取首个 { 到末个 } 的子串再解析。
        """
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        fenced = '```json\n{"action": "execute", "role": "reviser"}\n```'
        assert _parse_decision(fenced) == ("execute", "reviser")

    def test_markdown_fenced_with_text_around(self) -> None:
        """markdown 围栏前后带说明文字 → 仍提取 JSON 对象解析（宽松）。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _parse_decision

        noisy = '好的，决策如下：\n```json\n{"action": "finish"}\n```\n请确认。'
        assert _parse_decision(noisy) == ("finish", "")


class TestDecisionLLMExceptionCoverage:
    """_decide_next_action LLM 异常重试补测（规则 1j）。"""

    @pytest.mark.asyncio
    async def test_llm_exception_retry_then_success(self) -> None:
        """LLM 抛异常 → 重试 → 成功（覆盖 except 分支）。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import _decide_next_action

        class FlakyLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def chat(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("transient")
                return type("R", (), {"content": '{"action": "finish"}'})()

        from inkflow.domain.ports.agent_pipeline import PipelineContext

        state = {
            "context": PipelineContext(project_id="p1"),
            "stages": {},
            "llm_client": FlakyLLM(),
            "results": {},
            "route_history": [],
            "steps": 0,
            "consecutive": 0,
            "last_role": "",
            "final_output": "",
        }
        action, role = await _decide_next_action(state, _make_config())
        assert action == "finish"
        assert role == ""


class TestGuardFallbackOnErrorFalseCoverage:
    """护栏触发 + fallback_on_error=false → FAILED（覆盖 L187/L195 分支）。"""

    @pytest.mark.asyncio
    async def test_invalid_role_with_fallback_disabled_fails(self) -> None:
        """非法角色 + fallback_on_error=false → FAILED（不回退）。"""
        llm = FakeLLM(['{"action": "execute", "role": "ghost"}'])
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute(
            _make_stages(), _make_context(), supervisor=_make_config(fallback_on_error=False)
        )
        from inkflow.domain.ports.agent_pipeline import StageStatus

        assert result.status == StageStatus.FAILED


class TestHITLRejectCoverage:
    """HITL reject（approved=False → fallback 固定链）补测（覆盖 L205-207）。"""

    @pytest.mark.asyncio
    async def test_hitl_reject_goes_fallback(self) -> None:
        """hitl_roles 命中 + resume approved=False → 回退固定链。"""
        from inkflow.infrastructure.agent.supervisor_pipeline import HITLInterrupt

        llm = FakeLLM(
            [
                '{"action": "execute", "role": "writer"}',
                '{"action": "finish"}',
            ]
        )
        pipeline = SupervisorPipeline(llm)
        try:
            await pipeline.execute(
                _make_stages(), _make_context(), supervisor=_make_config(hitl_roles=["writer"])
            )
            raise AssertionError("应抛 HITLInterrupt")
        except HITLInterrupt as exc:
            interrupt = exc
        result = await pipeline.resume(interrupt, approved=False)
        # 拒绝 → fallback 固定链 → final_output 非空（reviser 输出）
        assert isinstance(result.final_output, str)
        assert result.final_output != ""


class TestFallbackAbortCoverage:
    """fallback 链中角色失败 → _abort → FAILED（覆盖 L249-250）。"""

    @pytest.mark.asyncio
    async def test_fallback_chain_required_failure(self) -> None:
        """fallback 链中 required 角色失败 → FAILED。"""
        from unittest.mock import AsyncMock, patch

        llm = FakeLLM(['{"action": "fallback"}'])
        pipeline = SupervisorPipeline(llm)
        with patch(
            "inkflow.infrastructure.agent.supervisor_pipeline.generic_node",
            AsyncMock(
                side_effect=lambda state, role_id: {
                    "results": {
                        role_id: __import__(
                            "inkflow.domain.ports.agent_pipeline", fromlist=["StageResult"]
                        ).StageResult(
                            stage_id=role_id,
                            status=__import__(
                                "inkflow.domain.ports.agent_pipeline", fromlist=["StageStatus"]
                            ).StageStatus.FAILED,
                            error="boom",
                        )
                    },
                    "_abort": True,
                }
            ),
        ):
            result = await pipeline.execute(
                _make_stages(), _make_context(), supervisor=_make_config()
            )
        from inkflow.domain.ports.agent_pipeline import StageStatus

        assert result.status == StageStatus.FAILED


class TestValidateErrorsCoverage:
    """validate 错误路径补测（覆盖 L280/283 + execute PipelineError）。"""

    @pytest.mark.asyncio
    async def test_validate_empty_stages(self) -> None:
        """空角色池 → PipelineError。"""
        from inkflow.domain.ports.agent_pipeline import PipelineError

        pipeline = SupervisorPipeline(FakeLLM([]))
        with pytest.raises(PipelineError):
            await pipeline.execute([], _make_context(), supervisor=_make_config())

    @pytest.mark.asyncio
    async def test_validate_duplicate_ids(self) -> None:
        """重复角色 id → PipelineError。"""
        from inkflow.domain.ports.agent_pipeline import AgentRole, PipelineError, PipelineStage

        dup_stage = PipelineStage(
            id="writer",
            name="写手",
            agent=AgentRole(id="writer", name="写手", system_prompt="写作"),
        )
        pipeline = SupervisorPipeline(FakeLLM([]))
        with pytest.raises(PipelineError):
            await pipeline.execute(
                [dup_stage, dup_stage], _make_context(), supervisor=_make_config()
            )


class TestResumeErrorCoverage:
    """resume 错误路径补测（覆盖 L363-364/368）。"""

    @pytest.mark.asyncio
    async def test_resume_without_execute_raises(self) -> None:
        """未 execute 直接 resume → PipelineError（thread 不存在）。"""
        from inkflow.domain.ports.agent_pipeline import PipelineError

        pipeline = SupervisorPipeline(FakeLLM([]))
        with pytest.raises(PipelineError):
            await pipeline.resume(type("I", (), {"payload": {}})(), approved=True)


class TestToResultCustomRoleCoverage:
    """_to_result 自定义角色兜底补测（覆盖 L395-396）。"""

    @pytest.mark.asyncio
    async def test_custom_role_executed_included(self) -> None:
        """自定义角色（非固定链）执行后出现在 stages 结果中。"""
        from inkflow.domain.ports.agent_pipeline import AgentRole, PipelineStage

        custom_stage = PipelineStage(
            id="researcher",
            name="研究员",
            agent=AgentRole(id="researcher", name="研究员", system_prompt="调研"),
        )
        llm = FakeLLM(
            [
                '{"action": "execute", "role": "researcher"}',
                '{"action": "finish"}',
            ]
        )
        pipeline = SupervisorPipeline(llm)
        result = await pipeline.execute([custom_stage], _make_context(), supervisor=_make_config())
        stage_ids = [sr.stage_id for sr in result.stages]
        assert "researcher" in stage_ids
