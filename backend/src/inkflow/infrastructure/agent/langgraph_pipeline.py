"""LangGraph Agent 管线 — StateGraph 引擎实现 AgentPipelineProtocol。

- validate: 空图 / 重复 id / 入口 / 终点 / 非法上游引用 / 环检测
  （F42 #269：入口/终点从「唯一」放宽为「至少一个」——层级并行下第一层多角色
  都是入口、最后一层多角色都是终点；环存在时终点错误信息会误导，仅无环时报告）
- execute: 构建 StateGraph（PipelineState: TypedDict + 嵌套 results dict + reducer）
  按 DAG 边调度；任意 stage.id 经通用节点执行（v1.2 白名单删除）；多 START/END 边
  （F42 #269 §5.3.2）；节点只返回增量（results 键），失败传播与跳过语义见 pipeline_nodes
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime
from functools import partial
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineError,
    PipelineResult,
    PipelineStage,
    PipelineStreamEvent,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.llm_client import LLMClientProtocol
from inkflow.infrastructure.agent import pipeline_nodes
from inkflow.infrastructure.agent.pipeline_nodes import PipelineState
from inkflow.logging import instrument


def _chunk_stream(text: str, size: int = 6) -> list[str]:
    """#681：#642 镜像（chat_agent_service）——完整响应按固定大小切块，模拟流式增量输出。"""
    return [text[i : i + size] for i in range(0, len(text), size)]


