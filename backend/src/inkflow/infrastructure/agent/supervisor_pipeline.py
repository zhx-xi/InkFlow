"""Supervisor 动态路由编排引擎 — 实现 AgentPipelineProtocol（spec §5.2-5.7）。

方案 A：supervisor 节点无静态出边，Command(goto) 全权控制路由（Spike ② 教训：
条件边+Command 并存会 fan-out）。护栏（steps/consecutive）在 supervisor 节点
内部校验（LLM 决策后强制）。fallback 固定链兜底（architect→writer→auditor→
reviser 剩余角色）。HITL：supervisor 命中 hitl_roles → goto hitl 节点；hitl 节点仅
interrupt（无其他副作用）。resume 后 approved → goto role，rejected → goto fallback。
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any, NotRequired, TypedDict, cast

from langgraph.channels.untracked_value import UntrackedValue
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig
from inkflow.domain.ports.agent_pipeline import (
    AgentPipelineProtocol,
    PipelineContext,
    PipelineError,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.infrastructure.agent.pipeline_nodes import PipelineState, generic_node


class SupervisorState(TypedDict):
    """Supervisor 图状态 — PipelineState 扩展 + supervisor 专属键。"""

    context: PipelineContext
    stages: dict[str, PipelineStage]
    # UntrackedValue：llm_client 不参与 checkpointer 序列化（FakeLLM 等 mock 不可
    # msgpack 序列化）；resume 时经 Command(update=...) 重新注入
    llm_client: Annotated[LLMClientProtocol, UntrackedValue(LLMClientProtocol)]
    _abort: NotRequired[bool]
    results: Annotated[dict[str, StageResult], dict.__or__]  # 镜像 PipelineState reducer
    route_history: Annotated[list[str], lambda a, b: a + b]
    steps: int
    consecutive: int
    last_role: str
    final_output: str
    hitl_pending: NotRequired[bool]


class HITLInterrupt(Exception):  # noqa: N818  # 测试契约要求精确类名 HITLInterrupt（不可用 Error 后缀）
    """HITL 中断 — 角色执行前 interrupt() 暂停，携带 payload 供 AgentService 存储。"""

    def __init__(self, payload: dict) -> None:
        super().__init__(payload)
        self.payload = payload


_FALLBACK_CHAIN = ["architect", "writer", "auditor", "reviser"]
_MAX_DECISION_ATTEMPTS = 4  # 初始 1 次 + 最多 3 次重试（空 content / 解析失败 / LLM 异常）
_DEFAULT_SUPERVISOR_PROMPT = (
    "你是小说创作管线的编排 supervisor，负责动态路由决策。"
    "请根据任务上下文、可用角色池、路由历史与护栏约束，选择下一个执行角色或结束。"
)


def _build_decision_messages(
    state: SupervisorState, config: SupervisorExecuteConfig, attempt: int
) -> list[ChatMessage]:
    """组装决策消息：system（角色池+护栏+历史，含「决策」字样——契约）+ user（JSON 要求）。

    重试（attempt > 0）时 user 消息附路由历史重申，督促 LLM 重新输出结构化决策。
    """
    system_prompt = config.supervisor_prompt or _DEFAULT_SUPERVISOR_PROMPT
    role_lines = "\n".join(
        f"- {stage_id}: {stage.name}" for stage_id, stage in state["stages"].items()
    )
    history = " → ".join(state.get("route_history", [])) or "（无）"
    system = (
        f"{system_prompt}\n\n"
        "决策要求：请根据以下信息做出下一步路由决策，仅输出一个 JSON 对象。\n"
        f"可用角色池（stage_id: name）：\n{role_lines}\n\n"
        f"路由历史：{history}\n"
        f"护栏约束：max_steps={config.max_steps}，max_consecutive={config.max_consecutive}。"
    )
    user = (
        '请输出 JSON 决策，格式：{"action": "execute", "role": "<stage_id>"}、'
        '{"action": "finish"} 或 {"action": "fallback"}。'
    )
    if attempt > 0:
        user += f"\n上次输出无效，请重新决策。当前路由历史：{history}。"
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]


def _parse_decision(content: str) -> tuple[str, str] | None:
    """解析 LLM 决策 JSON → (action, role)；解析失败/空 content 返回 None。

    role 仅在 action=execute 时有值，其余 action 恒为空串。
    宽松解析（#343 实证根因）：LLM 可能返回 markdown 代码块围栏包裹的 JSON
    （如 ```json\n{...}\n```），先试完整解析，失败则提取首个 { 到末个 } 子串。
    """
    if not content.strip():
        return None

    def _try_parse(text: str) -> dict | None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    data = _try_parse(content)
    if data is None:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and start < end:
            data = _try_parse(content[start : end + 1])
    if data is None:
        return None
    action = data.get("action")
    if action == "execute":
        role = data.get("role")
        if isinstance(role, str) and role:
            return ("execute", role)
        return None
    if action in ("finish", "fallback"):
        return (action, "")
    return None


def _decision_trace_entry(raw_decision: str, started: float) -> dict:
    """F47 #379：supervisor 路由决策 trace 条目（spec §2.1 type=decision）。

    reasoning 记录决策 JSON 原文；duration_ms 为本次决策调用耗时；output 恒为空串。
    """
    return {
        "node": "supervisor",
        "type": "decision",
        "reasoning": raw_decision,
        "tool_calls": [],
        "output": "",
        "duration_ms": int((time.monotonic() - started) * 1000),
        "ts": datetime.now(UTC).isoformat(),
    }


async def _decide_next_action(
    state: SupervisorState,
    config: SupervisorExecuteConfig,
    trace_sink: Callable[[dict], None] | None = None,
) -> tuple[str, str]:
    """LLM 决策循环：调用 chat → 解析；空 content / 解析失败 / 异常 → 重试 → 失败 ("", "")。

    trace_sink（F47 #379）：每次路由决策完成后追加一条 decision trace（supervisor 节点
    经实例注入收集器；直接调用本函数时省略，保持既有 (action, role) 契约）。
    """
    llm: LLMClientProtocol = state["llm_client"]
    started = time.monotonic()
    raw_decision = ""
    for attempt in range(_MAX_DECISION_ATTEMPTS):
        messages = _build_decision_messages(state, config, attempt)
        try:
            response = await llm.chat(messages)
        except Exception:
            continue
        raw_decision = response.content
        parsed = _parse_decision(raw_decision)
        if parsed is not None:
            if trace_sink is not None:
                trace_sink(_decision_trace_entry(raw_decision, started))
            return parsed
    if trace_sink is not None:
        trace_sink(_decision_trace_entry(raw_decision, started))
    return "", ""


def _pick_final(results: dict[str, StageResult]) -> str:
    """成品身份（F42 §5.6）：优先 reviser 输出；reviser 未执行 → writer 输出；都没有 → 空串。

    architect/auditor 永不作为成品。
    """
    reviser = results.get("reviser")
    if reviser is not None and reviser.status == StageStatus.COMPLETED:
        reviser_output: str = reviser.output
        return reviser_output
    writer = results.get("writer")
    if writer is not None and writer.status == StageStatus.COMPLETED:
        writer_output: str = writer.output
        return writer_output
    return ""


def _guard_triggered(state: SupervisorState, config: SupervisorExecuteConfig, role: str) -> bool:
    """振荡护栏（LLM 决策后强制）：步数超限 / 同角色连续达上限 / 非法角色 → 回退。"""
    if state.get("steps", 0) >= config.max_steps:
        return True
    if role == state.get("last_role", "") and state.get("consecutive", 0) >= config.max_consecutive:
        return True
    return role not in state["stages"]


async def _supervisor_node(
    state: SupervisorState,
    supervisor_config: SupervisorExecuteConfig,
    trace_sink: Callable[[dict], None] | None = None,
) -> Command[Any]:
    """LLM 决策下一个执行角色 → Command(goto)。

    决策输入组装（system prompt）：任务上下文变量 + 角色池（state["stages"] 的
    id/name 列表）+ 路由历史（route_history）+ 护栏约束（max_steps/max_consecutive）。
    决策输出解析（user 消息要求 JSON）：{"action": "execute", "role": "x"} /
    {"action": "finish"} / {"action": "fallback"}。
    护栏（LLM 决策后强制）：steps>=max_steps / role==last_role 且
    consecutive>=max_consecutive / role 不在角色池 → goto fallback。
    空 content / 解析失败 → 重试（最多 3 次，附路由历史重申）→ 仍失败 → fallback。
    HITL：决策角色在 hitl_roles 时 goto="hitl"（interrupt 前置独立节点，无其他副作用）；
    resume 后由 hitl 节点按 approved 分支 goto role / fallback。
    """
    action, role = await _decide_next_action(state, supervisor_config, trace_sink)
    if action == "":
        # 决策重试耗尽：fallback_on_error=false → 直接失败；默认 → deterministic 回退
        if not supervisor_config.fallback_on_error:
            return Command(update={"_abort": True}, goto=END)
        return Command(update={"route_history": ["__fallback__"]}, goto="fallback")
    if action == "finish":
        return Command(update={"final_output": _pick_final(state.get("results", {}))}, goto=END)
    if action == "fallback":
        return Command(update={"route_history": ["__fallback__"]}, goto="fallback")
    # action == "execute"
    if _guard_triggered(state, supervisor_config, role):
        if not supervisor_config.fallback_on_error:
            return Command(update={"_abort": True}, goto=END)
        return Command(update={"route_history": ["__fallback__"]}, goto="fallback")
    if role in supervisor_config.hitl_roles:
        # HITL 命中 → goto 独立 hitl 节点（interrupt 前置，无其他副作用）
        return Command(update={"route_history": [role]}, goto="hitl")
    return Command(update={"route_history": [role]}, goto=role)


async def _hitl_node(
    state: SupervisorState, supervisor_config: SupervisorExecuteConfig
) -> Command[Any]:
    """HITL 确认节点：interrupt 前置（无其他副作用），resume 后从 interrupt 返回 resume 值。
    LangGraph resume 语义 = 节点从头重跑；本节点除 interrupt 外无副作用，
    重跑安全。approved=True → goto 待确认角色；False → fallback 固定链。
    待确认角色 = route_history 尾部（supervisor 决策时已追加增量）。
    """
    pending_role = state.get("route_history", [])[-1] if state.get("route_history") else ""
    decision: dict = interrupt(
        {
            "question": f"确认执行下一角色 {pending_role}？",
            "role": pending_role,
            "route_history": state.get("route_history", []),
        }
    )
    if decision.get("approved", False):
        return Command(goto=pending_role)
    return Command(update={"route_history": ["__fallback__"]}, goto="fallback")


async def _bootstrap_node(
    state: SupervisorState, llm_client: LLMClientProtocol
) -> dict[str, object]:
    """启动节点：将 llm_client 写入 UntrackedValue 通道（不参与 checkpointer 序列化）。

    llm_client 不随初始输入传入（否则 __start__ 通道将整个输入 dict 写入 checkpoint，
    触发不可序列化错误）；由本节点在执行初期注入，resume 时经 Command(update=...) 重注入。
    """
    return {"llm_client": llm_client}


async def _role_node(state: SupervisorState, role_id: str) -> dict[str, object]:
    """角色执行节点：包装 generic_node（复用重试/失败语义）+ 更新 steps/consecutive 计数。"""
    result: dict[str, object] = await generic_node(cast(PipelineState, state), role_id)
    consecutive = state.get("consecutive", 0)
    if state.get("last_role") == role_id:
        consecutive += 1
    else:
        consecutive = 1
    result["steps"] = state.get("steps", 0) + 1
    result["consecutive"] = consecutive
    result["last_role"] = role_id
    return result


async def _fallback_node(state: SupervisorState) -> dict[str, object]:
    """deterministic 回退：固定链执行剩余未完成角色（architect→writer→auditor→reviser）。"""
    executed = {
        sid for sid, sr in state.get("results", {}).items() if sr.status == StageStatus.COMPLETED
    }
    remaining = [r for r in _FALLBACK_CHAIN if r not in executed and r in state["stages"]]
    results_increment: dict[str, StageResult] = {}
    aborted = False
    for role_id in remaining:
        result: dict[str, object] = await generic_node(cast(PipelineState, state), role_id)
        for sid, sr in cast(dict[str, StageResult], result.get("results", {})).items():
            results_increment[sid] = sr
        if result.get("_abort") is True:
            aborted = True
            break
    merged_results = {**state.get("results", {}), **results_increment}
    return {
        "results": results_increment,
        "final_output": _pick_final(merged_results),
        **({"_abort": True} if aborted else {}),
    }


class SupervisorPipeline(AgentPipelineProtocol):
    """Supervisor 动态路由编排引擎 — 实现 AgentPipelineProtocol（spec §5.2-5.7）。"""

    def __init__(
        self,
        llm_client: LLMClientProtocol,
        *,
        checkpointer: InMemorySaver | None = None,
    ) -> None:
        """构造：llm_client 决策/角色执行共用；checkpointer 默认 InMemorySaver（进程内）。"""
        self._llm = llm_client
        self._checkpointer = checkpointer or InMemorySaver()
        self._roles: list[str] = []
        self._stages: list[PipelineStage] = []
        self._config = SupervisorExecuteConfig()
        self._thread_id = ""
        self._trace: list[dict] = []

    def _append_trace(self, entry: dict) -> None:
        """F47 #379：收集 supervisor 路由决策 trace 条目（供 _to_result 合并返回）。"""
        self._trace.append(entry)

    def validate(self, stages: Sequence[PipelineStage]) -> list[str]:
        """角色池合法性校验：非空 / 无重复 id（spec §7 空池拒绝）。"""
        errors: list[str] = []
        if not stages:
            return ["管线至少需要一个阶段"]
        ids = [s.id for s in stages]
        if len(ids) != len(set(ids)):
            errors.append("阶段 id 不能重复")
        return errors

    def _build_graph(
        self, config: SupervisorExecuteConfig
    ) -> CompiledStateGraph[SupervisorState, Any, Any, Any]:
        """方案 A 拓扑：supervisor/hitl 无静态出边，Command(goto) 全权控制路由。"""
        g = StateGraph(SupervisorState)
        g.add_node("bootstrap", partial(_bootstrap_node, llm_client=self._llm))
        g.add_node(
            "supervisor",
            partial(_supervisor_node, supervisor_config=config, trace_sink=self._append_trace),
        )
        g.add_node("hitl", partial(_hitl_node, supervisor_config=config))
        for role_id in self._roles:
            g.add_node(role_id, partial(_role_node, role_id=role_id))
        g.add_node("fallback", _fallback_node)
        g.add_edge(START, "bootstrap")
        g.add_edge("bootstrap", "supervisor")
        for role_id in self._roles:
            g.add_edge(role_id, "supervisor")
        g.add_edge("fallback", END)
        return g.compile(checkpointer=self._checkpointer)

    async def execute(
        self,
        stages: Sequence[PipelineStage],
        context: PipelineContext,
        *,
        supervisor: SupervisorExecuteConfig | None = None,
    ) -> PipelineResult:
        """构建 supervisor 图 → ainvoke（InMemorySaver checkpointer）→ PipelineResult。

        HITL：首次 interrupt 时抛 HITLInterrupt（payload 供 AgentService 存 waiting_hitl）；
        resume() 从 checkpointer 恢复继续。
        """
        config = supervisor or SupervisorExecuteConfig()
        errors = self.validate(stages)
        if errors:
            raise PipelineError(f"supervisor 管线配置无效: {'; '.join(errors)}")
        self._config = config
        self._stages = list(stages)
        self._roles = [s.id for s in stages]
        self._thread_id = f"supervisor-{uuid.uuid4()}"
        self._trace = []
        app = self._build_graph(config)
        state = cast(
            SupervisorState,
            {
                "context": context,
                "stages": {s.id: s for s in stages},
                "results": {},
                "route_history": [],
                "steps": 0,
                "consecutive": 0,
                "last_role": "",
                "final_output": "",
            },
        )
        try:
            final = await app.ainvoke(
                state, config={"configurable": {"thread_id": self._thread_id}}
            )
        except Exception as e:
            raise PipelineError(f"supervisor 编排失败: {e}") from e
        final_dict = cast(dict[str, Any], final)
        interrupts = final_dict.get("__interrupt__")
        if interrupts:
            raise HITLInterrupt(interrupts[0].value)
        return self._to_result(self._stages, cast(SupervisorState, final_dict))

    async def resume(self, interrupt_obj: HITLInterrupt, *, approved: bool) -> PipelineResult:
        """HITL confirm 后从 checkpointer 恢复（approved=False → 走 fallback 固定链）。

        thread_id 沿用 execute() 生成的值；checkpointer 实例跨调用持久保存图状态。
        """
        app = self._build_graph(self._config)
        try:
            final = await app.ainvoke(
                Command(
                    resume={"approved": approved},
                    update={"llm_client": self._llm},
                ),
                config={"configurable": {"thread_id": self._thread_id}},
            )
        except Exception as e:
            raise PipelineError(f"supervisor resume 失败: {e}") from e
        final_dict = cast(dict[str, Any], final)
        interrupts = final_dict.get("__interrupt__")
        if interrupts:
            raise HITLInterrupt(interrupts[0].value)
        return self._to_result(self._stages, cast(SupervisorState, final_dict))

    def _to_result(
        self, stages: Sequence[PipelineStage], final_state: SupervisorState
    ) -> PipelineResult:
        """汇总：stages = route_history 展开（重复角色保留多次，Q3=A）+ fallback 链补录；

        status = completed（有 failed / _abort 则 failed）；final_output 取成品身份。
        """
        results_map: dict[str, StageResult] = final_state.get("results", {})
        stage_results: list[StageResult] = []
        seen: set[str] = set()
        for role in final_state.get("route_history", []):
            if role == "__fallback__":
                continue
            sr = results_map.get(role, StageResult(stage_id=role, status=StageStatus.COMPLETED))
            stage_results.append(sr)
            seen.add(role)
        # fallback 固定链角色补录（不在 route_history 中）
        for role in _FALLBACK_CHAIN:
            if role in results_map and role not in seen:
                stage_results.append(results_map[role])
                seen.add(role)
        # 其余已执行角色兜底（自定义角色等）
        for role, sr in results_map.items():
            if role not in seen:
                stage_results.append(sr)
                seen.add(role)
        failed = [sr for sr in stage_results if sr.status == StageStatus.FAILED]
        status = (
            StageStatus.FAILED
            if failed or final_state.get("_abort", False)
            else StageStatus.COMPLETED
        )
        # F47 #379（spec §2.1）：decision trace（supervisor 决策，执行期收集）在前，
        # stage trace（角色节点执行，按 stage_results 组装）在后，随 result 返回。
        trace_ts = datetime.now(UTC).isoformat()
        stage_trace = [
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
        return PipelineResult(
            stages=stage_results,
            final_output=final_state.get("final_output", ""),
            status=status,
            trace=[*self._trace, *stage_trace],
        )
