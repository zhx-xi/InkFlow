"""LangGraph Agent 管线 — StateGraph 引擎实现 AgentPipelineProtocol。

- validate: 空图 / 重复 id / 入口 / 终点 / 非法上游引用 / 环检测
  （F42 #269：入口/终点从「唯一」放宽为「至少一个」——层级并行下第一层多角色
  都是入口、最后一层多角色都是终点；环存在时终点错误信息会误导，仅无环时报告）
- execute: 构建 StateGraph（PipelineState: TypedDict + 嵌套 results dict + reducer）
  按 DAG 边调度；任意 stage.id 经通用节点执行（v1.2 白名单删除）；多 START/END 边
  （F42 #269 §5.3.2）；节点只返回增量（results 键），失败传播与跳过语义见 pipeline_nodes
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from functools import partial
from typing import cast

from langgraph.graph import END, START, StateGraph

from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineError,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.llm_client import LLMClientProtocol
from inkflow.infrastructure.agent import pipeline_nodes
from inkflow.infrastructure.agent.pipeline_nodes import PipelineState


class LangGraphAgentPipeline:
    """LangGraph StateGraph 管线引擎 — 实现 AgentPipelineProtocol。"""

    def __init__(self, llm_client: LLMClientProtocol) -> None:
        self._llm = llm_client

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

    async def execute(
        self,
        stages: Sequence[PipelineStage],
        context: PipelineContext,
    ) -> PipelineResult:
        """执行管线：构建 StateGraph → 顺序执行 → 汇总结果。

        Raises:
            PipelineError: 必需阶段重试耗尽（异常携带 result 属性，含各阶段状态）。
        """
        errors = self.validate(stages)
        if errors:
            raise PipelineError(f"管线配置无效: {'; '.join(errors)}")

        try:
            # TypedDict + 嵌套 results dict：动态 stage key 收进 results（reducer 增量合并）
            workflow = StateGraph(PipelineState)
            for stage in stages:
                # 通用节点绑定 stage_id（v1.2 白名单删除：任意 stage.id 可执行）
                workflow.add_node(stage.id, partial(pipeline_nodes.generic_node, stage_id=stage.id))
            # 多入口（F42 #269 §5.3.2）：每个 input_from 为空的阶段连 START
            for stage in stages:
                if not stage.input_from:
                    workflow.add_edge(START, stage.id)
            for stage in stages:
                for downstream_id in stage.output_to:
                    workflow.add_edge(stage.id, downstream_id)
            # 多终点：每个 output_to 为空的阶段连 END
            for stage in stages:
                if not stage.output_to:
                    workflow.add_edge(stage.id, END)

            app = workflow.compile()
            # 输入仅含三个不可变键；results 通道由首个节点写入创建（reducer 增量合并）
            initial_state: PipelineState = cast(
                PipelineState,
                {
                    "context": context,
                    "stages": {s.id: s for s in stages},
                    "llm_client": self._llm,
                },
            )
            final_state = await app.ainvoke(initial_state)
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
        result = PipelineResult(
            stages=stage_results,
            final_output=results_map.get(
                terminal.id, StageResult(stage_id=terminal.id, status=StageStatus.COMPLETED)
            ).output,
            status=StageStatus.FAILED if failed else StageStatus.COMPLETED,
        )
        if failed:
            error = PipelineError(f"管线执行失败: 阶段 '{failed[0].stage_id}' 重试耗尽")
            error.result = result
            raise error
        return result