class LangGraphAgentPipeline:
    """LangGraph StateGraph 管线引擎 — 实现 AgentPipelineProtocol。"""

    def __init__(self, llm_client: LLMClientProtocol) -> None:
        self._llm = llm_client

    @instrument(caller_type="agent")
    def validate(self, stages: Sequence[PipelineStage]) -> list[str]:
        """验证管线定义合法性：空图 / 重复 id / 入口 / 终点 / 非法引用 / 环。"""
        errors: list[str] = []
        if not stages:
            return ["管线至少需要一个阶段"]

        ids = {s.id for s in stages}
        if len(ids) != len(stages):
            errors.append("阶段 id 不能重复")

        entries = [s for s in stages if not s.input_from]
        terminals = [s for s in stages if not s.output_to]
        if not entries:
            errors.append("管线必须至少有一个入口阶段")
        cycle_errors = self._detect_cycle(stages, ids)
        # 环存在时「无终点」是环的必然结果，报终点错误会误导（test_validate_no_terminal）；
        # 无环时缺失终点才是真实配置问题（如 output_to 引用不存在阶段，C7）
        if not terminals and not cycle_errors:
            errors.append("管线必须至少有一个终点阶段")

        for s in stages:
            for upstream_id in s.input_from:
                if upstream_id not in ids:
                    errors.append(f"阶段 '{s.id}' 引用了不存在的上游阶段 '{upstream_id}'")

        errors.extend(cycle_errors)
        return errors

    @staticmethod
    def _detect_cycle(stages: Sequence[PipelineStage], ids: set[str]) -> list[str]:
        """Kahn 拓扑排序检测环：存在环 → 返回 1 条错误。"""
        indegree = {sid: 0 for sid in ids}
        for s in stages:
            for downstream_id in s.output_to:
                if downstream_id in indegree:
                    indegree[downstream_id] += 1
        by_id = {s.id: s for s in stages}
        queue = deque(sid for sid, d in indegree.items() if d == 0)
        processed = 0
        while queue:
            sid = queue.popleft()
            processed += 1
            for downstream_id in by_id[sid].output_to:
                if downstream_id in indegree:
                    indegree[downstream_id] -= 1
                    if indegree[downstream_id] == 0:
                        queue.append(downstream_id)
        if processed != len(ids):
            return ["管线存在循环依赖"]
        return []

    @instrument(caller_type="agent")
    async def execute(
        self,
        stages: Sequence[PipelineStage],
        context: PipelineContext,
        conditional_edges: Sequence[tuple[str, str]] | None = None,
    ) -> PipelineResult:
        """执行管线：构建 StateGraph → 顺序执行 → 汇总结果。

        conditional_edges（F46 #270，spec §5.3.2）：条件边 (from, to) 列表——跳过
        对应静态 add_edge，改用 add_conditional_edges 构建 gate 路由（通过 → 目标，
        不通过 → END，跳过目标及其下游）。

        Raises:
            PipelineError: 必需阶段重试耗尽（异常携带 result 属性，含各阶段状态）。
        """
        errors = self.validate(stages)
        if errors:
            raise PipelineError(f"管线配置无效: {'; '.join(errors)}")

        try:
            app = self._compile(stages, conditional_edges)
            final_state = await app.ainvoke(self._build_initial_state(stages, context))
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(f"管线执行失败: {e}") from e

        results_map: dict[str, StageResult] = final_state.get("results", {})
        stage_results = [
            results_map.get(
                stage.id,
                StageResult(stage_id=stage.id, status=StageStatus.COMPLETED),
            )
            for stage in stages
        ]
        failed = [sr for sr in stage_results if sr.status == StageStatus.FAILED]
        # 多终点取 stages 列表中靠后的终点（保持既有 final_output = 终点输出语义）
        terminals = [s for s in stages if not s.output_to]
        terminal = terminals[-1] if terminals else stages[-1]
        terminal_result = results_map.get(
            terminal.id, StageResult(stage_id=terminal.id, status=StageStatus.COMPLETED)
        )
        # F46 #270（spec §5.3.3 成品身份回退）：终点被条件边跳过（results 无该终点条目）
        # → final_output 回退最后执行的**内容角色**（writer）输出（architect/auditor 永不作成品）
        final_output = terminal_result.output
        if terminal.id not in results_map:
            content_candidates = [
                s
                for s in reversed(stages)
                if s.id in results_map
                and results_map[s.id].status == StageStatus.COMPLETED
                and s.id not in ("architect", "auditor")
            ]
            if content_candidates:
                final_output = results_map[content_candidates[0].id].output
        # F47 #379（spec §2.1）：执行完成后按 stages 结果组装 trace 条目（每 stage 一条，
        # type=stage，reasoning=AIMessage content，output 前 500 字符截断）。
        trace_ts = datetime.now(UTC).isoformat()
        trace = [
            {
                "node": sr.stage_id,
                "type": "stage",
                "reasoning": sr.output,
                "tool_calls": [],
                "output": sr.output[:500],
                "duration_ms": sr.duration_ms,
                "ts": trace_ts,
            }
            for sr in stage_results
        ]
        result = PipelineResult(
            stages=stage_results,
            final_output=final_output,
            status=StageStatus.FAILED if failed else StageStatus.COMPLETED,
            trace=trace,
        )
        if failed:
            error = PipelineError(f"管线执行失败: 阶段 '{failed[0].stage_id}' 重试耗尽")
            error.result = result
            raise error
        return result

    def _compile(
        self,
        stages: Sequence[PipelineStage],
        conditional_edges: Sequence[tuple[str, str]] | None = None,
    ) -> CompiledStateGraph:
        """构建并编译 StateGraph（execute/stream 共用装配，spec §5.3.2）。"""
        # TypedDict + 嵌套 results dict：动态 stage key 收进 results（reducer 增量合并）
        workflow = StateGraph(PipelineState)
        for stage in stages:
            # 通用节点绑定 stage_id（v1.2 白名单删除：任意 stage.id 可执行）
            workflow.add_node(stage.id, partial(pipeline_nodes.generic_node, stage_id=stage.id))
        # 多入口（F42 #269 §5.3.2）：每个 input_from 为空的阶段连 START
        for stage in stages:
            if not stage.input_from:
                workflow.add_edge(START, stage.id)
        # 静态边：跳过条件边（条件边改用 add_conditional_edges 单独构建，spec §5.3.2）
        conditional_pairs = {tuple(p) for p in (conditional_edges or [])}
        for stage in stages:
            for downstream_id in stage.output_to:
                if (stage.id, downstream_id) in conditional_pairs:
                    continue  # 条件边：不 add_edge，下方 add_conditional_edges 处理
                workflow.add_edge(stage.id, downstream_id)
        # 条件边：gate 函数读上游 output，PASS → 目标，否则 → END（跳过目标及其下游）
        for from_id, to_id in conditional_pairs:
            workflow.add_conditional_edges(
                from_id, _make_gate(from_id, to_id), {to_id: to_id, END: END}
            )
        # 多终点：每个 output_to 为空的阶段连 END
        for stage in stages:
            if not stage.output_to:
                workflow.add_edge(stage.id, END)
        return workflow.compile()

    def _build_initial_state(
        self, stages: Sequence[PipelineStage], context: PipelineContext
    ) -> PipelineState:
        """组装图初始状态（execute/stream 共用：三个不可变键）。"""
        return cast(
            PipelineState,
            {
                "context": context,
                "stages": {s.id: s for s in stages},
                "llm_client": self._llm,
            },
        )

    @instrument(caller_type="agent")
    async def stream(
        self,
        stages: Sequence[PipelineStage],
        context: PipelineContext,
        conditional_edges: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncGenerator[PipelineStreamEvent, None]:
        """#681：astream_events v2 流式执行管线 → 帧序列（token delta + 阶段切换帧）。

        - 装配与 execute 相同（_compile + _build_initial_state）
        - on_chat_model_stream（run_type=llm）→ token 级 delta 帧
        - on_chat_model_end（run_type=llm，完整 output）→ 非流式时 _chunk_stream 切块 delta
        - metadata['langgraph_node'] 变化 → type='stage' 帧（每阶段进入仅一次）
        - 流结束 → done(final_output=最后非空 content, intent='content')
        - 异常（重试耗尽等）→ done(error=...)，由端点转 error 帧
        """
        errors = self.validate(stages)
        if errors:
            raise PipelineError(f"管线配置无效: {'; '.join(errors)}")
        app = self._compile(stages, conditional_edges)
        final_output = ""
        stage_name_map = {s.id: s.name for s in stages}
        current_stage: str | None = None
        streamed_any = False
        try:
            async for ev in app.astream_events(
                self._build_initial_state(stages, context), version="v2"
            ):
                ev_dict = cast(dict[str, Any], ev)
                node = (ev_dict.get("metadata") or {}).get("langgraph_node")
                if (
                    ev_dict.get("event") == "on_chat_model_stream"
                    and ev_dict.get("run_type") == "llm"
                ):
                    chunk = (ev_dict.get("data") or {}).get("chunk")
                    content = getattr(chunk, "content", "") or ""
                    if content:
                        if node and node != current_stage:
                            current_stage = node
                            yield PipelineStreamEvent(
                                type="stage",
                                stage_id=node,
                                stage_name=stage_name_map.get(node, node),
                            )
                        final_output = content
                        yield PipelineStreamEvent(type="delta", delta=content)
                        streamed_any = True
                elif (
                    ev_dict.get("event") == "on_chat_model_end" and ev_dict.get("run_type") == "llm"
                ):
                    output = (ev_dict.get("data") or {}).get("output")
                    content = getattr(output, "content", "") or ""
                    if content:
                        if node and node != current_stage:
                            current_stage = node
                            yield PipelineStreamEvent(
                                type="stage",
                                stage_id=node,
                                stage_name=stage_name_map.get(node, node),
                            )
                        final_output = content
                        if not streamed_any:
                            # 非流式完整响应 → _chunk_stream 切块模拟 token 级流
                            for c in _chunk_stream(content):
                                await asyncio.sleep(0.05)
                                yield PipelineStreamEvent(type="delta", delta=c)
                        else:
                            yield PipelineStreamEvent(type="delta", delta=content)
                        streamed_any = True
            yield PipelineStreamEvent(
                type="done", done=True, final_output=final_output, intent="content"
            )
        except Exception as e:
            yield PipelineStreamEvent(type="done", done=True, error=str(e))


# F46 #270 gate 通过标记（spec §5.3.3，确定性关键词匹配，不区分大小写）
_PASS_MARKERS = ("通过", "pass", "通过审核", "合格")


def _make_gate(from_id: str, to_id: str):
    """conditional 边 gate：from 输出含通过标记（且非「不通过」否定）→ to_id；
    否则 → END（跳过目标及其下游）。"""

    def gate(state: PipelineState) -> str:
        sr = state["results"].get(from_id)
        text = (sr.output if sr else "").lower()
        # 关键词匹配须排除「不通过」否定（否则子串命中「通过」误判放行，spec §5.3.3）
        passed = "不通过" not in text and any(m in text for m in _PASS_MARKERS)
        return to_id if passed else END

    return gate
