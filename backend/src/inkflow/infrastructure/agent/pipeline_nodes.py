"""管线节点 — LangGraph StateGraph 的节点函数。

每个节点从 state 中读取阶段定义（``state["stages"][stage_id]``）与共享的
LLM 客户端（``state["llm_client"]``），调用 LLM 后将输出写回
``state[f"{stage_id}_output"]``，并记录状态 / 重试次数。

失败语义（spec §2.6）：
- required 阶段重试耗尽 → 标记 failed，置 ``state["_abort"]``，下游全部跳过
- 非 required 阶段重试耗尽 → 标记 skipped，下游照常执行（上游输出为空字符串）
"""

from __future__ import annotations

import re

from inkflow.domain.ports.agent_pipeline import PipelineStage, StageStatus
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol

_VARIABLE_RE = re.compile(r"\{(\w+)\}")


def _render(template: str, variables: dict[str, str]) -> str:
    """将 {variable} 占位符替换为上下文变量；未知占位符原样保留。"""
    return _VARIABLE_RE.sub(lambda m: variables.get(m.group(1), m.group(0)), template)


def _build_messages(
    state: dict, stage: PipelineStage, upstream_keys: list[str]
) -> list[ChatMessage]:
    """构建 system + user 消息：system 为渲染后的角色 Prompt，user 含上游输出。

    渲染变量 = 上下文变量 + 上游阶段输出（以 ``{stage_id}_output`` 命名），
    因此系统 Prompt 可直接引用 ``{architect_output}`` / ``{writer_output}`` 等占位符。
    """
    variables = dict(state["context"].variables)
    for key in upstream_keys:
        variables[f"{key}_output"] = state.get(f"{key}_output", "")
    system_prompt = _render(stage.agent.system_prompt, variables)
    parts = [f"请执行阶段 {stage.id}（{stage.name}）"]
    for key in upstream_keys:
        upstream_output = state.get(f"{key}_output", "")
        parts.append(f"以下是上游阶段 {key} 的输出：\n{upstream_output}")
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content="\n\n".join(parts)),
    ]


async def _call_llm_node(state: dict, stage_id: str, upstream_keys: list[str]) -> dict:
    """通用节点逻辑：重试调用 LLM 并记录阶段状态。

    - 已有必需阶段失败（``state["_abort"]``）→ 直接标记 skipped，不调用 LLM
    - 成功 → completed + output + retry_count
    - 重试耗尽：required → failed + 置 _abort；否则 → skipped
    """
    stage: PipelineStage = state["stages"][stage_id]
    # StateGraph(dict) 是单一 __root__ 通道：节点返回的 dict 会整体替换 state，
    # 因此必须返回完整 state（含 context/stages/llm_client）。
    # 线性链每个 super-step 只有一个节点，不存在并发写冲突（并行执行属 Phase 2）。
    if state.get("_abort"):
        state[f"{stage_id}_status"] = StageStatus.SKIPPED.value
        return state

    llm: LLMClientProtocol = state["llm_client"]
    messages = _build_messages(state, stage, upstream_keys)
    last_error: Exception | None = None
    max_attempts = stage.max_retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = await llm.chat(
                messages,
                model=stage.agent.model,
                temperature=stage.agent.temperature,
                max_tokens=stage.agent.max_tokens,
            )
        except Exception as e:
            last_error = e
            continue
        state[f"{stage_id}_output"] = response.content
        state[f"{stage_id}_status"] = StageStatus.COMPLETED.value
        state[f"{stage_id}_retry_count"] = attempt - 1
        return state

    state[f"{stage_id}_retry_count"] = stage.max_retries
    state[f"{stage_id}_error"] = str(last_error) if last_error else "未知错误"
    if stage.required:
        state[f"{stage_id}_status"] = StageStatus.FAILED.value
        state["_abort"] = True
    else:
        state[f"{stage_id}_status"] = StageStatus.SKIPPED.value
    return state


async def architect_node(state: dict) -> dict:
    """架构师节点 — 规划章节结构（无上游输出）。"""
    return await _call_llm_node(state, "architect", [])


async def writer_node(state: dict) -> dict:
    """写手节点 — 基于架构师输出生成章节内容。"""
    return await _call_llm_node(state, "writer", ["architect"])


async def auditor_node(state: dict) -> dict:
    """审阅节点 — 基于写手输出审校文笔质量。"""
    return await _call_llm_node(state, "auditor", ["writer"])


async def reviser_node(state: dict) -> dict:
    """修订节点 — 基于写手输出与审阅意见修订。"""
    return await _call_llm_node(state, "reviser", ["writer", "auditor"])
