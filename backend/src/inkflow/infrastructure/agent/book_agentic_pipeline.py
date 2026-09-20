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
from loguru import logger

from inkflow.domain.models.agent_book import AgenticBookConfig
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.domain.services.chapter_brief import (
    ContextBuilder,
    ProjectConfigGetter,
    build_book_task_context,
    build_chapter_brief,
    chapter_write_messages,
    record_word_deviation,
    resolve_brief_setting,
)
from inkflow.domain.services.usage_accounting import (
    chat_response_usage,
    guard_empty_chapter_content,
    result_usage,
)
from inkflow.infrastructure.agent._audit_bridge import (
    audit_event,
    blocking_update,
    build_audit_messages,
    persist_chapter_body,
    read_draft_body,
    read_draft_content,
    report_to_audit_dict,
)
from inkflow.infrastructure.agent.book_agentic_helpers import (
    _bump_chapter_ops,
    _chapter_failed,
    _chapter_written,
    _counter_update,
    _extract_final_content,
    _find_chapter,
    _first_unaudited_written,
    _parse_audit,
    _parse_decision,
    _plan_to_dict,
    _restore_plan,
    _usage_event,
)
from inkflow.logging import instrument

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
    # #1267：审计阻断记录 {outline_id: 原因}——非空即「因审计阻断」，停止后续章节
    audit_blocked: Annotated[dict[str, str], operator.or_]
    route_history: Annotated[list[str], lambda a, b: a + b]
    usage: Annotated[list[dict], operator.add]
    steps: int
    consecutive: int
    last_op: str
    finished: bool
    status: NotRequired[str]
    # 内部路由键（镜像 F29 _abort/hitl_pending）：target_outline_id = 当前决策目标章，
    # chapter_ops = 各章 write/audit/revise 累计次数（章节循环护栏数据源）
    target_outline_id: NotRequired[str]
    chapter_ops: NotRequired[dict[str, int]]
    # #1186 P2-a：书任务上下文段（书名/大纲切片/风格偏好/角色摘要）——bootstrap 解析一次，
    # 决策消息直接读 state（决策最多重试 4 次，不重复 await 装配层取值）
    book_context: NotRequired[str]
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
    """组装决策消息：system（书任务上下文+操作池+各章状态+书进度+路由历史+护栏，含「决策」字样）
    + user（结构化 JSON 要求；重试时重申路由历史）."""
    system_prompt = config.supervisor_prompt or _DEFAULT_SUPERVISOR_PROMPT
    chapter_lines = "\n".join(
        f"- {ch.get('name', '')}（outline_id={ch.get('outline_id')}，状态="
        f"{state.get('progress', {}).get(str(ch.get('outline_id', '')), 'pending')}）"
        for ch in state["chapters"]
    )
    # #1186 P2-a：书任务上下文段（bootstrap 已解析；缺失 → 整段省略，不落占位符）
    book_context = str(state.get("book_context", "")).strip()
    context_section = f"{book_context}\n\n" if book_context else ""
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
        f"{context_section}"
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
) -> tuple[str, str, str, list[dict]]:
    """LLM 决策循环：chat → 解析；空 content / 解析失败 / 异常 → 重试至多 3 次 → ("", "", "").

    #902：每次成功 chat（content 解析 OK）→ 产出 usage 事件（source="decision"，
    chapter=target outline_id 或 ""）；失败/异常 attempt 无 response → 零事件（防伪计费）。
    """
    llm = state["llm_client"]
    config = pipeline._config
    events: list[dict] = []
    for attempt in range(_MAX_DECISION_ATTEMPTS):
        messages = _build_decision_messages(state, config, attempt)
        try:
            response = await llm.chat(messages)  # type: ignore[attr-defined]  # 鸭子类型：llm_client 提供 async chat(messages)
        except Exception:
            continue
        content = str(getattr(response, "content", ""))
        parsed = _parse_decision(content)
        if parsed is not None:
            prompt_tokens, completion_tokens, total_tokens = chat_response_usage(response)
            events.append(
                {
                    "source": "decision",
                    "chapter": parsed[2],
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            )
            return (parsed[0], parsed[1], parsed[2], events)
    return ("", "", "", events)


@instrument(caller_type="agent")
async def _supervisor_node(state: BookAgenticState, pipeline: BookAgenticPipeline) -> Command[Any]:
    """LLM 决策下一个 book-level 操作 → Command(goto)；护栏在决策后强制（F29 模式）.

    #902：决策 chat 的 usage 事件并入本节点 Command update（decision 事件每成功
    response 恰一，跨 checkpoint 持久化）。
    """
    config = pipeline._config
    # #1267 审计阻断闸：任一章审计出阻断级 finding → 停止后续章节（不静默继续），
    # 已完成产出保留（progress/results 不动，收尾由 execute 落 needs_review + 原因）。
    # 放在 LLM 决策之前：阻断后连决策请求都不再发（确定性停止，不依赖模型自觉）。
    if state.get("audit_blocked"):
        blocked_id = next(iter(state["audit_blocked"]), "")
        logger.warning("#1267 审计阻断生效，停止后续章节：chapter={}", blocked_id)
        return Command(update={"finished": True, "status": "blocked"}, goto=END)
    action, op, oid, decision_events = await _decide_next_action(state, pipeline)
    if action == "":
        # 决策重试耗尽 / 异常：fallback_on_error=false → 直接中止；默认 → 确定性兜底
        if not config.fallback_on_error:
            return Command(
                update={"finished": True, "status": "aborted", "usage": decision_events},
                goto=END,
            )
        return Command(
            update={"route_history": ["__fallback__"], "usage": decision_events}, goto="fallback"
        )
    if action == "finish":
        goto = "hitl" if "finish" in config.hitl_points else "finish_book"
        return Command(
            update={"route_history": ["finish_book"], "usage": decision_events}, goto=goto
        )
    if action == "fallback":
        return Command(
            update={"route_history": ["__fallback__"], "usage": decision_events}, goto="fallback"
        )
    # action == "goto"
    guarded = _guarded_route(state, config, op, oid)
    if guarded is None:
        if not config.fallback_on_error:
            return Command(
                update={"finished": True, "status": "aborted", "usage": decision_events},
                goto=END,
            )
        return Command(
            update={"route_history": ["__fallback__"], "usage": decision_events}, goto="fallback"
        )
    op, oid = guarded
    return Command(
        update={
            "route_history": [op],
            "target_outline_id": oid,
            "usage": decision_events,
        },
        goto=op,
    )


@instrument(caller_type="agent")
async def _bootstrap_node(state: BookAgenticState, pipeline: BookAgenticPipeline) -> Command[Any]:
    """启动节点：注入 llm_client（UntrackedValue）+ 书任务上下文（#1186 P2-a 解析一次）；
    hitl_points 含 book_start → 先走 hitl.

    恒返回 Command(goto=...)：bootstrap 无静态出边（Spike ② 教训——Command 与静态边
    并存会 fan-out）。
    """
    update: dict[str, object] = {
        "llm_client": pipeline._llm,
        # #1186 P2-a：决策输入的书任务上下文在此解析一次写入 state —— 后续每次决策
        # （含重试 4 次 / 各操作节点回环）只读 state，不重复 await 装配层取值
        "book_context": await pipeline._resolve_book_context(state),
    }
    goto = "hitl" if "book_start" in pipeline._config.hitl_points else "book_supervisor"
    return Command(update=update, goto=goto)


@instrument(caller_type="agent")
async def _hitl_node(state: BookAgenticState, pipeline: BookAgenticPipeline) -> Command[Any]:
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


@instrument(caller_type="agent")
async def _write_chapter(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """write_chapter：writer_factory → agent.invoke → draft_service.create → 落盘增量.

    失败重试 retry_limit 次 → 标记 failed（supervisor 后续决策跳过/重写/兜底）。
    #902：成功委托产 write usage 事件；失败路径零事件（防伪计费）。
    """
    oid = state.get("target_outline_id", "")
    chapter = _find_chapter(state["chapters"], oid)
    if chapter is None:
        return _chapter_failed(state, "write_chapter", oid)
    execution_id, event = await pipeline._write_with_retry(chapter)
    if execution_id is None:
        return _chapter_failed(state, "write_chapter", oid)
    return _chapter_written(state, "write_chapter", oid, execution_id, event)


@instrument(caller_type="agent")
async def _audit_chapter(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """audit_chapter：注入 F34 服务优先，否则 audit_callable / llm_client.chat → audit_results.

    #1174：审计输入是本章**正文**——从 state["results"][oid]（= execution_id = draft id）
    经 draft_service 取回后传入；取不到 → content=""，由 _delegate_audit 草稿回读兜底。
    #902：成功审校 chat → audit usage 事件（source="audit"）；异常 → 零事件。
    """
    oid = state.get("target_outline_id", "")
    chapter = _find_chapter(state["chapters"], oid)
    update = _counter_update(state, "audit_chapter")
    audit: dict = {"score": 0, "issues": [], "character_drift": [], "setting_drift": []}
    event: dict | None = None
    if chapter is not None:
        try:
            body = await read_draft_content(
                pipeline._draft_service, str(state.get("results", {}).get(oid, ""))
            )
            audit, event = await pipeline._delegate_audit(chapter, content=body)
        except Exception:
            audit = {"score": 0, "issues": [], "character_drift": [], "setting_drift": []}
    extra: dict[str, object] = {
        "audit_results": {oid: audit},
        "usage": [event] if event is not None else [],
    }
    if chapter is not None:
        extra["chapter_ops"] = _bump_chapter_ops(state, oid)
        # #1267 消费方：审计结论必须影响流程——阻断级 finding → 记录「因审计阻断」
        extra.update(blocking_update(oid, audit))
    return {**update, **extra}


@instrument(caller_type="agent")
async def _revise_chapter(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """revise_chapter：按 audit 意见改写 → draft_service.create 重新落盘 → 更新 results.

    #902：revise 内 write 委托成功 → write usage 事件（chapter=目标 outline_id）。
    """
    oid = state.get("target_outline_id", "")
    chapter = _find_chapter(state["chapters"], oid)
    if chapter is None:
        return _chapter_failed(state, "revise_chapter", oid)
    audit = state.get("audit_results", {}).get(oid, {})
    audit_issues = [str(i) for i in audit.get("issues", [])] if isinstance(audit, dict) else []
    execution_id, event = await pipeline._write_with_retry(chapter, audit_issues=audit_issues)
    if execution_id is None:
        return _chapter_failed(state, "revise_chapter", oid)
    return _chapter_written(state, "revise_chapter", oid, execution_id, event)


@instrument(caller_type="agent")
async def _mark_done(state: BookAgenticState, pipeline: BookAgenticPipeline) -> Command[Any]:
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


@instrument(caller_type="agent")
async def _finish_book(state: BookAgenticState) -> Command[Any]:
    """finish_book：finished=True → END（status=completed）."""
    return Command(update={"finished": True, "status": "completed"}, goto=END)


@instrument(caller_type="agent")
async def _fallback_node(
    state: BookAgenticState, pipeline: BookAgenticPipeline
) -> dict[str, object]:
    """fallback：剩余未 done 章一次 write 完成（确定性兜底，R10）；静态边 → END.

    #902：fallback 内 write 委托成功 → write usage 事件（每成功章恰一）。
    """
    progress = dict(state.get("progress", {}))
    results: dict[str, str] = {}
    usage_events: list[dict] = []
    # #1267 审计阻断闸：兜底路径同样受阻断约束（否则「决策重试耗尽 → fallback」
    # 会绕过阻断继续把后续章写完，阻断形同虚设）。
    blocked = state.get("audit_blocked") or {}
    if blocked:
        logger.warning("#1267 审计阻断生效，兜底路径不再续写：{}", sorted(blocked))
        return {
            "progress": progress,
            "results": results,
            "usage": usage_events,
            "finished": True,
            "status": "blocked",
        }
    for chapter in state["chapters"]:
        oid = str(chapter["outline_id"])
        if progress.get(oid) == "done":
            continue
        execution_id, event = await pipeline._write_with_retry(chapter)
        if execution_id is None:
            progress[oid] = "failed"
            results[oid] = "failed"
        else:
            progress[oid] = "done"
            results[oid] = execution_id
            if event is not None:
                usage_events.append(event)
            if pipeline._plan is not None:
                pipeline._plan.execution_refs[oid] = execution_id
    return {
        "progress": progress,
        "results": results,
        "usage": usage_events,
        "finished": True,
        "status": "completed",
    }


class BookAgenticPipeline:
    """book-level 自主编排引擎（镜像 F29 supervisor + F44 checkpoint/HITL 结构）."""

    def __init__(
        self,
        llm_client: object,
        *,
        writer_factory: Callable[..., Awaitable[object]] | None = None,
        draft_service: object | None = None,
        audit_callable: Callable[..., Awaitable[object]] | None = None,
        audit_service: object | None = None,
        chapter_service: object | None = None,
        retry_limit: int = 2,
        checkpointer: InMemorySaver | None = None,
        checkpoint_path: str | Path | None = None,
        context_builder: ContextBuilder | None = None,
        project_config_getter: ProjectConfigGetter | None = None,
        volume_lookup: Callable[[uuid.UUID, uuid.UUID | None], Awaitable[str | None]] | None = None,
    ) -> None:
        """构造：llm_client 经 UntrackedValue 注入（不参与 checkpointer 序列化，R7）.

        checkpointer 显式传入 → 优先使用（不打开文件）；否则 checkpoint_path → 每次
        execute/resume 临时打开 AsyncSqliteSaver 文件后端（跨实例/跨进程 resume 可行）；
        两者皆无 → 进程内 InMemorySaver。

        volume_lookup: #976 卷解析回调（镜像 F44 BookVolumePipeline）——缺失 → 兜底
            草稿不归卷（volume_id=None），既有装配不受影响。
        """
        self._llm = llm_client
        self._writer_factory = writer_factory
        self._draft_service = draft_service
        self._audit_callable = audit_callable
        self._audit_service = audit_service
        self._chapter_service = chapter_service
        self._context_builder = context_builder
        self._project_config_getter = project_config_getter
        self._volume_lookup = volume_lookup
        self._retry_limit = retry_limit
        if checkpointer is None and checkpoint_path is None:
            checkpointer = InMemorySaver()
        self._checkpointer = checkpointer
        self._checkpoint_path = checkpoint_path
        self._thread_id = ""
        self._plan: WritingPlan | None = None
        self._limits = BookLimits()
        self._config = AgenticBookConfig()

    async def _resolve_book_context(self, state: BookAgenticState) -> str:
        """书任务上下文段装配（#1186 P2-a）：解析 setting → 委托域层渲染.

        渲染实现在 :func:`chapter_brief.build_book_task_context`（域层单一实现点）；
        本方法只负责装配层取值（project_config_getter / context_builder）。
        书级决策取首章为 F6 设定上下文代表（``get_context`` 按项目注入，忽略章参）。
        """
        plan = self._plan
        if plan is None:
            return ""
        chapters: list[dict] = state["chapters"]
        chapter: object = chapters[0] if chapters else None
        project_config: object | None = (
            await self._project_config_getter(plan.project_id)
            if self._project_config_getter is not None
            else None
        )
        setting = await resolve_brief_setting(self._context_builder, project_config, plan, chapter)
        return build_book_task_context(plan, chapters, setting)

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

    @instrument(caller_type="agent")
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
                "audit_blocked": {},
                "route_history": [],
                "usage": [],
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
            self._finalize_audit_block(plan, final_dict)
            return {
                "run_id": self._thread_id,
                "status": str(final_dict.get("status", "completed")),
                "thread_id": self._thread_id,
            }

        return await self._run_with_checkpointer(_run, thread_id=self._thread_id)

    @staticmethod
    def _finalize_audit_block(plan: WritingPlan, final: dict[str, Any]) -> None:
        """#1267 全自动轨收尾：审计阻断 → 状态落库可查（复用既有字段，零新增 DB 字段）.

        - 被阻断的章 ``progress[oid] = "needs_review"``（待人工介入，issue 原话语义）
        - ``progress_reason`` = 审计阻断原因（用户在 run 详情可读，不静默）
        - ``plan.status`` 由 BookService.write_book_agentic 按 execute 返回值落库
          （"blocked"；进度/reason 在此就地写，因 plan 为共享引用）

        非阻断（无 ``audit_blocked``）→ 不动 plan（保持既有收尾语义）。
        """
        blocked: dict = final.get("audit_blocked") or {}
        if not blocked:
            return
        reasons: list[str] = []
        for oid, reason in blocked.items():
            plan.progress[oid] = "needs_review"
            reasons.append(str(reason))
        plan.progress_reason = "\n".join(reasons)[:2000]
        logger.warning(
            "#1267 审计阻断收尾：{} 章标记 needs_review，run 状态置 blocked", len(blocked)
        )

    @instrument(caller_type="agent")
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
            snapshot = await app.aget_state(config={"configurable": {"thread_id": self._thread_id}})
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

    @instrument(caller_type="agent")
    async def get_checkpoint_state(self, run_id: str) -> dict | None:
        """查询图状态（BookAgenticState 键）；无 checkpoint → None."""

        async def _read(
            app: CompiledStateGraph[BookAgenticState, Any, Any, Any],
        ) -> dict | None:
            snapshot = await app.aget_state(config={"configurable": {"thread_id": run_id}})
            values: dict = snapshot.values
            return values if values else None

        return await self._run_with_checkpointer(_read, thread_id=run_id)

    @instrument(caller_type="agent")
    def _require_deps(self, *, writer: bool = False, drafts: bool = False) -> WritingPlan:
        """装配守卫（#1186 收敛三条重复 ``raise ValueError("… 未装配")``）→ plan."""
        if self._plan is None:
            raise ValueError("plan 未装配")
        if writer and self._writer_factory is None:
            raise ValueError("writer_factory 未装配")
        if drafts and self._draft_service is None:
            raise ValueError("draft_service 未装配")
        return self._plan

    async def _chapter_deps(self, plan: WritingPlan, chapter: dict) -> tuple[str, dict[str, Any]]:
        """章 brief 装配（#1186 收敛 `_delegate_write`/`_revise_chapter` 重复取值）.

        返回 ``(system_prompt, brief_inputs)``：后者供调用方取 ``default_words``
        （消息构造 :func:`chapter_write_messages` 与字数偏差记录
        :func:`record_word_deviation` 共用），避免重复 ``resolve_brief_setting``。
        """
        cfg: object | None = (
            await self._project_config_getter(plan.project_id)
            if self._project_config_getter is not None
            else None
        )
        brief_inputs = await resolve_brief_setting(self._context_builder, cfg, plan, chapter)
        return self._build_chapter_brief(plan, chapter, **brief_inputs), brief_inputs

    async def _write_with_retry(
        self, chapter: dict, *, audit_issues: list[str] | None = None
    ) -> tuple[str | None, dict | None]:
        """委托写作 + retry_limit 重试（#1186 收敛 write/revise/fallback 三处逐字重复的重试环）.

        全部尝试失败 → (None, None)（调用方按失败路径落 progress=results=failed）。
        """
        for _ in range(1 + self._retry_limit):
            try:
                return await self._delegate_write(chapter, audit_issues=audit_issues)
            except Exception:  # 逐次重试语义：单次失败不中断，交由下轮
                continue
        return None, None

    async def _delegate_write(
        self, chapter: dict, *, audit_issues: list[str] | None = None
    ) -> tuple[str, dict]:
        """委托章写作（镜像 F44 _delegate_chapter）：章 brief → writer_factory →
        agent.invoke → draft_service.create 回收 → (execution_id, usage 事件).

        #902：usage 事件只来自真实 invoke 结果（messages usage_metadata / 顶层 usage），
        双源皆缺 → 全零事件（无伪计费）；source="write"、chapter=str(outline_id)。
        """
        plan = self._require_deps(writer=True, drafts=True)
        system_prompt, brief_inputs = await self._chapter_deps(plan, chapter)
        if audit_issues:
            system_prompt += "\n【审校意见（修订必改）】" + "；".join(audit_issues)
        agent = await self._writer_factory(  # type: ignore[misc]  # 已过 _require_deps 守卫
            system_prompt=system_prompt,
            expected_project_id=plan.project_id,
            expected_chapter_id=chapter["chapter_id"],
            expected_source_outline_id=chapter["outline_id"],
            expected_volume_outline_id=chapter.get("volume_outline_id"),
        )
        messages = chapter_write_messages(system_prompt, chapter, brief_inputs["default_words"])
        result = await agent.invoke(  # type: ignore[union-attr]  # 鸭子类型：agent 按 F27 契约提供 async invoke(messages, config)（_require_deps 守卫无法收窄 Optional 工厂）
            messages, config={"configurable": {"thread_id": self._thread_id}}
        )
        prompt_tokens, completion_tokens, total_tokens = result_usage(result)

        async def _invoke_again() -> str:
            """#1316 空产出重试：重新委托一次（token 并入本事件，计费口径不丢）."""
            nonlocal prompt_tokens, completion_tokens, total_tokens
            retried = await agent.invoke(  # type: ignore[union-attr]  # 鸭子类型：agent 按 F27 契约提供 async invoke(messages, config)（_require_deps 守卫无法收窄 Optional 工厂）
                messages, config={"configurable": {"thread_id": self._thread_id}}
            )
            retry_prompt, retry_completion, retry_total = result_usage(retried)
            prompt_tokens += retry_prompt
            completion_tokens += retry_completion
            total_tokens += retry_total
            return _extract_final_content(retried)

        content = await guard_empty_chapter_content(
            _extract_final_content(result), invoke=_invoke_again, chapter_name=chapter["name"]
        )
        record_word_deviation(content, brief_inputs["default_words"], chapter_name=chapter["name"])
        draft = await self._draft_service.create(  # type: ignore[union-attr]  # 鸭子类型：draft_service 按 F27 契约提供 async create
            project_id=plan.project_id,
            chapter_id=chapter["chapter_id"],
            content=content,
            summary="书级 agent 编排保存",
            volume_id=await self._resolve_draft_volume(plan, chapter),
            source_outline_id=chapter["outline_id"],
        )
        execution_id = str(getattr(draft, "id", ""))
        return (
            execution_id,
            _usage_event(
                "write",
                str(chapter["outline_id"]),
                prompt_tokens,
                completion_tokens,
                total_tokens,
            ),
        )

    async def _resolve_draft_volume(self, plan: WritingPlan, chapter: dict) -> uuid.UUID | None:
        """#976 D3/D5：委托落草稿卷解析（volume_lookup 未装配/无映射/解析失败 → None）.

        查表键：章 dict 的 ``volume_outline_id``（卷 outline 节点 id）优先，回退
        ``outline_id``（章 dict 恒含）；str/UUID 双形态容错归一为 UUID。
        """
        if self._volume_lookup is None:
            return None
        lookup_id = chapter.get("volume_outline_id") or chapter["outline_id"]
        volume_raw = await self._volume_lookup(plan.project_id, lookup_id)
        if volume_raw is None:
            return None
        try:
            return volume_raw if isinstance(volume_raw, uuid.UUID) else uuid.UUID(str(volume_raw))
        except (TypeError, ValueError):
            return None

    # #1185：章 brief 三轨副本收敛——本轨直接复用 domain 单一实现（签名见 chapter_brief）
    _build_chapter_brief = staticmethod(build_chapter_brief)

    @instrument(caller_type="agent")
    async def _delegate_audit(self, chapter: dict, *, content: str = "") -> tuple[dict, dict]:
        """审校委托（优先级）：注入 F34 服务 → audit_callable → llm_client.chat.

        #1174：审计输入是本章**正文**（content 参数；空 → 回读该章最新草稿），
        不再喂 chapter["description"]（大纲描述）。
        #1177：F34 分支把四项检查（人设/设定漂移 + 字数 + 静态）映射为契约 dict
        （character_drift/setting_drift/issues/score/findings）。
        #902：返回 (audit, usage 事件)——事件 source="audit"、chapter=str(outline_id)；
        F34 分支无 chat 响应 → 全零事件（防伪计费）。
        """
        messages = build_audit_messages(chapter, content)
        project_id = getattr(self._plan, "project_id", None)
        chapter_id = chapter.get("chapter_id")
        if self._audit_service is not None and chapter_id is not None:
            text = content
            if not text.strip():
                text = await read_draft_body(self._draft_service, project_id, chapter)
            if text.strip() and await persist_chapter_body(self._chapter_service, chapter_id, text):
                report = await self._audit_service.audit(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按 F34 契约提供 async audit(project_id, chapter_id, include_static=...)
                    project_id, chapter_id, include_static=True
                )
                return (report_to_audit_dict(report), audit_event(chapter, None))
        if self._audit_callable is not None:
            response = await self._audit_callable(messages)
        else:
            response = await self._llm.chat(messages)  # type: ignore[attr-defined]  # 鸭子类型：llm_client 按 F29 契约提供 async chat(messages)
        return (
            _parse_audit(str(getattr(response, "content", ""))),
            audit_event(chapter, response),
        )
