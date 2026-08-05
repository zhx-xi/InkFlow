"""管线节点 — LangGraph StateGraph 的节点函数。

每个节点从 state 中读取阶段定义（``state["stages"][stage_id]``）与共享的
LLM 客户端（``state["llm_client"]``），调用 LLM 后只返回增量
（``{"results": {stage_id: StageResult(...)}}``，失败路径额外含 ``_abort``），
不再返回 / 修改 context / stages / llm_client。

失败语义（spec §2.6）：
- required 阶段重试耗尽 → 标记 failed，置 ``_abort``，下游全部跳过
- 非 required 阶段重试耗尽 → 标记 skipped，下游照常执行（上游输出为空字符串）
"""

from __future__ import annotations

import operator
import re
from typing import Annotated, NotRequired, TypedDict

from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol


class PipelineState(TypedDict):
    """LangGraph 管线状态 — TypedDict + reducer（Issue #87）。"""

    context: PipelineContext
    stages: dict[str, PipelineStage]
    llm_client: LLMClientProtocol
    _abort: NotRequired[bool]
    # 动态 stage key 收进嵌套 dict（增量合并，并行安全）
    results: Annotated[dict[str, StageResult], operator.or_]


_VARIABLE_RE = re.compile(r"\{(\w+)\}")


def _render(template: str, variables: dict[str, str]) -> str:
    """将 {variable} 占位符替换为上下文变量；未知占位符原样保留。"""
    return _VARIABLE_RE.sub(lambda m: variables.get(m.group(1), m.group(0)), template)


def _build_messages(
    state: PipelineState, stage: PipelineStage, upstream_keys: list[str]
) -> list[ChatMessage]:
    """构建 system + user 消息：system 为渲染后的角色 Prompt，user 含上游输出。

    渲染变量 = 上下文变量 + 上游阶段输出（以 ``{stage_id}_output`` 命名），
    因此系统 Prompt 可直接引用 ``{architect_output}`` / ``{writer_output}`` 等占位符。
    上游输出从嵌套 results dict 读取（``state["results"][key].output``）；
    skipped 上游的 output 默认 ""，与旧 ``state.get(f"{key}_output", "")`` 语义等价。
    """
    variables = dict(state["context"].variables)
    for key in upstream_keys:
        variables[f"{key}_output"] = state["results"][key].output
    system_prompt = _render(stage.agent.system_prompt, variables)
    parts = [f"请执行阶段 {stage.id}（{stage.name}）"]
    for key in upstream_keys:
        upstream_output = state["results"][key].output
        parts.append(f"以下是上游阶段 {key} 的输出：\n{upstream_output}")
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content="\n\n".join(parts)),
    ]


async def _call_llm_node(state: PipelineState, stage_id: str, upstream_keys: list[str]) -> dict:
    """通用节点逻辑：重试调用 LLM 并记录阶段状态。

    - 已有必需阶段失败（``state["_abort"]``）→ 直接标记 skipped，不调用 LLM
    - 成功 → completed + output + retry_count
    - 重试耗尽：required → failed + 置 _abort；否则 → skipped
    """
    stage: PipelineStage = state["stages"][stage_id]
    # 已有必需阶段失败 → 直接返回 skipped 增量，不调用 LLM
    if state.get("_abort"):
        return {"results": {stage_id: StageResult(stage_id=stage_id, status=StageStatus.SKIPPED)}}

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
        return {
            "results": {
                stage_id: StageResult(
                    stage_id=stage_id,
                    status=StageStatus.COMPLETED,
                    output=response.content,
                    retry_count=attempt - 1,
                )
            }
        }

    result: dict = {
        "results": {
            stage_id: StageResult(
                stage_id=stage_id,
                status=StageStatus.FAILED if stage.required else StageStatus.SKIPPED,
                error=str(last_error) if last_error else "未知错误",
                retry_count=stage.max_retries,
            )
        }
    }
    if stage.required:
        result["_abort"] = True
    return result


async def architect_node(state: PipelineState) -> dict:
    """架构师节点 — 规划章节结构（无上游输出）。"""
    return await _call_llm_node(state, "architect", [])


async def writer_node(state: PipelineState) -> dict:
    """写手节点 — 基于架构师输出生成章节内容。"""
    return await _call_llm_node(state, "writer", ["architect"])


async def auditor_node(state: PipelineState) -> dict:
    """审阅节点 — 基于写手输出审校文笔质量。"""
    return await _call_llm_node(state, "auditor", ["writer"])


async def reviser_node(state: PipelineState) -> dict:
    """修订节点 — 基于写手输出与审阅意见修订。"""
    return await _call_llm_node(state, "reviser", ["writer", "auditor"])
