"""F49 自主全自动写作 - book-level 自主编排核心（#551 后端批 1）.

BookAgenticPipeline 镜像 F29 SupervisorPipeline 动态路由 + F44 BookVolumePipeline
checkpoint/HITL：book_supervisor 节点 LLM 决策 → Command(goto) 路由到书级操作节点
（write_chapter/audit_chapter/revise_chapter/mark_done/finish_book）；操作节点执行后
静态边回 book_supervisor（Spike ② 教训：条件边 + Command 并存会 fan-out）；hitl 节点
仅 interrupt（无其他副作用，F44 R4）；fallback 确定性兜底写剩余章 → END。

图拓扑：
    START → bootstrap（UntrackedValue 注入 llm_client）
          → book_supervisor（LLM 决策 → Command(goto=op/finish/fallback)，无静态出边）
            → write_chapter / audit_chapter / revise_chapter / mark_done / finish_book /
              hitl / fallback
    write/audit/revise 执行后静态边回 book_supervisor；mark_done 恒 Command(goto=...)
    （chapter_done HITL 条件路由，无静态边——Spike ②）；hitl 仅 interrupt；fallback → END。

依据: specs/f27-writer-agent/spec.md §5.1-§5.5/§7
    + backend/tests/unit/test_book_agentic_pipeline.py（RED 契约 docstring）。
"""

from __future__ import annotations

import json
import operator
import uuid
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Annotated, Any, NotRequired, TypedDict, TypeVar, cast

from langgraph.channels.untracked_value import UntrackedValue
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from inkflow.domain.models.agent_book import AgenticBookConfig
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.ports.llm_client import ChatMessage

_R = TypeVar("_R")


class BookAgenticState(TypedDict):
    """book-level 编排图状态 - 镜像 SupervisorState 的 reducer 模式."""

    context: dict[str, Any]
    plan: dict
    chapters: list[dict]
    limits: dict
    config: dict
    progress: dict[str, str]
    results: Annotated[dict[str, str], operator.or_]
    audit_results: Annotated[dict[str, dict], operator.or_]
    route_history: Annotated[list[str], lambda a, b: a + b]
    steps: int
    consecutive: int
    last_op: str
    finished: bool
    status: NotRequired[str]
    # 内部路由键（镜像 F29 _abort/hitl_pending）：target_outline_id = 当前决策目标章，
    # chapter_ops = 各章 write/audit/revise 累计次数（章节循环护栏数据源）
    target_outline_id: NotRequired[str]
    chapter_ops: NotRequired[dict[str, int]]
    llm_client: Annotated[object, UntrackedValue(object)]


class BookAgenticHITLInterrupt(Exception):  # noqa: N818  # 测试契约要求精确类名（不可用 Error 后缀）
    """book-level HITL 中断 - interrupt() 暂停，payload 供 BookService 存 waiting_hitl."""

    def __init__(self, payload: dict) -> None:
        super().__init__(payload)
        self.payload = payload


_OPERATION_POOL = [
    "write_chapter",
    "audit_chapter",
    "revise_chapter",
    "mark_done",
    "finish_book",
]
_CHAPTER_OPS = ("write_chapter", "audit_chapter", "revise_chapter")
_MAX_DECISION_ATTEMPTS = 4  # 初始 1 次 + 最多 3 次重试（空 content / 解析失败 / LLM 异常）
_DEFAULT_SUPERVISOR_PROMPT = (
    "你是小说创作管线的 book-level 编排 supervisor，负责书级动态路由决策。"
    "请根据书任务上下文、各章状态、书进度、路由历史与护栏约束，选择下一个操作或结束。"
)


