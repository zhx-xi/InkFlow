"""F44 卷级编排图（#337 阶段 3 + #1187 承接两阶段）— Send map-reduce 并行扇出
 + 写前承接（B）+ 卷级审计（C）+ 卷边界 HITL + 失败恢复策略树.

BookVolumePipeline 镜像 SupervisorPipeline（F29）结构：execute 抛 VolumeHITLInterrupt，
resume 从 checkpointer 恢复。图拓扑（Spike ①-④ 实证形态，父侧契约定稿）：
    START → bootstrap（UntrackedValue 注入 llm_client，镜像 F29）
        → prepare_continuity（#1187 B：扇出前一次 LLM 调用生成整卷承接表，不读正文）
        → volume_fan_out（Command(goto=[Send("write_chapter", ...)])，非 return [Send(...)]）
          → write_chapter 并行分支（节点内无 interrupt，章级重试 N 次；brief 注入本章承接）
          → join（map-reduce 回收；results 通道 Annotated[dict, operator.or_] reducer）
          → join 判定顺序: ① 护栏（累计步数 >= max_agent_calls → END/aborted）
            ② 卷级失败（该卷全部章 failed → volume_failure）
            ③ 最后一卷（→ volume_audit → END）/ 其余（→ volume_audit）
        → volume_audit（#1187 C：逐章 F34 审计 + #1267 阻断判定；纯计算无 interrupt）
        → volume_boundary（interrupt 串行点）→ resume approved → 下一卷 / END
        → volume_failure（interrupt）→ resume decision: continue / abort / supervisor

依据: specs/f44-book-orchestrator/spec.md §5.3/§12 D1-D3/D9/§13.3 M7-M9 + v1.10（#1187）
    + .hermes/plans/f44-stage3-contract.md §1（父侧裁定，语义冲突以它为准）
    + docs/f44-orchestrator-spike-2026-08-17.md ①-④（Spike 实证形态）。

F44 阶段 4（#338）扩展：checkpoint_path 装配 AsyncSqliteSaver 文件后端 + thread_id
语义 + 跨重启 resume（父侧契约 .hermes/plans/f44-stage4-contract.md §1）。
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
from langgraph.types import Command, Send, interrupt
from loguru import logger

from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.services.chapter_brief import (
    ContextBuilder,
    ProjectConfigGetter,
    build_chapter_brief,
    chapter_write_messages,
    record_word_deviation,
    resolve_brief_setting,
)
from inkflow.domain.services.usage_accounting import (
    ChapterContentEmptyError,  # noqa: F401  # #1316 契约：须与 book_service 导出同一异常符号（is 判定）
    _extract_saved_draft_id,
    chat_response_usage,
    draft_fallback_needed,
    guard_empty_chapter_content,
    result_usage,
)
from inkflow.infrastructure.agent._audit_bridge import blocking_update, report_to_audit_dict
from inkflow.infrastructure.llm.content_text import content_text
from inkflow.logging import instrument

_R = TypeVar("_R")


class VolumeState(TypedDict):
    """卷级编排图状态 — 镜像 PipelineState.results reducer 模式（Spike ② 必备）。"""

    context: dict[str, Any]
    chapters: list[dict]
    volumes: list[dict]
    plan: dict
    limits: dict
    results: Annotated[dict[str, str], operator.or_]
    # #1187 B：整卷承接表 {str(outline_id): {"carry": 开头承接, "hook": 章末钩子}}——
    # 普通 dict 通道（非 reducer）：每卷开始时由 prepare_continuity 整体覆盖/重算。
    continuity: dict[str, dict]
    # #1187 C：审计阻断记录 {outline_id: 原因}——镜像 book_agentic_pipeline 同名通道
    audit_blocked: Annotated[dict[str, str], operator.or_]
    failed: Annotated[list[str], operator.add]
    volume_index: int
    total_volumes: int
    retries: int
    steps: Annotated[int, operator.add]
    usage: Annotated[list[dict], operator.add]
    finished: bool
    status: NotRequired[str]
    llm_client: Annotated[object, UntrackedValue(object)]


class VolumeHITLInterrupt(Exception):  # noqa: N818  # 测试契约要求精确类名 VolumeHITLInterrupt（不可用 Error 后缀）
    """卷级 HITL 中断 — interrupt() 暂停，payload 供 BookService 存 waiting_hitl。"""

    def __init__(self, payload: dict) -> None:
        super().__init__(payload)
        self.payload = payload


def _extract_final_content(result: dict[str, Any]) -> str:
    """从 agent.invoke 结果（dict，含 "messages"）提取最终 message content（镜像 BookService）。"""
    messages = result.get("messages", [])
    if not messages:
        return ""
    final = messages[-1]
    content = getattr(final, "content", None)
    if content is None and isinstance(final, dict):
        content = final.get("content")
    if content is None:
        return ""
    # #1262：content 可能是 structured content blocks（list[dict]）——统一走归一器，
    # 避免 str() 把 list repr（含 thinking 文本）当正文。
    return content_text(content)


def _parse_supervisor_decision(content: str) -> str:
    """解析 supervisor 补救决策 JSON → "continue" | "abort"；空 content/解析失败默认 continue。

    宽松解析（镜像 F29 _parse_decision）：LLM 可能返回 markdown 代码块围栏包裹的
    JSON（如 ```json\\n{...}\\n```），先试完整解析，失败则提取首个 { 到末个 } 子串。
    """
    data: dict | None = None
    if content.strip():
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and start < end:
                try:
                    data = json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    data = None
    if not isinstance(data, dict):
        return "continue"
    return "abort" if data.get("action") == "abort" else "continue"


def _parse_continuity_table(content: str) -> dict[str, dict]:
    """解析整卷承接表 JSON → {str(outline_id): {"carry": str, "hook": str}}.

    宽松解析（镜像 `_parse_supervisor_decision`）：LLM 可能用 markdown 代码块围栏包裹
    （```json\\n{...}\\n```），先试完整解析，失败则提取首个 `{` 到末个 `}` 子串。
    任何形态不符（非 dict / 值非 dict）→ 丢弃该项；整体解析失败 → 空表（降级不阻断写作）。
    """
    data: object = None
    if content.strip():
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and start < end:
                try:
                    data = json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    data = None
    if not isinstance(data, dict):
        return {}
    table: dict[str, dict] = {}
    for outline_id, entry in data.items():
        if not isinstance(entry, dict):
            continue
        table[str(outline_id)] = {
            "carry": str(entry.get("carry") or ""),
            "hook": str(entry.get("hook") or ""),
        }
    return table


def _continuity_messages(volume: dict, chapters: list[dict]) -> list[dict[str, str]]:
    """构造承接表提示词（#1187 B）——输入只有大纲面：卷纲 + 各章章纲 + 前一章章纲.

    扇出前无任何正文，故承接依据只能是「卷纲 + 章纲」；章 `outline_id` 必须进提示词
    （LLM 用它做承接表的键）。
    """
    lines: list[str] = []
    previous = "（本章为卷首，无前一章）"
    for chapter in chapters:
        lines.append(
            f"- outline_id={chapter['outline_id']}｜章名：{chapter.get('name', '')}"
            f"｜本章章纲：{chapter.get('description', '')}"
            f"｜前一章章纲：{previous}"
        )
        previous = f"{chapter.get('name', '')}：{chapter.get('description', '')}"
    return [
        {
            "role": "system",
            "content": (
                "你是小说卷级承接规划员：同卷各章将被并行写作（互不知情），"
                "你的职责是给出每章开头的承接点与章末钩子，使并行成稿仍前后连贯。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"【本卷卷纲】{volume.get('description', '') or '（无卷纲，请仅依据章纲推断）'}\n"
                "【本卷各章章纲】\n" + "\n".join(lines) + "\n请输出 JSON："
                '{"<outline_id>": {"carry": "本章开头应承接什么", '
                '"hook": "本章结尾应留下什么"}, ...}，'
                "覆盖本卷每一章，不要输出任何其他文字。"
            ),
        },
    ]


def _continuity_segment(continuity: dict | None) -> str:
    """本章承接段（追加进章 brief）——carry/hook 任一为空则该行不追加；皆空 → 空串."""
    if not continuity:
        return ""
    lines: list[str] = []
    carry = str(continuity.get("carry") or "")
    hook = str(continuity.get("hook") or "")
    if carry:
        lines.append(f"【上一章结尾】{carry}")
    if hook:
        lines.append(f"【本章结尾钩子】{hook}")
    return "\n" + "\n".join(lines) if lines else ""


@instrument(caller_type="agent")
async def _bootstrap_node(state: VolumeState, llm_client: object) -> dict[str, object]:
    """启动节点：将 llm_client 写入 UntrackedValue 通道（不参与 checkpointer 序列化，镜像 F29）。"""
    return {"llm_client": llm_client}


@instrument(caller_type="agent")
async def _prepare_continuity(
    state: VolumeState, pipeline: BookVolumePipeline
) -> dict[str, object]:
    """B 阶段（#1187）：扇出前一次 LLM 调用生成整卷承接表 → VolumeState["continuity"].

    位置硬约束：必须在 `volume_fan_out` 之前——扇出后各分支同时启动，拿不到任何前章
    正文；承接只能依赖大纲面（卷纲 + 各章章纲 + 前一章章纲）。LLM 异常/解析失败 →
    空承接表（降级不阻断写作）。
    """
    return {"continuity": await pipeline._build_continuity(state)}


@instrument(caller_type="agent")
async def _volume_fan_out(state: VolumeState) -> Command[Any]:
    """卷扇出：Command(goto=[Send("write_chapter", {...}) ...])——Spike ① 形态。

    非 return [Send(...)]（LangGraph 1.2.10 报 InvalidUpdateError）；空卷直接 goto join 回收。
    #1187 B：payload 携带本章承接（carry/hook），分支 state 即 payload（Send 全量替换）。
    """
    if not state["chapters"]:
        return Command(goto="join")
    continuity = state.get("continuity") or {}
    return Command(
        goto=[Send("write_chapter", _fan_out_payload(ch, continuity)) for ch in state["chapters"]]
    )


def _fan_out_payload(chapter: dict, continuity: dict) -> dict:
    """章分支 payload：本章 dict + 本章承接（隔离性——只带本章 carry/hook，不串他章）."""
    entry: object = continuity.get(str(chapter["outline_id"]))
    entry = entry if isinstance(entry, dict) else {}
    return {
        "chapter": chapter,
        "carry": str(entry.get("carry") or ""),
        "hook": str(entry.get("hook") or ""),
    }


@instrument(caller_type="agent")
async def _write_chapter(state: VolumeState, pipeline: BookVolumePipeline) -> dict[str, object]:
    """章执行节点（Send 并行分支，节点内无 interrupt——Spike ④ 硬约束）。

    执行 = writer_factory(system_prompt=章 brief, expected_project_id, expected_chapter_id)
    → agent.invoke([...]) → draft_service.create(...) → 返回 results 增量。
    任一步抛异常 → 重试整章（重新调用 writer_factory），至多 retry_limit 次重试
    （总尝试 1 + retry_limit）；仍失败 → 章级只报告 failed，不阻塞其他章。

    #1187 B：分支 state = Send payload（含本章承接 carry/hook），原样传给 _delegate_chapter
    注入本章 brief（隔离性：分支只拿到本章承接）。
    """
    branch = cast(dict[str, Any], state)
    chapter: dict = branch["chapter"]
    outline_id = str(chapter["outline_id"])
    continuity = {"carry": branch.get("carry", ""), "hook": branch.get("hook", "")}
    attempts = 0
    usage_events: list[dict] = []
    for _ in range(1 + pipeline._retry_limit):
        attempts += 1
        try:
            execution_id, event = await pipeline._delegate_chapter(chapter, continuity=continuity)
        except Exception:
            # 任一步异常 → 重试整章（循环再次调用 writer_factory）
            continue
        else:
            usage_events.append(event)
            return {
                "results": {outline_id: execution_id},
                "steps": attempts,
                "usage": usage_events,
            }
    return {"results": {outline_id: "failed"}, "failed": [outline_id], "steps": attempts}


@instrument(caller_type="agent")
async def _join(state: VolumeState, pipeline: BookVolumePipeline) -> Command[Any]:
    """map-reduce 回收节点：判定顺序 = ① 护栏 ② 卷级失败 ③ 最后一卷/卷级审计。

    #1187 C：③ 承接成功/部分成功的卷统一进入 `volume_audit`（非最后一卷由审计节点续接
    `volume_boundary`，最后一卷由审计节点收尾 END）——`join → volume_audit` 是画图边
    （`destinations`，仅渲染不影响执行），实际路由仍由本节点 Command(goto) 决定。
    """
    if state.get("steps", 0) >= pipeline._limits.max_agent_calls:
        # 预算 = max_agent_calls（每次尝试含重试消耗 1 步）；超预算终止，不抛 interrupt
        return Command(update={"finished": True, "status": "aborted"}, goto=END)
    chapters = state["chapters"]
    results = state.get("results", {})
    failed_count = sum(1 for c in chapters if results.get(str(c["outline_id"])) == "failed")
    if chapters and failed_count == len(chapters):
        # 卷级失败判定 = 该卷全部章 failed（部分失败不触发 volume_failure）
        return Command(goto="volume_failure")
    # 其余（全成功/部分失败，含最后一卷）→ volume_audit：最后一卷由审计节点收尾 END
    # （不 interrupt → execute 返回 completed），非最后一卷由审计节点续接 volume_boundary。
    return Command(goto="volume_audit")


@instrument(caller_type="agent")
async def _volume_audit(state: VolumeState, pipeline: BookVolumePipeline) -> Command[Any]:
    """C 阶段（#1187）：卷级逐章 F34 审计 + #1267 阻断判定（纯计算，无 interrupt）.

    位置：`join` 之后、`volume_boundary` 之前。无阻断 → 最后一卷 END / 其余
    volume_boundary；阻断级 finding（severity=error 且非 degraded）→ 不进入
    volume_boundary，`status="blocked"` + goto END（已完成产出保留）。
    audit_service 未装配（None）→ 行为与改造前一致（不审计，仅按卷序收尾/续接）。
    """
    update, blocked = await pipeline._audit_volume(state)
    if blocked:
        return Command(update={**update, "finished": True}, goto=END)
    if state["volume_index"] >= state["total_volumes"] - 1:
        return Command(update={"finished": True}, goto=END)
    return Command(update=update, goto="volume_boundary")


@instrument(caller_type="agent")
async def _volume_boundary(state: VolumeState, pipeline: BookVolumePipeline) -> Command[Any]:
    """卷边界 HITL 串行点（唯一允许 interrupt 的位置之一，Spike ③）：resume approved
    → 下一卷 / END；approved=False → 中止。"""
    progress = {
        str(c["outline_id"]): (
            "failed" if state.get("results", {}).get(str(c["outline_id"])) == "failed" else "done"
        )
        for c in state["chapters"]
    }
    decision: dict = interrupt(
        {
            "question": "确认继续下一卷？",
            "volume_index": state["volume_index"],
            "progress": progress,
        }
    )
    if decision.get("approved", False):
        return pipeline._goto_next_volume(state)
    return Command(update={"finished": True, "status": "aborted"}, goto=END)


@instrument(caller_type="agent")
async def _volume_failure(state: VolumeState, pipeline: BookVolumePipeline) -> Command[Any]:
    """卷级失败 HITL（§12 D9）：resume decision 分支 continue / abort / supervisor。"""
    failed = [
        str(c["outline_id"])
        for c in state["chapters"]
        if state.get("results", {}).get(str(c["outline_id"])) == "failed"
    ]
    decision: dict = interrupt({"question": "卷执行失败，如何继续？", "failed": failed})
    action = str(decision.get("decision", ""))
    if action == "supervisor":
        # 授权主 agent 补救：llm_client.chat（消息含 failed 章列表）→ 解析 action
        action, supervisor_event = await pipeline._delegate_supervisor(failed)
        if action == "abort":
            return Command(
                update={"finished": True, "status": "aborted", "usage": [supervisor_event]},
                goto=END,
            )
        # "continue"：跳过 failed 卷，继续下一卷 / END（supervisor chat 已发生 → 计费）
        return pipeline._goto_next_volume_with_usage(state, supervisor_event)
    if action == "abort":
        return Command(update={"finished": True, "status": "aborted"}, goto=END)
    # "continue"（含解析失败默认）→ 跳过 failed 卷，继续下一卷 / END
    return pipeline._goto_next_volume(state)


class BookVolumePipeline:
    """卷级编排引擎（镜像 SupervisorPipeline：execute 抛 VolumeHITLInterrupt，resume 恢复）。"""

    def __init__(
        self,
        llm_client: object,
        *,
        writer_factory: Callable[..., Awaitable[object]] | None = None,
        draft_service: object | None = None,
        retry_limit: int = 2,
        checkpointer: InMemorySaver | None = None,
        checkpoint_path: str | Path | None = None,
        volume_lookup: Callable[[uuid.UUID, uuid.UUID | None], Awaitable[str | None]] | None = None,
        context_builder: ContextBuilder | None = None,
        project_config_getter: ProjectConfigGetter | None = None,
        audit_service: object | None = None,
    ) -> None:
        """构造：llm_client 仅 UntrackedValue 通道传递（镜像 F29 bootstrap 节点），
        不参与执行决策；只在卷级失败 decision="supervisor" 补救时调用 chat。
        checkpointer 显式传入 → 优先使用（不打开文件）；否则 checkpoint_path →
        每次 execute/resume 临时打开 AsyncSqliteSaver 文件后端（跨实例/跨进程
        resume 可行）；两者皆无 → 进程内 InMemorySaver（阶段 3 默认）。

        #1187：llm_client 另用于 B 阶段 `prepare_continuity` 的整卷承接表生成（一次/卷）；
        audit_service = F34 `ChapterAuditService` 鸭子契约（未装配 None → 卷级审计透传）。
        """
        self._llm = llm_client
        self._writer_factory = writer_factory
        self._draft_service = draft_service
        self._audit_service = audit_service
        self._retry_limit = retry_limit
        self._volume_lookup = volume_lookup
        self._context_builder = context_builder
        self._project_config_getter = project_config_getter
        if checkpointer is None and checkpoint_path is None:
            checkpointer = InMemorySaver()
        self._checkpointer = checkpointer
        self._checkpoint_path = checkpoint_path
        self._thread_id = ""
        self._plan: WritingPlan | None = None
        self._volumes: list[dict] = []
        self._limits = BookLimits()

    def _build_graph(
        self, checkpointer: BaseCheckpointSaver
    ) -> CompiledStateGraph[VolumeState, Any, Any, Any]:
        """构建卷级图：bootstrap → prepare_continuity（B 写前承接）→ volume_fan_out
        → write_chapter（Send 并行）→ join → volume_audit（C 写后审计）
        → volume_boundary / volume_failure（Command(goto) 动态路由，镜像 F29）；
        checkpointer 参数化（显式 InMemorySaver 或临时 AsyncSqliteSaver）。"""
        g = StateGraph(VolumeState)
        g.add_node("bootstrap", partial(_bootstrap_node, llm_client=self._llm))
        g.add_node("prepare_continuity", partial(_prepare_continuity, pipeline=self))
        # destinations：Command/Send 型节点的画图边（仅渲染不影响执行，langgraph 语义）——
        # 缺它则图渲染在 volume_fan_out 处断链（Send 是运行时动态路由，静态不可知）。
        g.add_node("volume_fan_out", _volume_fan_out, destinations=("write_chapter", "join"))
        g.add_node("write_chapter", partial(_write_chapter, pipeline=self))
        # destinations：Command 型节点的画图边（仅渲染不影响执行，langgraph 语义）
        g.add_node(
            "join",
            partial(_join, pipeline=self),
            destinations=("volume_audit", "volume_failure"),
        )
        g.add_node(
            "volume_audit",
            partial(_volume_audit, pipeline=self),
            destinations=("volume_boundary",),
        )
        g.add_node("volume_boundary", partial(_volume_boundary, pipeline=self))
        g.add_node("volume_failure", partial(_volume_failure, pipeline=self))
        g.add_edge(START, "bootstrap")
        g.add_edge("bootstrap", "prepare_continuity")
        g.add_edge("prepare_continuity", "volume_fan_out")
        g.add_edge("write_chapter", "join")
        return g.compile(checkpointer=checkpointer)

    async def _run_with_checkpointer(
        self,
        fn: Callable[[CompiledStateGraph[VolumeState, Any, Any, Any]], Awaitable[_R]],
        *,
        thread_id: str,
    ) -> _R:
        """编译图后执行 fn：显式 checkpointer 优先；否则按 checkpoint_path 临时打开
        AsyncSqliteSaver 文件后端（async with 生命周期内编译 + 运行 + 落盘）。"""
        if self._checkpointer is not None:
            return await fn(self._build_graph(self._checkpointer))
        async with AsyncSqliteSaver.from_conn_string(str(self._checkpoint_path)) as saver:
            return await fn(self._build_graph(saver))

    @instrument(caller_type="agent")
    async def execute(
        self,
        plan: WritingPlan,
        volumes: list[dict],
        limits: BookLimits,
        *,
        thread_id: str | None = None,
    ) -> dict[str, str]:
        """跑一卷/多卷：Send 扇出全部章 → join 回收 → 卷边界 interrupt 暂停。

        thread_id 给定 → 用作图 config thread_id（与 run_id 统一，供 resume/checkpoint
        定位）；None → 内部生成 uuid4。返回 dict 增加 "thread_id" 键。

        Returns:
            {"run_id": ..., "status": "completed" | "aborted", "thread_id": ...}
            （全部卷完成或护栏终止）。
        Raises:
            VolumeHITLInterrupt: 卷边界/卷级失败暂停（payload 供 BookService 存 waiting_hitl）。
        """
        self._plan = plan
        self._volumes = volumes
        self._limits = limits
        self._thread_id = thread_id if thread_id is not None else str(uuid.uuid4())
        state = cast(
            VolumeState,
            {
                "context": {"plan_id": str(plan.id), "project_id": str(plan.project_id)},
                "chapters": volumes[0]["chapters"] if volumes else [],
                "volumes": volumes,
                "plan": plan.model_dump(mode="json"),
                "limits": limits.model_dump(),
                "results": {},
                "continuity": {},
                "audit_blocked": {},
                "failed": [],
                "volume_index": 0,
                "total_volumes": len(volumes),
                "retries": 0,
                "steps": 0,
                "usage": [],
                "finished": False,
            },
        )

        async def _run(
            app: CompiledStateGraph[VolumeState, Any, Any, Any],
        ) -> dict[str, str]:
            final = await app.ainvoke(
                state, config={"configurable": {"thread_id": self._thread_id}}
            )
            final_dict = cast(dict[str, Any], final)
            interrupts = final_dict.get("__interrupt__")
            if interrupts:
                raise VolumeHITLInterrupt(interrupts[0].value)
            return {
                "run_id": self._thread_id,
                "status": str(final_dict.get("status", "completed")),
                "thread_id": self._thread_id,
            }

        return await self._run_with_checkpointer(_run, thread_id=self._thread_id)

    @instrument(caller_type="agent")
    async def resume(
        self,
        interrupt_obj: VolumeHITLInterrupt,
        *,
        approved: bool = True,
        decision: str = "",
        thread_id: str | None = None,
    ) -> dict[str, str]:
        """卷边界/卷级失败确认后从 checkpointer 恢复（thread_id 沿用 execute 生成值）。

        thread_id 给定 → 用之（跨重启从 plan.thread_id 读取）；None → self._thread_id
        （向后兼容 execute → resume 隐式传递）。返回 dict 增加 "thread_id" 键。

        Returns:
            {"run_id": ..., "status": "completed" | "aborted", "thread_id": ...}
            或再次抛 VolumeHITLInterrupt。
        """
        self._thread_id = thread_id if thread_id is not None else self._thread_id

        async def _run(
            app: CompiledStateGraph[VolumeState, Any, Any, Any],
        ) -> dict[str, str]:
            # 跨重启 resume：从 checkpoint 恢复 plan/limits（fresh 实例无内存装配）
            snapshot = await app.aget_state(config={"configurable": {"thread_id": self._thread_id}})
            values: dict = snapshot.values
            if values.get("plan"):
                self._plan = WritingPlan(**values["plan"])
            if values.get("limits"):
                self._limits = BookLimits(**values["limits"])
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
                raise VolumeHITLInterrupt(interrupts[0].value)
            return {
                "run_id": self._thread_id,
                "status": str(final_dict.get("status", "completed")),
                "thread_id": self._thread_id,
            }

        return await self._run_with_checkpointer(_run, thread_id=self._thread_id)

    @instrument(caller_type="agent")
    async def get_checkpoint_state(self, run_id: str) -> dict | None:
        """查询图状态（VolumeState 键）；无 checkpoint → None。

        checkpoint_path 模式下临时打开文件 saver 读取（fresh 实例可从文件读到
        中断点状态，供 BookService.get_summary 的 next 数据源）。"""

        async def _read(
            app: CompiledStateGraph[VolumeState, Any, Any, Any],
        ) -> dict | None:
            snapshot = await app.aget_state(config={"configurable": {"thread_id": run_id}})
            values: dict = snapshot.values
            return values if values else None

        return await self._run_with_checkpointer(_read, thread_id=run_id)

    def _goto_next_volume(self, state: VolumeState) -> Command[Any]:
        """跳过当前卷推进到下一卷；已是最后一卷 → END（finished=True）。

        下一卷章列表从 state["volumes"] 读取（持久化通道：跨重启 resume 的 fresh
        实例也能继续），不依赖实例内存 _volumes。

        #1187 B：卷推进必须清空 continuity（否则下一卷的章会读到上一卷承接表——
        跨卷串味），并回到 `prepare_continuity` 重算本卷承接表。
        """
        next_index = state["volume_index"] + 1
        if next_index >= state["total_volumes"]:
            return Command(update={"finished": True}, goto=END)
        return Command(
            update={
                "chapters": state["volumes"][next_index]["chapters"],
                "volume_index": next_index,
                "continuity": {},
            },
            goto="prepare_continuity",
        )

    def _goto_next_volume_with_usage(self, state: VolumeState, event: dict) -> Command[Any]:
        """#902：supervisor 补救（chat 已发生）后推进下一卷，usage 事件并入 update.

        镜像 _goto_next_volume，仅增 "usage": [event]（checkpoint 持久化不丢不重）。
        """
        next_index = state["volume_index"] + 1
        if next_index >= state["total_volumes"]:
            return Command(update={"finished": True, "usage": [event]}, goto=END)
        return Command(
            update={
                "chapters": state["volumes"][next_index]["chapters"],
                "volume_index": next_index,
                "continuity": {},
                "usage": [event],
            },
            goto="prepare_continuity",
        )

    @instrument(caller_type="agent")
    async def _delegate_chapter(
        self, chapter: dict, *, continuity: dict | None = None
    ) -> tuple[str, dict]:
        """委托契约核心（镜像 BookService._delegate_chapter）：章 brief → writer_factory
        → agent.invoke → draft_service.create 回收 → (execution_id, usage 事件)。

        #902：usage 事件只来自真实 LLM 调用结果（invoke 结果 messages usage_metadata /
        顶层 usage）；双源皆缺 → 全零事件（无伪计费）。事件 source="write"，
        chapter=str(outline_id)。

        #1187 B：continuity = 本章承接（B 阶段承接表按本章 outline_id 取出的项）——
        承接段追加进既有 brief（`_build_chapter_brief` 通道）产物，隔离性由调用方保证。
        """
        plan = self._plan
        if plan is None:
            raise ValueError("plan 未装配")
        if self._writer_factory is None:
            raise ValueError("writer_factory 未装配")
        cfg: object | None = (
            await self._project_config_getter(plan.project_id)
            if self._project_config_getter is not None
            else None
        )
        brief_inputs = await resolve_brief_setting(self._context_builder, cfg, plan, chapter)
        system_prompt = self._build_chapter_brief(
            plan, chapter, **brief_inputs
        ) + _continuity_segment(continuity)
        agent = await self._writer_factory(
            system_prompt=system_prompt,
            expected_project_id=plan.project_id,
            expected_chapter_id=chapter["chapter_id"],
            expected_source_outline_id=chapter["outline_id"],
            expected_volume_outline_id=chapter.get("volume_outline_id"),
        )
        messages = chapter_write_messages(system_prompt, chapter, brief_inputs["default_words"])
        result = await agent.invoke(messages)  # type: ignore[attr-defined]  # 鸭子类型：agent 按 F27 契约提供 async invoke(messages)
        prompt_tokens, completion_tokens, total_tokens = result_usage(result)

        async def _invoke_again() -> str:
            """#1316 空产出重试：重新委托一次（token 并入本事件，计费口径不丢）."""
            nonlocal result, prompt_tokens, completion_tokens, total_tokens
            result = await agent.invoke(messages)  # type: ignore[attr-defined]  # 鸭子类型：同首次委托（F27 async invoke(messages)）
            retry_prompt, retry_completion, retry_total = result_usage(result)
            prompt_tokens += retry_prompt
            completion_tokens += retry_completion
            total_tokens += retry_total
            return _extract_final_content(result)

        content = await guard_empty_chapter_content(
            _extract_final_content(result), invoke=_invoke_again, chapter_name=chapter["name"]
        )
        record_word_deviation(content, brief_inputs["default_words"], chapter_name=chapter["name"])
        if draft_fallback_needed(result):
            # #975 守卫：agent 未显式 save_draft → 服务层兜底建草稿（#976 D3 卷透传）
            draft = await self._draft_service.create(  # type: ignore[union-attr]  # 鸭子类型：draft_service 按 F27 契约提供 async create
                project_id=plan.project_id,
                chapter_id=chapter["chapter_id"],
                content=content,
                summary="",
                volume_id=await self._resolve_draft_volume(plan, chapter),
                source_outline_id=chapter["outline_id"],
            )
            execution_id = str(getattr(draft, "id", ""))
        else:
            # agent 已 save_draft：不回退建草稿，执行 id 取工具消息 draft_id（可 ""）
            execution_id = _extract_saved_draft_id(result)
        return (
            execution_id,
            {
                "source": "write",
                "chapter": str(chapter["outline_id"]),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        )

    @instrument(caller_type="agent")
    async def _build_continuity(self, state: VolumeState) -> dict[str, dict]:
        """B 阶段承接表生成（#1187）：一次 LLM 调用生成整卷承接表；失败 → 空表.

        输入只有大纲面（卷纲 + 各章章纲 + 前一章章纲）——调用点在扇出前，此时无任何
        正文可读。LLM 异常 / content 解析失败 → `{}`（降级：brief 不注入承接段）。
        """
        chapters: list[dict] = state["chapters"]
        if not chapters:
            return {}
        volumes: list[dict] = state["volumes"]
        index = state["volume_index"]
        volume = volumes[index] if 0 <= index < len(volumes) else {}
        try:
            response = await self._llm.chat(  # type: ignore[attr-defined]  # 鸭子类型：llm_client 按 F29 契约提供 async chat(messages)
                _continuity_messages(volume, chapters)
            )
        except Exception:
            logger.warning("#1187 卷级承接表生成失败，降级为空承接表：volume_index={}", index)
            return {}
        return _parse_continuity_table(str(getattr(response, "content", "")))

    @instrument(caller_type="agent")
    async def _audit_volume(self, state: VolumeState) -> tuple[dict[str, object], bool]:
        """C 阶段卷级审计（#1187）：逐章复用 F34 服务 → (状态更新, 是否阻断).

        顺序：跳过 failed 章（无正文可审）→ `audit_service.audit(project_id, chapter_id)`
        → `_audit_bridge.report_to_audit_dict` 扁平化 → `blocking_update` 判定（#1267
        唯一口径，本处不另立阈值）。未装配 audit_service → 空更新（透传）；单章审计异常
        → 吞掉（warning）继续审其余章，不阻断编排。

        Returns:
            (update, blocked)：update 为图状态增量（阻断时含 `audit_blocked` + `status`）。
        """
        service = self._audit_service
        if service is None:
            return {}, False
        project_id = getattr(self._plan, "project_id", None)
        blocked_map: dict[str, str] = {}
        for chapter in state["chapters"]:
            oid = str(chapter["outline_id"])
            if state.get("results", {}).get(oid) == "failed":
                continue  # 失败章无正文可审
            chapter_id = chapter.get("chapter_id")
            if chapter_id is None:
                continue
            try:
                report = await service.audit(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按 F34 契约提供 async audit(project_id, chapter_id, include_static=...)
                    project_id, chapter_id, include_static=True
                )
            except Exception:
                logger.warning("#1187 卷级审计失败（跳过本章，不阻断编排）：chapter={}", oid)
                continue
            audit_dict = report_to_audit_dict(report)
            raw_findings = list(getattr(report, "findings", None) or [])
            if raw_findings:
                # `_dump_finding` 对无 model_dump 的鸭子 finding 只留 message（severity 丢失），
                # 阻断判定须看原始 findings（_audit_bridge._is_blocking_finding 两形态通吃）。
                audit_dict["findings"] = raw_findings
            delta = blocking_update(oid, audit_dict)
            if delta:
                blocked_map.update(cast("dict[str, str]", delta["audit_blocked"]))
        if not blocked_map:
            return {}, False
        return {"audit_blocked": blocked_map, "status": "blocked"}, True

    async def _resolve_draft_volume(self, plan: WritingPlan, chapter: dict) -> uuid.UUID | None:
        """#976 D3/D5：委托落草稿卷解析（volume_lookup 未装配/无映射 → None）.

        查表键：章 dict 的 volume_outline_id（卷 outline 节点 id）优先，回退
        outline_id（chapter dict 恒含）；返回 str(uuid.UUID(int=vid)) → UUID。
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
    async def _delegate_supervisor(self, failed: list[str]) -> tuple[str, dict]:
        """授权主 agent 补救（F29 supervisor 决策通道）：llm_client.chat → 解析
        {action: continue|abort}（解析失败默认 continue）→ (action, usage 事件)。

        #902：事件 source="supervisor"、chapter=""，取自 llm.chat 响应真实 usage
        （token_usage 主源 / usage_metadata 回退）；双源皆缺 → 全零事件。
        """
        messages = [
            {
                "role": "system",
                "content": "你是小说创作管线的编排 supervisor，负责卷级失败补救决策。",
            },
            {
                "role": "user",
                "content": (
                    "当前卷执行失败，failed 章列表如下：\n"
                    + "\n".join(f"- {oid}" for oid in failed)
                    + '\n请输出 JSON 决策：{"action": "continue"} 或 {"action": "abort"}。'
                ),
            },
        ]
        response = await self._llm.chat(  # type: ignore[attr-defined]  # 鸭子类型：llm_client 按 F29 契约提供 async chat(messages)
            messages
        )
        prompt_tokens, completion_tokens, total_tokens = chat_response_usage(response)
        content = str(getattr(response, "content", ""))
        return (
            _parse_supervisor_decision(content),
            {
                "source": "supervisor",
                "chapter": "",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        )
