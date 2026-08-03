"""LangGraph Agent 管线 — StateGraph 引擎实现 AgentPipelineProtocol。

- validate: 空图 / 重复 id / 多入口 / 多终点 / 非法上游引用 / 环检测
- execute: 构建 StateGraph 顺序执行，失败传播与跳过语义见 pipeline_nodes
"""

from __future__ import annotations

from collections.abc import Sequence

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
        queue = [sid for sid, d in indegree.items() if d == 0]
        processed = 0
        while queue:
            sid = queue.pop(0)
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
            # state 含动态的 {stage_id}_output/_status 等 key，无法用 TypedDict 静态表达
            workflow = StateGraph(dict)  # type: ignore[type-var]  # StateGraph 泛型 StateT 不接受裸 dict（state 为动态 key 结构）
            for stage in stages:
                workflow.add_node(stage.id, _NODE_MAP[stage.id])  # type: ignore[type-var]  # add_node 节点输入泛型与动态 dict state 不匹配

            entry = next(s for s in stages if not s.input_from)
            workflow.set_entry_point(entry.id)
            for stage in stages:
                for downstream_id in stage.output_to:
                    workflow.add_edge(stage.id, downstream_id)
            terminal = next(s for s in stages if not s.output_to)
            workflow.add_edge(terminal.id, END)

            app = workflow.compile()
            final_state = await app.ainvoke(
                {
                    "context": context,
                    "stages": {s.id: s for s in stages},
                    "llm_client": self._llm,
                }
            )
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(f"管线执行失败: {e}") from e

        stage_results = [
            StageResult(
                stage_id=stage.id,
                status=StageStatus(
                    final_state.get(f"{stage.id}_status", StageStatus.COMPLETED.value)
                ),
                output=final_state.get(f"{stage.id}_output", ""),
                error=final_state.get(f"{stage.id}_error", ""),
                retry_count=final_state.get(f"{stage.id}_retry_count", 0),
            )
            for stage in stages
        ]
        failed = [sr for sr in stage_results if sr.status == StageStatus.FAILED]
        result = PipelineResult(
            stages=stage_results,
            final_output=final_state.get(f"{terminal.id}_output", ""),
            status=StageStatus.FAILED if failed else StageStatus.COMPLETED,
        )
        if failed:
            error = PipelineError(f"管线执行失败: 阶段 '{failed[0].stage_id}' 重试耗尽")
            error.result = result  # type: ignore[attr-defined]  # PipelineError 未声明 result 属性，运行时动态附加
            raise error
        return result