def _try_json(content: str) -> dict | None:
    """宽松 JSON 解析：仅接受 dict；其余（含列表/标量）返回 None."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_decision(content: str) -> tuple[str, str, str] | None:
    """解析 LLM 决策 JSON → (action, op, outline_id)；空 content/解析失败返回 None.

    宽松解析（镜像 F29 _parse_decision）：LLM 可能返回 markdown 代码块围栏包裹的
    JSON，先试完整解析，失败则提取首个 { 到末个 } 子串。
    """
    if not content.strip():
        return None
    data = _try_json(content)
    if data is None:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and start < end:
            data = _try_json(content[start : end + 1])
    if data is None:
        return None
    action = data.get("action")
    if action == "goto":
        op = data.get("op")
        oid = data.get("outline_id")
        if isinstance(op, str) and op and isinstance(oid, str) and oid:
            return ("goto", op, oid)
        return None
    if action in ("finish", "fallback"):
        return (action, "", "")
    return None


def _parse_audit(content: str) -> dict:
    """解析审校 LLM 输出 → {score, issues}；解析失败返回零分空问题（不阻塞编排）."""
    data = _try_json(content)
    if data is None:
        return {"score": 0, "issues": []}
    issues = data.get("issues", [])
    return {
        "score": int(data.get("score", 0)),
        "issues": [str(i) for i in issues] if isinstance(issues, list) else [],
    }


def _find_chapter(chapters: list[dict], outline_id: str) -> dict | None:
    """按 outline_id（uuid 或 str）查章 dict；无 → None."""
    for ch in chapters:
        if str(ch.get("outline_id", "")) == str(outline_id):
            return ch
    return None


def _extract_final_content(result: dict[str, Any]) -> str:
    """从 agent.invoke 结果（dict，含 "messages"）提取最终 message content（镜像 F44）."""
    messages = result.get("messages", [])
    if not messages:
        return ""
    final = messages[-1]
    content = getattr(final, "content", None)
    if content is None and isinstance(final, dict):
        content = final.get("content")
    if content is None:
        return ""
    return str(content)


def _plan_to_dict(plan: object) -> dict:
    """WritingPlan → JSON dict；鸭子对象（SimpleNamespace）→ vars 快照（UUID 转 str）."""
    if hasattr(plan, "model_dump"):
        return cast(dict, plan.model_dump(mode="json"))  # 鸭子类型：WritingPlan 提供 model_dump
    data = dict(vars(plan))
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()}


def _restore_plan(data: dict) -> WritingPlan:
    """从 checkpoint 状态还原 WritingPlan（过滤未知键，兼容鸭子对象快照）."""
    fields = WritingPlan.model_fields
    return WritingPlan(**{k: v for k, v in data.items() if k in fields})


def _counter_update(state: BookAgenticState, op: str) -> dict[str, object]:
    """操作节点计数（镜像 F29 _role_node）：steps/consecutive/last_op."""
    consecutive = state.get("consecutive", 0)
    if state.get("last_op", "") == op:
        consecutive += 1
    else:
        consecutive = 1
    return {
        "steps": state.get("steps", 0) + 1,
        "consecutive": consecutive,
        "last_op": op,
    }


def _bump_chapter_ops(state: BookAgenticState, outline_id: str) -> dict[str, int]:
    """各章 write/audit/revise 累计次数 +1（章节循环护栏数据源）."""
    ops = dict(state.get("chapter_ops", {}))
    ops[outline_id] = ops.get(outline_id, 0) + 1
    return ops


def _first_unaudited_written(state: BookAgenticState) -> str | None:
    """返回已写未审的章 outline_id（progress=in_progress 且无 audit_results）；无 → None."""
    progress = state.get("progress", {})
    audit_results = state.get("audit_results", {})
    for oid in progress:
        if progress[oid] == "in_progress" and oid not in audit_results:
            return oid
    return None


def _guarded_route(
    state: BookAgenticState, config: AgenticBookConfig, op: str, oid: str
) -> tuple[str, str] | None:
    """护栏（LLM 决策后强制，F29 §5.4）：返回 (op, oid)；None → fallback.

    判定顺序：steps 超限 / 振荡（op==last_op 且 consecutive>=max_consecutive）/
    非法 op 或非法 outline_id → fallback；章节循环超限 → 强制 mark_done；
    audit_required 且写后未审即 mark_done / 写其它章 → 强制 audit_chapter。
    """
    if state.get("steps", 0) >= config.max_steps:
        return None
    if op == state.get("last_op", "") and state.get("consecutive", 0) >= config.max_consecutive:
        return None
    if op not in _OPERATION_POOL:
        return None
    if op in ("write_chapter", "audit_chapter", "revise_chapter", "mark_done") and (
        _find_chapter(state["chapters"], oid) is None
    ):
        return None
    if op in _CHAPTER_OPS and state.get("chapter_ops", {}).get(oid, 0) >= config.max_chapter_cycles:
        op = "mark_done"
    if config.audit_required:
        unaudited = _first_unaudited_written(state)
        if op == "mark_done" and unaudited is not None:
            return ("audit_chapter", unaudited)
        if op == "write_chapter" and unaudited is not None and unaudited != oid:
            return ("audit_chapter", unaudited)
    return (op, oid)


def _build_decision_messages(
    state: BookAgenticState, config: AgenticBookConfig, attempt: int
) -> list[ChatMessage]:
    """组装决策消息：system（操作池+各章状态+书进度+路由历史+护栏，含「决策」字样——RED 契约）
    + user（结构化 JSON 要求；重试时重申路由历史）. """
    system_prompt = config.supervisor_prompt or _DEFAULT_SUPERVISOR_PROMPT
    chapter_lines = "\n".join(
        f"- {ch.get('name', '')}（outline_id={ch.get('outline_id')}，状态="
        f"{state.get('progress', {}).get(str(ch.get('outline_id', '')), 'pending')}）"
        for ch in state["chapters"]
    )
    history = " → ".join(state.get("route_history", [])) or "（无）"
    done = sum(1 for s in state.get("progress", {}).values() if s == "done")
    failed = sum(1 for s in state.get("progress", {}).values() if s == "failed")
    system = (
        f"{system_prompt}\n\n"
        "决策要求：请根据以下信息做出下一步路由决策，仅输出一个 JSON 对象。\n"
        "可用操作池（op: 说明）：\n"
        "- write_chapter: 撰写一章\n"
        "- audit_chapter: 审校一章\n"
        "- revise_chapter: 按审校意见修订一章\n"
        "- mark_done: 标记一章完成\n"
        "- finish_book: 全书完成\n\n"
        f"各章状态：\n{chapter_lines}\n\n"
        f"书进度：done={done}，failed={failed}，总章数={len(state['chapters'])}\n"
        f"路由历史：{history}\n"
        f"护栏约束：max_steps={config.max_steps}，max_consecutive={config.max_consecutive}，"
        f"max_chapter_cycles={config.max_chapter_cycles}。"
    )
    user = (
        '请输出 JSON 决策，格式：{"action": "goto", "op": "<write_chapter|audit_chapter|'
        'revise_chapter|mark_done|finish_book>", "outline_id": "<uuid str>"}、'
        '{"action": "finish"} 或 {"action": "fallback"}。'
    )
    if attempt > 0:
        user += f"\n上次输出无效，请重新决策。当前路由历史：{history}。"
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]


async def _decide_next_action(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> tuple[str, str, str]:
    """LLM 决策循环：chat → 解析；空 content / 解析失败 / 异常 → 重试至多 3 次 → ("", "", "")."""
    llm = state["llm_client"]
    config = pipeline._config
    for attempt in range(_MAX_DECISION_ATTEMPTS):
        messages = _build_decision_messages(state, config, attempt)
        try:
            response = await llm.chat(messages)  # type: ignore[attr-defined]  # 鸭子类型：llm_client 提供 async chat(messages)
        except Exception:
            continue
        parsed = _parse_decision(str(getattr(response, "content", "")))
        if parsed is not None:
            return parsed
    return ("", "", "")


async def _supervisor_node(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> Command[Any]:
    """LLM 决策下一个 book-level 操作 → Command(goto)；护栏在决策后强制（F29 模式）."""
    config = pipeline._config
    action, op, oid = await _decide_next_action(state, pipeline)
    if action == "":
        # 决策重试耗尽 / 异常：fallback_on_error=false → 直接中止；默认 → 确定性兜底
        if not config.fallback_on_error:
            return Command(update={"finished": True, "status": "aborted"}, goto=END)
        return Command(update={"route_history": ["__fallback__"]}, goto="fallback")
    if action == "finish":
        goto = "hitl" if "finish" in config.hitl_points else "finish_book"
        return Command(update={"route_history": ["finish_book"]}, goto=goto)
    if action == "fallback":
        return Command(update={"route_history": ["__fallback__"]}, goto="fallback")
    # action == "goto"
    guarded = _guarded_route(state, config, op, oid)
    if guarded is None:
        if not config.fallback_on_error:
            return Command(update={"finished": True, "status": "aborted"}, goto=END)
        return Command(update={"route_history": ["__fallback__"]}, goto="fallback")
    op, oid = guarded
    return Command(update={"route_history": [op], "target_outline_id": oid}, goto=op)


async def _bootstrap_node(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> Command[Any]:
    """启动节点：注入 llm_client（UntrackedValue）；hitl_points 含 book_start → 先走 hitl.

    恒返回 Command(goto=...)：bootstrap 无静态出边（Spike ② 教训——Command 与静态边
    并存会 fan-out）。
    """
    update: dict[str, object] = {"llm_client": pipeline._llm}
    goto = "hitl" if "book_start" in pipeline._config.hitl_points else "book_supervisor"
    return Command(update=update, goto=goto)


async def _hitl_node(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> Command[Any]:
    """HITL 确认节点：仅 interrupt（无其他副作用，F44 R4）；resume 后按 pending 路由.

    pending = route_history 尾部（finish_book）或 book_start（启动中断）；chapter_done
    中断时 pending=mark_done。approved=True → 继续编排；False → 中止（status=aborted）。
    """
    route_history = state.get("route_history", [])
    pending = route_history[-1] if route_history else "book_start"
    decision: dict = interrupt(
        {
            "question": f"确认继续书级编排（{pending}）？",
            "thread_id": pipeline._thread_id,
            "run_id": pipeline._thread_id,
            "hitl_point": pending,
        }
    )
    if not decision.get("approved", False):
        return Command(update={"finished": True, "status": "aborted"}, goto=END)
    if pending == "finish_book":
        return Command(goto="finish_book")
    return Command(goto="book_supervisor")


async def _write_chapter(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """write_chapter：writer_factory → agent.invoke → draft_service.create → 落盘增量.

    失败重试 retry_limit 次 → 标记 failed（supervisor 后续决策跳过/重写/兜底）。
    """
    oid = state.get("target_outline_id", "")
    chapter = _find_chapter(state["chapters"], oid)
    update = _counter_update(state, "write_chapter")
    if chapter is None:
        return {**update, "results": {oid: "failed"}, "progress": {oid: "failed"}}
    execution_id: str | None = None
    for _ in range(1 + pipeline._retry_limit):
        try:
            execution_id = await pipeline._delegate_write(chapter)
        except Exception:
            continue
        else:
            break
    if execution_id is None:
        return {**update, "results": {oid: "failed"}, "progress": {oid: "failed"}}
    return {
        **update,
        "chapter_ops": _bump_chapter_ops(state, oid),
        "results": {oid: execution_id},
        "progress": {oid: "in_progress"},
    }


async def _audit_chapter(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """audit_chapter：audit_callable（注入）或 llm_client.chat（非决策调用）→ audit_results."""
    oid = state.get("target_outline_id", "")
    chapter = _find_chapter(state["chapters"], oid)
    update = _counter_update(state, "audit_chapter")
    audit: dict = {"score": 0, "issues": []}
    if chapter is not None:
        try:
            audit = await pipeline._delegate_audit(chapter)
        except Exception:
            audit = {"score": 0, "issues": []}
    extra: dict[str, object] = {"audit_results": {oid: audit}}
    if chapter is not None:
        extra["chapter_ops"] = _bump_chapter_ops(state, oid)
    return {**update, **extra}


async def _revise_chapter(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """revise_chapter：按 audit 意见改写 → draft_service.create 重新落盘 → 更新 results."""
    oid = state.get("target_outline_id", "")
    chapter = _find_chapter(state["chapters"], oid)
    update = _counter_update(state, "revise_chapter")
    if chapter is None:
        return {**update, "results": {oid: "failed"}, "progress": {oid: "failed"}}
    audit = state.get("audit_results", {}).get(oid, {})
    audit_issues = [str(i) for i in audit.get("issues", [])] if isinstance(audit, dict) else []
    execution_id: str | None = None
    for _ in range(1 + pipeline._retry_limit):
        try:
            execution_id = await pipeline._delegate_write(chapter, audit_issues=audit_issues)
        except Exception:
            continue
        else:
            break
    if execution_id is None:
        return {**update, "results": {oid: "failed"}, "progress": {oid: "failed"}}
    return {**update, "chapter_ops": _bump_chapter_ops(state, oid), "results": {oid: execution_id}}


async def _mark_done(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> Command[Any]:
    """mark_done：progress=done + execution_refs 落库；chapter_done 命中 → goto hitl.

    恒返回 Command(goto=...)：mark_done 无静态出边（避免 Command + 静态边 fan-out）。
    """
    oid = state.get("target_outline_id", "")
    update: dict[str, object] = {
        **_counter_update(state, "mark_done"),
        "progress": {**state.get("progress", {}), oid: "done"},
    }
    if pipeline._plan is not None:
        ref = state.get("results", {}).get(oid, "")
        pipeline._plan.execution_refs[oid] = ref
    goto = "hitl" if "chapter_done" in pipeline._config.hitl_points else "book_supervisor"
    return Command(update=update, goto=goto)


async def _finish_book(state: BookAgenticState) -> Command[Any]:
    """finish_book：finished=True → END（status=completed）."""
    return Command(update={"finished": True, "status": "completed"}, goto=END)


async def _fallback_node(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """fallback：剩余未 done 章一次 write 完成（确定性兜底，R10）；静态边 → END."""
    progress = dict(state.get("progress", {}))
    results: dict[str, str] = {}
    for chapter in state["chapters"]:
        oid = str(chapter["outline_id"])
        if progress.get(oid) == "done":
            continue
        execution_id: str | None = None
        for _ in range(1 + pipeline._retry_limit):
            try:
                execution_id = await pipeline._delegate_write(chapter)
            except Exception:
                continue
            else:
                break
        if execution_id is None:
            progress[oid] = "failed"
            results[oid] = "failed"
        else:
            progress[oid] = "done"
            results[oid] = execution_id
            if pipeline._plan is not None:
                pipeline._plan.execution_refs[oid] = execution_id
    return {"progress": progress, "results": results, "finished": True, "status": "completed"}


class BookAgenticPipeline:
    """book-level 自主编排引擎（镜像 F29 supervisor + F44 checkpoint/HITL 结构）."""

    def __init__(
        self,
        llm_client: object,
        *,
        writer_factory: Callable[..., Awaitable[object]] | None = None,
        draft_service: object | None = None,
        audit_callable: Callable[..., Awaitable[object]] | None = None,
        retry_limit: int = 2,
        checkpointer: InMemorySaver | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        """构造：llm_client 经 UntrackedValue 注入（不参与 checkpointer 序列化，R7）.

        checkpointer 显式传入 → 优先使用（不打开文件）；否则 checkpoint_path → 每次
        execute/resume 临时打开 AsyncSqliteSaver 文件后端（跨实例/跨进程 resume 可行）；
        两者皆无 → 进程内 InMemorySaver。
        """
        self._llm = llm_client
        self._writer_factory = writer_factory
        self._draft_service = draft_service
        self._audit_callable = audit_callable
        self._retry_limit = retry_limit
        if checkpointer is None and checkpoint_path is None:
            checkpointer = InMemorySaver()
        self._checkpointer = checkpointer
        self._checkpoint_path = checkpoint_path
        self._thread_id = ""
        self._plan: WritingPlan | None = None
        self._limits = BookLimits()
        self._config = AgenticBookConfig()

    def _build_graph(
        self, checkpointer: BaseCheckpointSaver
    ) -> CompiledStateGraph[BookAgenticState, Any, Any, Any]:
        """构建 book-level 图：bootstrap → book_supervisor（Command(goto) 动态路由）→
        操作节点（执行后静态边回 book_supervisor）；hitl 无静态出边（仅 interrupt）；
        fallback → END。"""
        g = StateGraph(BookAgenticState)
        g.add_node("bootstrap", partial(_bootstrap_node, pipeline=self))
        g.add_node("book_supervisor", partial(_supervisor_node, pipeline=self))
        g.add_node("write_chapter", partial(_write_chapter, pipeline=self))
        g.add_node("audit_chapter", partial(_audit_chapter, pipeline=self))
        g.add_node("revise_chapter", partial(_revise_chapter, pipeline=self))
        g.add_node("mark_done", partial(_mark_done, pipeline=self))
        g.add_node("finish_book", _finish_book)
        g.add_node("hitl", partial(_hitl_node, pipeline=self))
        g.add_node("fallback", partial(_fallback_node, pipeline=self))
        g.add_edge(START, "bootstrap")
        for op in ("write_chapter", "audit_chapter", "revise_chapter"):
            g.add_edge(op, "book_supervisor")
        g.add_edge("fallback", END)
        return g.compile(checkpointer=checkpointer)

    async def _run_with_checkpointer(
        self,
        fn: Callable[[CompiledStateGraph[BookAgenticState, Any, Any, Any]], Awaitable[_R]],
        *,
        thread_id: str,
    ) -> _R:
        """编译图后执行 fn：显式 checkpointer 优先；否则按 checkpoint_path 临时打开
        AsyncSqliteSaver 文件后端（async with 生命周期内编译 + 运行 + 落盘，镜像 F44）."""
        if self._checkpointer is not None:
            return await fn(self._build_graph(self._checkpointer))
        async with AsyncSqliteSaver.from_conn_string(str(self._checkpoint_path)) as saver:
            return await fn(self._build_graph(saver))

    async def execute(
        self,
        plan: WritingPlan,
        chapters: list[dict],
        limits: BookLimits,
        *,
        config: AgenticBookConfig | None = None,
        thread_id: str | None = None,
    ) -> dict[str, str]:
        """跑 book-level 自主编排：book_supervisor 动态路由 write/audit/revise/mark_done/finish.

        thread_id 给定 → 用作图 thread_id（与 run_id 统一，供 resume/checkpoint 定位）；
        None → 内部生成 uuid4。HITL 命中 → 抛 BookAgenticHITLInterrupt（payload 含
        thread_id/run_id/question，供 BookService 存 waiting_hitl）。

        Returns:
            {"run_id": ..., "status": "completed" | "aborted", "thread_id": ...}
        Raises:
            BookAgenticHITLInterrupt: HITL 确认点暂停（hitl_points 白名单命中）。
        """
        self._plan = plan
        self._limits = limits
        self._config = config or AgenticBookConfig()
        self._thread_id = thread_id if thread_id is not None else str(uuid.uuid4())
        state = cast(
            BookAgenticState,
            {
                "context": {"plan_id": str(plan.id), "project_id": str(plan.project_id)},
                "plan": _plan_to_dict(plan),
                "chapters": chapters,
                "limits": limits.model_dump(),
                "config": self._config.model_dump(),
                "progress": {},
                "results": {},
                "audit_results": {},
                "route_history": [],
                "steps": 0,
                "consecutive": 0,
                "last_op": "",
                "finished": False,
            },
        )

        async def _run(
            app: CompiledStateGraph[BookAgenticState, Any, Any, Any],
        ) -> dict[str, str]:
            final = await app.ainvoke(
                state, config={"configurable": {"thread_id": self._thread_id}}
            )
            final_dict = cast(dict[str, Any], final)
            interrupts = final_dict.get("__interrupt__")
            if interrupts:
                raise BookAgenticHITLInterrupt(interrupts[0].value)
            return {
                "run_id": self._thread_id,
                "status": str(final_dict.get("status", "completed")),
                "thread_id": self._thread_id,
            }

        return await self._run_with_checkpointer(_run, thread_id=self._thread_id)

    async def resume(
        self,
        interrupt_obj: BookAgenticHITLInterrupt,
        *,
        approved: bool = True,
        decision: str = "",
        thread_id: str | None = None,
    ) -> dict[str, str]:
        """HITL 确认后从 checkpointer 恢复（thread_id 沿用 execute 生成值/给定值）.

        approved=True → 继续编排；False → 中止（status=aborted）。再次遇 interrupt → 再抛。
        跨重启（fresh 实例）从 checkpoint 恢复 plan/limits/config 后继续（R9/R10 语义）。
        """
        self._thread_id = thread_id if thread_id is not None else self._thread_id

        async def _run(
            app: CompiledStateGraph[BookAgenticState, Any, Any, Any],
        ) -> dict[str, str]:
            snapshot = await app.aget_state(
                config={"configurable": {"thread_id": self._thread_id}}
            )
            values: dict = snapshot.values
            if values.get("plan"):
                self._plan = _restore_plan(values["plan"])
            if values.get("limits"):
                self._limits = BookLimits(**values["limits"])
            if values.get("config"):
                self._config = AgenticBookConfig(**values["config"])
            final = await app.ainvoke(
                Command(
                    resume={"approved": approved, "decision": decision},
                    update={"llm_client": self._llm},
                ),
                config={"configurable": {"thread_id": self._thread_id}},
            )
            final_dict = cast(dict[str, Any], final)
            interrupts = final_dict.get("__interrupt__")
            if interrupts:
                raise BookAgenticHITLInterrupt(interrupts[0].value)
            return {
                "run_id": self._thread_id,
                "status": str(final_dict.get("status", "completed")),
                "thread_id": self._thread_id,
            }

        return await self._run_with_checkpointer(_run, thread_id=self._thread_id)

    async def get_checkpoint_state(self, run_id: str) -> dict | None:
        """查询图状态（BookAgenticState 键）；无 checkpoint → None."""

        async def _read(
            app: CompiledStateGraph[BookAgenticState, Any, Any, Any],
        ) -> dict | None:
            snapshot = await app.aget_state(
                config={"configurable": {"thread_id": run_id}}
            )
            values: dict = snapshot.values
            return values if values else None

        return await self._run_with_checkpointer(_read, thread_id=run_id)

    async def _delegate_write(
        self, chapter: dict, *, audit_issues: list[str] | None = None
    ) -> str:
        """委托章写作（镜像 F44 _delegate_chapter）：章 brief → writer_factory →
        agent.invoke → draft_service.create 回收 → 返回 execution_id."""
        plan = self._plan
        if plan is None:
            raise ValueError("plan 未装配")
        if self._writer_factory is None:
            raise ValueError("writer_factory 未装配")
        if self._draft_service is None:
            raise ValueError("draft_service 未装配")
        system_prompt = self._build_chapter_brief(plan, chapter, audit_issues or [])
        agent = await self._writer_factory(
            system_prompt=system_prompt,
            expected_project_id=plan.project_id,
            expected_chapter_id=chapter["chapter_id"],
        )
        result = await agent.invoke(  # type: ignore[attr-defined]  # 鸭子类型：agent 按 F27 契约提供 async invoke(messages, config)
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (f"请撰写章节《{chapter['name']}》：{chapter['description']}"),
                },
            ],
            config={"configurable": {"thread_id": self._thread_id}},
        )
        content = _extract_final_content(result)
        draft = await self._draft_service.create(  # type: ignore[attr-defined]  # 鸭子类型：draft_service 按 F27 契约提供 async create
            project_id=plan.project_id,
            chapter_id=chapter["chapter_id"],
            content=content,
            summary="书级 agent 编排保存",
        )
        return str(getattr(draft, "id", ""))

    @staticmethod
    def _build_chapter_brief(plan: WritingPlan, chapter: dict, audit_issues: list[str]) -> str:
        """构造章 brief：大纲切片 + 角色摘要 + 风格/偏好注入（镜像 F44/BookService）."""
        character_summary = (
            "主角自定" if not plan.character_ids else "见角色档案（plan.character_ids）"
        )
        brief = (
            "你是一位小说章节写作者。请严格按大纲切片撰写本章正文。\n"
            f"【章节大纲】{chapter['description']}\n"
            f"【角色摘要】{character_summary}\n"
            "【风格/偏好注入】遵循项目写作风格与用户偏好（偏好优先于通用文风）。"
        )
        if audit_issues:
            brief += "\n【审校意见（修订必改）】" + "；".join(audit_issues)
        return brief

    async def _delegate_audit(self, chapter: dict) -> dict:
        """审校委托：audit_callable 注入优先，否则 llm_client.chat（非决策调用）."""
        messages = [
            ChatMessage(
                role="system",
                content="你是小说章节质量审校员。请审校章节正文并输出 JSON 质量评估。",
            ),
            ChatMessage(
                role="user",
                content=(
                    f"请审校章节《{chapter.get('name', '')}》：{chapter.get('description', '')}。"
                    '输出格式：{"score": <0-100 整数>, "issues": ["<问题1>", ...]}。'
                ),
            ),
        ]
        if self._audit_callable is not None:
            response = await self._audit_callable(messages)
        else:
            response = await self._llm.chat(messages)  # type: ignore[attr-defined]  # 鸭子类型：llm_client 按 F29 契约提供 async chat(messages)
        return _parse_audit(str(getattr(response, "content", "")))
