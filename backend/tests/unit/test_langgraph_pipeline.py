"""LangGraph 管线引擎测试 (spec §9.5) — Mock LLMClient，不联网。

覆盖顺序执行 / 输出传递 / validate 校验 / 重试 / 跳过 / 失败传播。
"""

import pytest

from inkflow.domain.ports.agent_pipeline import (
    AgentRole,
    PipelineContext,
    PipelineError,
    PipelineStage,
    StageStatus,
)
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline


class MockLLMClient:
    """Mock LLM — 返回预设响应。"""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.calls = []  # 记录每次调用的 messages/model/temperature

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None, **kwargs):
        self.calls.append({"messages": messages, "model": model, "temperature": temperature})
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            if isinstance(resp, Exception):
                raise resp
            return ChatResponse(content=resp, model=model or "mock", finish_reason="stop")
        self.call_count += 1
        return ChatResponse(content=f"mock_response_{self.call_count}", model=model or "mock")


# ── 构造辅助 ──────────────────────────────────────────────────────────


def _make_role(role_id: str = "architect", **kwargs) -> AgentRole:
    """构造一个合法的 AgentRole（默认值 + 覆盖项）。"""
    role = {"id": role_id, "name": "架构师", "system_prompt": "你是资深{genre}小说架构师"}
    role.update(kwargs)
    return AgentRole(**role)


def _make_stage(stage_id: str, name: str, role: AgentRole, **kwargs) -> PipelineStage:
    """构造一个 PipelineStage（默认值 + 覆盖项）。"""
    stage = {"id": stage_id, "name": name, "agent": role}
    stage.update(kwargs)
    return PipelineStage(**stage)


def _builtin_chain() -> list[PipelineStage]:
    """builtin:write_chapter 4 阶段链（spec §4）:
    architect → writer → auditor → reviser 线性执行；reviser 通过共享 state
    同时接收 writer + auditor 输出（spec: 并行执行属 Phase 2，不在范围）。
    """
    architect = _make_stage(
        "architect", "架构师", _make_role("architect"), input_from=[], output_to=["writer"]
    )
    writer = _make_stage(
        "writer",
        "写手",
        _make_role("writer", name="写手"),
        input_from=["architect"],
        output_to=["auditor"],
    )
    auditor = _make_stage(
        "auditor",
        "审阅",
        _make_role("auditor", name="审阅"),
        input_from=["writer"],
        output_to=["reviser"],
    )
    reviser = _make_stage(
        "reviser",
        "修订",
        _make_role("reviser", name="修订"),
        input_from=["writer", "auditor"],
        output_to=[],
    )
    return [architect, writer, auditor, reviser]


def _make_context(**kwargs) -> PipelineContext:
    ctx = {"project_id": "proj-1", "variables": {"genre": "科幻"}}
    ctx.update(kwargs)
    return PipelineContext(**ctx)


# ── 顺序执行 (§9.5) ──────────────────────────────────────────────────


async def test_chain_executes_in_order():
    """architect→writer→auditor→reviser 顺序执行，输出逐级传递。"""
    llm = MockLLMClient(["架构大纲", "章节正文", "审阅意见", "修订稿"])
    pipeline = LangGraphAgentPipeline(llm)

    result = await pipeline.execute(_builtin_chain(), _make_context())

    assert [s.status for s in result.stages] == [StageStatus.COMPLETED] * 4
    assert [s.output for s in result.stages] == ["架构大纲", "章节正文", "审阅意见", "修订稿"]
    assert result.final_output == "修订稿"
    assert result.status == StageStatus.COMPLETED
    assert llm.call_count == 4
    # 调用顺序: architect → writer → auditor → reviser
    for i, stage_id in enumerate(["architect", "writer", "auditor", "reviser"]):
        user_msg = llm.calls[i]["messages"][1].content
        assert stage_id in user_msg
    # 节点将 AgentRole 的 model/temperature 透传给 LLM
    assert llm.calls[0]["model"] == "openai/gpt-4o"
    # spec §9.2.3 温度链拍板：AgentRole.temperature 默认 None（跟随默认，装配层决定最终值）
    assert llm.calls[0]["temperature"] is None


