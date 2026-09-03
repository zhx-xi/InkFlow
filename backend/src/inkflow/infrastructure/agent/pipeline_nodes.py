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
from inkflow.logging import instrument


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
    """构建 system + user 消息（v1.3 B8 定稿）：system 为渲染后的角色 Prompt，user 含上游输出。

    渲染变量 = 上下文变量 + 上游阶段输出（以 ``{stage_id}_output`` 命名），
    因此系统 Prompt 可直接引用 ``{architect_output}`` / ``{writer_output}`` 等占位符。

    注入键集（v1.3 B8）= upstream_keys（input_from）∪ 该角色 system_prompt 中
    ``_VARIABLE_RE`` 扫描出的全部 ``{xxx_output}`` 占位符键（xxx 部分）：
    - 键在 upstream_keys 且 results 有该键 → 实际输出（``.get`` 防御）
    - 否则 → 空串（未执行角色 / 同层 / 未来层强制空——即使 results 已有同层角色值
      也强制空，保证断言稳定；无 None 字面量注入，评审 O4）
    - user 消息 parts 只列 upstream_keys（既有逻辑不变）
    """
    variables = dict(state["context"].variables)
    # 注入键集 = upstream_keys ∪ prompt 占位符扫描集（{xxx_output} → xxx，去重保序）
    inject_keys: list[str] = list(upstream_keys)
    for match in _VARIABLE_RE.finditer(stage.agent.system_prompt):
        placeholder = match.group(1)
        if placeholder.endswith("_output"):
            role_key = placeholder[: -len("_output")]
            if role_key not in inject_keys:
                inject_keys.append(role_key)
    for key in inject_keys:
        if key in upstream_keys:
            # 实际输出（.get 防御：未执行/跳过的上游无条目 → 空串）
            sr = state["results"].get(key)
            variables[f"{key}_output"] = sr.output if sr is not None else ""
        else:
            # 同层/未来层/未执行引用 → 强制空串（软降级，C3）
            variables[f"{key}_output"] = ""
    system_prompt = _render(stage.agent.system_prompt, variables)
    parts = [f"请执行阶段 {stage.id}（{stage.name}）"]
    for key in upstream_keys:
        sr = state["results"].get(key)
        upstream_output = sr.output if sr is not None else ""
        parts.append(f"以下是上游阶段 {key} 的输出：\n{upstream_output}")
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content="\n\n".join(parts)),
    ]


@instrument(caller_type="agent")
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


@instrument(caller_type="agent")
async def generic_node(state: PipelineState, stage_id: str) -> dict:
    """通用节点：任意 stage.id 执行，upstream_keys 从 stage.input_from 推导（v1.2）。

    v1.1 漏洞修复：4 具名节点硬编码 upstream 与重排拓扑脱节（如 reviser 经重排后
    上游变化仍读旧硬编码）——泛化后上游完全由边定义驱动。
    """
    stage: PipelineStage = state["stages"][stage_id]
    return await _call_llm_node(state, stage_id, stage.input_from)


@instrument(caller_type="agent")
async def architect_node(state: PipelineState) -> dict:
    """兼容别名（v1.2 泛化）：architect 角色经通用节点执行，upstream 由 input_from 推导。"""
    return await generic_node(state, "architect")


@instrument(caller_type="agent")
async def writer_node(state: PipelineState) -> dict:
    """兼容别名（v1.2 泛化）：writer 角色经通用节点执行，upstream 由 input_from 推导。"""
    return await generic_node(state, "writer")


@instrument(caller_type="agent")
async def auditor_node(state: PipelineState) -> dict:
    """兼容别名（v1.2 泛化）：auditor 角色经通用节点执行，upstream 由 input_from 推导。"""
    return await generic_node(state, "auditor")


@instrument(caller_type="agent")
async def reviser_node(state: PipelineState) -> dict:
    """兼容别名（v1.2 泛化）：reviser 角色经通用节点执行，upstream 由 input_from 推导。"""
    return await generic_node(state, "reviser")
