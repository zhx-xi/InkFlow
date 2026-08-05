"""LangGraph Agent 管线 — StateGraph 引擎实现 AgentPipelineProtocol。

- validate: 空图 / 重复 id / 多入口 / 多终点 / 非法上游引用 / 环检测
- execute: 构建 StateGraph（PipelineState: TypedDict + 嵌套 results dict + reducer）
  顺序执行；节点只返回增量（results 键），失败传播与跳过语义见 pipeline_nodes
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import cast

from langgraph.graph import END, StateGraph

from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineError,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.llm_client import LLMClientProtocol
from inkflow.infrastructure.agent.pipeline_nodes import (
    PipelineState,
    architect_node,
    auditor_node,
    reviser_node,
    writer_node,
)

_NODE_MAP = {
    "architect": architect_node,
    "writer": writer_node,
    "auditor": auditor_node,
    "reviser": reviser_node,
}


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
        if len(entries) != 1:
            errors.append("管线必须只有一个入口阶段")
        if len(terminals) != 1:
            errors.append("管线必须只有一个终点阶段")

        for s in stages:
            for upstream_id in s.input_from:
                if upstream_id not in ids:
                    errors.append(f"阶段 '{s.id}' 引用了不存在的上游阶段 '{upstream_id}'")

        errors.extend(self._detect_cycle(stages, ids))
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

        # 前置校验阶段类型（在 try 外：PipelineError 直接透传，不被自身 except 捕获）
        for stage in stages:
            if _NODE_MAP.get(stage.id) is None:
                raise PipelineError(f"未知阶段类型: {stage.id}")

        try:
            # TypedDict + 嵌套 results dict：动态 stage key 收进 results（reducer 增量合并）
            workflow = StateGraph(PipelineState)
            for stage in stages:
                workflow.add_node(stage.id, _NODE_MAP[stage.id])

            entry = next(s for s in stages if not s.input_from)
            workflow.set_entry_point(entry.id)
            for stage in stages:
                for downstream_id in stage.output_to:
                    workflow.add_edge(stage.id, downstream_id)
            terminal = next(s for s in stages if not s.output_to)
            workflow.add_edge(terminal.id, END)

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