async def test_output_passes_downstream():
    """下游节点收到上游阶段输出：writer←architect，reviser←writer+auditor。"""
    llm = MockLLMClient(["architect_out", "writer_out", "auditor_out", "reviser_out"])
    pipeline = LangGraphAgentPipeline(llm)

    await pipeline.execute(_builtin_chain(), _make_context())

    writer_user = llm.calls[1]["messages"][1].content
    auditor_user = llm.calls[2]["messages"][1].content
    reviser_user = llm.calls[3]["messages"][1].content
    assert "architect_out" in writer_user
    assert "writer_out" in auditor_user
    assert "writer_out" in reviser_user
    assert "auditor_out" in reviser_user


# ── validate (§9.2 / §9.5) ───────────────────────────────────────────


def test_validate_valid_chain():
    """合法 4 阶段链 → 空错误列表。"""
    pipeline = LangGraphAgentPipeline(MockLLMClient())
    assert pipeline.validate(_builtin_chain()) == []


def test_validate_empty_stages():
    """空阶段列表 → 1 条错误。"""
    pipeline = LangGraphAgentPipeline(MockLLMClient())
    errors = pipeline.validate([])
    assert len(errors) == 1
    assert "至少需要一个阶段" in errors[0]


def test_validate_unknown_upstream():
    """input_from 引用不存在的阶段 → 错误。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b"]),
        _make_stage("b", "B", _make_role("writer"), input_from=["missing"], output_to=[]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    assert any("missing" in e for e in errors)


def test_validate_multiple_entries():
    """2 个 input_from=[] 阶段 → 放宽后合法（多入口，F42 #269 §5.3.2 层级并行）。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b"]),
        _make_stage("b", "B", _make_role("writer"), input_from=[], output_to=[]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    assert errors == []


def test_validate_no_terminal():
    """a→b→a 无 output_to=[] 阶段 → 放宽后「终点」错误消失，环检测仍报「循环」。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b"]),
        _make_stage("b", "B", _make_role("writer"), input_from=["a"], output_to=["a"]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    assert any("循环" in e for e in errors)
    assert not any("终点" in e for e in errors)


def test_validate_cycle():
    """a→b→a 循环依赖 → 循环错误。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b"]),
        _make_stage("b", "B", _make_role("writer"), input_from=["a"], output_to=["a"]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    assert any("循环" in e for e in errors)


# ── 重试与跳过 (§9.5 / spec §2.6) ────────────────────────────────────


async def test_stage_retry_then_success():
    """第 1 次失败 → retry_count=1 → completed。"""
    llm = MockLLMClient([Exception("llm boom"), "大纲成功"])
    stages = _builtin_chain()
    stages[0].max_retries = 1

    result = await LangGraphAgentPipeline(llm).execute(stages, _make_context())

    assert result.stages[0].status == StageStatus.COMPLETED
    assert result.stages[0].retry_count == 1
    assert result.stages[0].output == "大纲成功"
    assert result.status == StageStatus.COMPLETED


async def test_stage_fail_exhausts_retries():
    """3 次重试耗尽 → failed → PipelineError。"""
    llm = MockLLMClient([Exception("llm boom")] * 10)
    stages = _builtin_chain()
    stages[0].max_retries = 3

    with pytest.raises(PipelineError) as exc_info:
        await LangGraphAgentPipeline(llm).execute(stages, _make_context())

    result = exc_info.value.result
    assert result.stages[0].status == StageStatus.FAILED
    assert result.stages[0].retry_count == 3
    assert result.status == StageStatus.FAILED


async def test_non_required_stage_skipped():
    """required=False 失败 → skipped，下游继续执行。"""
    # architect 的 2 次尝试（max_retries=1）失败，其后各阶段成功
    llm = MockLLMClient([Exception("llm boom")] * 2 + ["writer_ok", "auditor_ok", "reviser_ok"])
    stages = _builtin_chain()
    stages[0].max_retries = 1
    stages[0].required = False

    result = await LangGraphAgentPipeline(llm).execute(stages, _make_context())

    assert result.stages[0].status == StageStatus.SKIPPED
    assert result.stages[1].status == StageStatus.COMPLETED
    assert result.stages[2].status == StageStatus.COMPLETED
    assert result.stages[3].status == StageStatus.COMPLETED
    assert result.final_output == "reviser_ok"


async def test_required_stage_downstream_skipped():
    """required=True 失败 → 下游全部 skipped。"""
    llm = MockLLMClient([Exception("llm boom")] * 10)
    stages = _builtin_chain()
    stages[0].max_retries = 1

    with pytest.raises(PipelineError) as exc_info:
        await LangGraphAgentPipeline(llm).execute(stages, _make_context())

    result = exc_info.value.result
    assert [s.status for s in result.stages] == [
        StageStatus.FAILED,
        StageStatus.SKIPPED,
        StageStatus.SKIPPED,
        StageStatus.SKIPPED,
    ]
    # 下游阶段未调用 LLM（仅 architect 的 1 次尝试 + 1 次重试）
    assert llm.call_count == 2


async def test_pipeline_error_message():
    """PipelineError 消息包含失败阶段信息。"""
    llm = MockLLMClient([Exception("llm boom")] * 10)
    stages = _builtin_chain()
    stages[0].max_retries = 1

    with pytest.raises(PipelineError) as exc_info:
        await LangGraphAgentPipeline(llm).execute(stages, _make_context())

    assert "architect" in str(exc_info.value)


# ── Phase 3 覆盖率补齐（#104）──────────────────────────────────


def test_validate_duplicate_stage_ids():
    """两个阶段共用同一 id → 「阶段 id 不能重复」错误。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=[]),
        _make_stage("a", "A2", _make_role("writer"), input_from=[], output_to=[]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    assert any("重复" in e for e in errors)


def test_validate_unknown_downstream_reference():
    """output_to 引用不存在的阶段 → 环检测两处 indegree 分支均容忍（不报循环）。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b"]),
        _make_stage("b", "B", _make_role("writer"), input_from=["a"], output_to=["ghost"]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    # ghost 不在 ids 中：入度统计与拓扑遍历均跳过它，只报缺少终点
    assert any("终点" in e for e in errors)
    assert not any("循环" in e for e in errors)


def test_validate_indegree_decrement_not_zero():
    """c 有两个上游时，处理第一个上游后 indegree 2→1（非 0 分支）。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b", "c"]),
        _make_stage("b", "B", _make_role("writer"), input_from=["a"], output_to=["c"]),
        _make_stage("c", "C", _make_role("auditor"), input_from=["a", "b"], output_to=[]),
    ]
    assert LangGraphAgentPipeline(MockLLMClient()).validate(stages) == []


async def test_execute_multiple_entries_succeeds():
    """2 个独立无依赖阶段（多入口/多终点）→ 放宽后合法，执行成功（F42 #269 §5.3.2）。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=[]),
        _make_stage("b", "B", _make_role("writer"), input_from=[], output_to=[]),
    ]
    result = await LangGraphAgentPipeline(MockLLMClient()).execute(stages, _make_context())
    assert [s.status for s in result.stages] == [StageStatus.COMPLETED, StageStatus.COMPLETED]


async def test_execute_arbitrary_stage_id_succeeds():
    """任意 stage.id（非内置 4）→ 通用节点执行成功（v1.2 白名单删除）。"""
    stages = [
        _make_stage("custom_role", "自定义", _make_role("architect"), input_from=[], output_to=[]),
    ]
    result = await LangGraphAgentPipeline(MockLLMClient()).execute(stages, _make_context())
    assert result.stages[0].status == StageStatus.COMPLETED
    assert result.final_output == "mock_response_1"


async def test_execute_node_pipeline_error_propagates(monkeypatch):
    """节点内抛 PipelineError → except PipelineError 原样透传（不包装）。

    F42 #269 R1：monkeypatch 目标从 _NODE_MAP 改通用节点 generic_node
    （pipeline_nodes.py 具名节点删除，任意 stage.id 经 generic_node 执行）。
    """

    async def _boom_node(state, stage_id):
        raise PipelineError("node exploded")

    stages = [
        _make_stage("architect", "A", _make_role("architect"), input_from=[], output_to=["writer"]),
        _make_stage("writer", "W", _make_role("writer"), input_from=["architect"], output_to=[]),
    ]
    monkeypatch.setattr(
        "inkflow.infrastructure.agent.pipeline_nodes.generic_node",
        _boom_node,
    )
    with pytest.raises(PipelineError, match="node exploded"):
        await LangGraphAgentPipeline(MockLLMClient()).execute(stages, _make_context())


async def test_execute_node_generic_exception_wrapped(monkeypatch):
    """节点内抛非 PipelineError 异常 → 包装为 PipelineError（管线执行失败），保留 cause。"""

    async def _crash_node(state, stage_id):
        raise RuntimeError("node crashed")

    stages = [
        _make_stage("architect", "A", _make_role("architect"), input_from=[], output_to=["writer"]),
        _make_stage("writer", "W", _make_role("writer"), input_from=["architect"], output_to=[]),
    ]
    monkeypatch.setattr(
        "inkflow.infrastructure.agent.pipeline_nodes.generic_node",
        _crash_node,
    )
    with pytest.raises(PipelineError, match="管线执行失败") as exc_info:
        await LangGraphAgentPipeline(MockLLMClient()).execute(stages, _make_context())
    assert isinstance(exc_info.value.__cause__, RuntimeError)


# ── F42 #269 层级拓扑 / 并行层 / 空注入（spec §5.3.2/§5.3.3 + §13 M4/M5）─────────


class RoleMapLLMClient:
    """per-role 响应表 mock（v1.3 R2 并行断言契约）：按 stage.id 分发响应，
    不按调用序——「层间顺序确定」断言 = 调用序号单调（层 2 全部 > 层 1 全部）。"""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.calls: list[dict] = []  # 每次调用的 stage 标识从 user 消息提取

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None, **kwargs):
        user_content = messages[1].content if len(messages) > 1 else ""
        # 从 user 消息首行提取阶段 id（pipeline_nodes L61 形态「请执行阶段 {id}（...）」）
        import re

        m = re.search(r"请执行阶段 (\w+)", user_content)
        stage_id = m.group(1) if m else "unknown"
        self.calls.append(
            {"stage": stage_id, "model": model, "temperature": temperature, "messages": messages}
        )
        from inkflow.domain.ports.llm_client import ChatResponse

        return ChatResponse(
            content=self.responses.get(stage_id, f"resp_{stage_id}"),
            model=model or "mock",
            finish_reason="stop",
        )


def _parallel_chain() -> list[PipelineStage]:
    """层级并行拓扑（spec M5 场景）：architect → writer/auditor 并行 → reviser 全连接。"""
    architect = _make_stage(
        "architect",
        "架构师",
        _make_role("architect"),
        input_from=[],
        output_to=["writer", "auditor"],
    )
    writer = _make_stage(
        "writer",
        "写手",
        _make_role("writer", name="写手", system_prompt="基于 {architect_output} 写作"),
        input_from=["architect"],
        output_to=["reviser"],
    )
    auditor = _make_stage(
        "auditor",
        "审阅",
        _make_role("auditor", name="审阅", system_prompt="审阅 {writer_output}"),
        input_from=["architect"],
        output_to=["reviser"],
    )
    reviser = _make_stage(
        "reviser",
        "修订",
        _make_role(
            "reviser",
            name="修订",
            system_prompt="修订 {writer_output} 和 {auditor_output}",
        ),
        input_from=["architect", "writer", "auditor"],
        output_to=[],
    )
    return [architect, writer, auditor, reviser]


async def test_validate_hierarchical_topology():
    """层级并行拓扑（多入口/多终点 + 全连接边）→ validate 通过（M4）。"""
    pipeline = LangGraphAgentPipeline(MockLLMClient())
    assert pipeline.validate(_parallel_chain()) == []


async def test_execute_parallel_layer_order_monotonic():
    """并行层执行：per-role 响应表 mock → 层间调用序号单调（层 2 全部 > 层 1 全部）。
    层内（writer/auditor）不承诺顺序（v1.3 R2 断言契约）。"""
    llm = RoleMapLLMClient(
        {"architect": "大纲", "writer": "正文", "auditor": "审阅意见", "reviser": "修订稿"}
    )
    result = await LangGraphAgentPipeline(llm).execute(_parallel_chain(), _make_context())

    # 全部角色均被执行
    stages_called = {c["stage"] for c in llm.calls}
    assert stages_called == {"architect", "writer", "auditor", "reviser"}
    # 层间顺序确定：architect（层 0）调用序号 < writer/auditor（层 1）< reviser（层 2）
    seq = {c["stage"]: i for i, c in enumerate(llm.calls)}
    assert seq["architect"] < seq["writer"]
    assert seq["architect"] < seq["auditor"]
    assert seq["writer"] < seq["reviser"]
    assert seq["auditor"] < seq["reviser"]
    # 成品 = 终点输出
    assert result.final_output == "修订稿"


async def test_execute_parallel_layer_shared_input():
    """并行层共享前序输出：writer/auditor 都收到 architect 输出。"""
    llm = RoleMapLLMClient(
        {"architect": "大纲内容", "writer": "正文", "auditor": "审阅意见", "reviser": "修订稿"}
    )
    await LangGraphAgentPipeline(llm).execute(_parallel_chain(), _make_context())

    for call in llm.calls:
        if call["stage"] in ("writer", "auditor"):
            assert "大纲内容" in call["messages"][1].content  # 前序层输出注入
    reviser_call = next(c for c in llm.calls if c["stage"] == "reviser")
    assert "正文" in reviser_call["messages"][1].content
    assert "审阅意见" in reviser_call["messages"][1].content


async def test_execute_missing_upstream_empty_injection():
    """未执行角色空注入（§5.3.3 .get 防御）：writer 不在管线（results 无条目）→
    auditor 引用 {writer_output} → 空串（无 None 字面量，评审 O4）。"""
    # 只有 architect → auditor 两阶段；auditor prompt 引用 writer_output（未执行）
    architect = _make_stage(
        "architect", "架构师", _make_role("architect"), input_from=[], output_to=["auditor"]
    )
    auditor = _make_stage(
        "auditor",
        "审阅",
        _make_role("auditor", name="审阅", system_prompt="引用 {writer_output} 检查"),
        input_from=["architect"],
        output_to=[],
    )
    llm = MockLLMClient(["大纲", "审阅意见"])
    await LangGraphAgentPipeline(llm).execute([architect, auditor], _make_context())

    auditor_user = llm.calls[1]["messages"][1].content
    assert "None" not in auditor_user  # 空注入非 None 字面量
    auditor_system = llm.calls[1]["messages"][0].content
    assert "None" not in auditor_system
    assert "{writer_output}" not in auditor_system  # 占位符被渲染（空串）


async def test_execute_same_layer_reference_forced_empty():
    """同层不可见硬语义（v1.3 B8）：writer/auditor 同层且 auditor 引用 {writer_output}
    → 即使 writer 调度先执行完成也强制注入空串（断言稳定，防 flaky）。"""
    writer = _make_stage(
        "writer",
        "写手",
        _make_role("writer", name="写手", system_prompt="独立写作"),
        input_from=[],
        output_to=[],
    )
    auditor = _make_stage(
        "auditor",
        "审阅",
        _make_role("auditor", name="审阅", system_prompt="审阅 {writer_output}"),
        input_from=[],
        output_to=[],
    )
    llm = RoleMapLLMClient({"writer": "正文内容", "auditor": "审阅意见"})
    await LangGraphAgentPipeline(llm).execute([writer, auditor], _make_context())

    auditor_call = next(c for c in llm.calls if c["stage"] == "auditor")
    auditor_system = auditor_call["messages"][0].content
    # 同层引用强制空：即使 writer 已执行（正文内容在 results），auditor 仍收空串
    assert "{writer_output}" not in auditor_system
    assert "正文内容" not in auditor_system
    assert "None" not in auditor_system
    # user 消息不得包含同层上游段（input_from 不含同层）
    auditor_user = auditor_call["messages"][1].content
    assert "正文内容" not in auditor_user
