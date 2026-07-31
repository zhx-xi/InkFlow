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
    assert llm.calls[0]["temperature"] == 0.7


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
    """2 个 input_from=[] 阶段 → 入口错误。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b"]),
        _make_stage("b", "B", _make_role("writer"), input_from=[], output_to=[]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    assert any("入口" in e for e in errors)


def test_validate_no_terminal():
    """无 output_to=[] 阶段 → 终点错误。"""
    stages = [
        _make_stage("a", "A", _make_role("architect"), input_from=[], output_to=["b"]),
        _make_stage("b", "B", _make_role("writer"), input_from=["a"], output_to=["a"]),
    ]
    errors = LangGraphAgentPipeline(MockLLMClient()).validate(stages)
    assert any("终点" in e for e in errors)


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
