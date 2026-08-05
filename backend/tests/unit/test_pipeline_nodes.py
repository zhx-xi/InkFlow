"""节点增量契约测试 (spec §3.2 / §6.2) — RED 载体。

设计假设（新契约，GREEN 阶段实现）：
1. 节点只返回增量 dict：正常/跳过路径键集合为 {"results"}，失败路径为 {"_abort", "results"}，
   绝不包含 context / stages / llm_client 键 —— 与当前实现（原地 mutate + 返回完整 state）相反。
2. results 为 {stage_id: StageResult(...)}，字段语义：
   - 成功：status=COMPLETED, output=LLM 响应内容, retry_count=成功前失败次数
   - 重试耗尽 required：status=FAILED, error=最后错误, retry_count=max_retries，附带 _abort=True
   - 重试耗尽非 required：status=SKIPPED, error=最后错误, retry_count=max_retries
   - 上游已 abort：status=SKIPPED，不调用 LLM，output/error 为空
3. error 文案（具体字符串）不在断言范围 —— 只断言非空。

当前实现（反模式：返回完整 state）下：
- 用例 1/2/3 的「返回值键集合」断言必然失败（返回值含 context/stages/llm_client）→ RED
- 用例 4 为 operator.or_ 合并语义契约钉住，当前即 PASS，非 RED
"""

import operator

from inkflow.domain.ports.agent_pipeline import (
    AgentRole,
    PipelineContext,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.infrastructure.agent.pipeline_nodes import architect_node


class MockLLMClient:
    """Mock LLM — 返回预设响应（照抄 test_langgraph_pipeline.py L19-36）。"""

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


def _make_context(**kwargs) -> PipelineContext:
    """构造 PipelineContext（默认值 + 覆盖项）。"""
    ctx = {"project_id": "proj-1", "variables": {"genre": "科幻"}}
    ctx.update(kwargs)
    return PipelineContext(**ctx)


def _make_state(llm, *, abort: bool = False, max_retries: int = 1) -> dict:
    """构造节点输入 state（普通 dict，不依赖尚不存在的 PipelineState 类型）。"""
    stage = _make_stage("architect", "架构师", _make_role("architect"), max_retries=max_retries)
    return {
        "context": _make_context(),
        "stages": {"architect": stage},
        "llm_client": llm,
        "_abort": abort,
    }


# ── 正常增量返回 (spec §6.2) ─────────────────────────────────────────


async def test_node_returns_partial_state():
    """正常路径：节点只返回增量 dict（仅含 results 键），不返回完整 state。"""
    llm = MockLLMClient(["架构大纲"])
    state = _make_state(llm)

    ret = await architect_node(state)

    # 核心断言：返回值只含 results 键（当前实现返回完整 state → RED）
    assert set(ret.keys()) == {"results"}
    result = ret["results"]["architect"]
    assert isinstance(result, StageResult)
    assert result.status == StageStatus.COMPLETED
    assert result.output == "架构大纲"
    assert result.retry_count == 0


async def test_node_failure_returns_abort():
    """required 失败路径：重试耗尽 → 返回含 _abort=True + results[stage] FAILED。"""
    llm = MockLLMClient([Exception("llm boom")] * 2)  # max_retries=1 → 2 次尝试全失败
    state = _make_state(llm, max_retries=1)

    ret = await architect_node(state)

    # 失败路径返回 {"_abort": True, "results": {...}}（当前实现返回完整 state → RED）
    assert set(ret.keys()) == {"_abort", "results"}
    assert ret["_abort"] is True
    result = ret["results"]["architect"]
    assert isinstance(result, StageResult)
    assert result.status == StageStatus.FAILED
    assert result.retry_count == 1
    assert result.error  # 错误文案不依赖，只断言非空


async def test_node_skipped_when_aborted():
    """abort 跳过路径：_abort 已置 True → results[stage] SKIPPED，且不调用 LLM。"""
    llm = MockLLMClient()
    state = _make_state(llm, abort=True)

    ret = await architect_node(state)

    # 跳过路径返回 {"results": {...}}（当前实现返回完整 state → RED）
    assert set(ret.keys()) == {"results"}
    result = ret["results"]["architect"]
    assert isinstance(result, StageResult)
    assert result.status == StageStatus.SKIPPED
    # 跳过时不得调用 LLM
    assert llm.call_count == 0


# ── 并行合并语义 (spec §6.2) ─────────────────────────────────────────


def test_results_merge_keeps_both_stages():
    """operator.or_ 合并两个节点增量 → 两个 stage key 并存（reducer 语义前提）。

    契约钉住用例：当前即 PASS，非 RED。LangGraph 对每个顶层 state 键单独应用
    reducer：`Annotated[dict, operator.or_]` 作用于 results 通道的当前累计值与
    节点新增量（两个按 stage_id 索引的内层 dict），即 `or_(累计, 增量)`。
    注意：合并的是内层 results dict（通道值），不是 `{"results": {...}}` 包装
    dict —— 后者顶层键冲突，右操作数会整体覆盖左操作数导致 stage key 丢失
    （已用真实 StateGraph + 并行节点实测：内层合并后两 key 并存）。
    """
    incremental_a = {
        "results": {"a": StageResult(stage_id="a", status=StageStatus.COMPLETED, output="A")}
    }
    incremental_b = {
        "results": {"b": StageResult(stage_id="b", status=StageStatus.COMPLETED, output="B")}
    }

    # 模拟 LangGraph 通道 reducer 调用：or_(当前累计值, 节点增量)
    merged = operator.or_(incremental_a["results"], incremental_b["results"])

    assert set(merged.keys()) == {"a", "b"}
    assert merged["a"].output == "A"
    assert merged["b"].output == "B"
