"""F44 卷级编排图（#337 阶段 3）— Send map-reduce 并行扇出 + 卷边界 HITL + 失败恢复策略树.

BookVolumePipeline 镜像 SupervisorPipeline（F29）结构：execute 抛 VolumeHITLInterrupt，
resume 从 checkpointer 恢复。图拓扑（Spike ①-④ 实证形态，父侧契约定稿）：
    START → bootstrap（UntrackedValue 注入 llm_client，镜像 F29）
        → volume_fan_out（Command(goto=[Send("write_chapter", ...)])，非 return [Send(...)]）
          → write_chapter 并行分支（节点内无 interrupt，章级重试 N 次）
          → join（map-reduce 回收；results 通道 Annotated[dict, operator.or_] reducer）
          → join 判定顺序: ① 护栏（累计步数 >= max_agent_calls → END/aborted）
            ② 卷级失败（该卷全部章 failed → volume_failure）
            ③ 其余 → 最后一卷 END / 非最后一卷 volume_boundary
        → volume_boundary（interrupt 串行点）→ resume approved → 下一卷 / END
        → volume_failure（interrupt）→ resume decision: continue / abort / supervisor

依据: specs/f44-book-orchestrator/spec.md §5.3/§12 D1-D3/D9/§13.3 M7-M9
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

from inkflow.domain.models.writing_plan import BookLimits, WritingPlan

_R = TypeVar("_R")


class VolumeState(TypedDict):
    """卷级编排图状态 — 镜像 PipelineState.results reducer 模式（Spike ② 必备）。"""

    context: dict[str, Any]
    chapters: list[dict]
    volumes: list[dict]
    plan: dict
    limits: dict
    results: Annotated[dict[str, str], operator.or_]
    failed: Annotated[list[str], operator.add]
    volume_index: int
    total_volumes: int
    retries: int
    steps: Annotated[int, operator.add]
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
    return str(content)


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


async def _bootstrap_node(state: VolumeState, llm_client: object) -> dict[str, object]:
    """启动节点：将 llm_client 写入 UntrackedValue 通道（不参与 checkpointer 序列化，镜像 F29）。"""
    return {"llm_client": llm_client}


async def _volume_fan_out(state: VolumeState) -> Command[Any]:
    """卷扇出：Command(goto=[Send("write_chapter", {"chapter": ch}) ...])——Spike ① 形态。

    非 return [Send(...)]（LangGraph 1.2.10 报 InvalidUpdateError）；空卷直接 goto join 回收。
    """
    if not state["chapters"]:
        return Command(goto="join")
    return Command(goto=[Send("write_chapter", {"chapter": ch}) for ch in state["chapters"]])


async def _write_chapter(state: VolumeState, pipeline: BookVolumePipeline) -> dict[str, object]:
    """章执行节点（Send 并行分支，节点内无 interrupt——Spike ④ 硬约束）。

    执行 = writer_factory(system_prompt=章 brief, expected_project_id, expected_chapter_id)
    → agent.invoke([...]) → draft_service.create(...) → 返回 results 增量。
    任一步抛异常 → 重试整章（重新调用 writer_factory），至多 retry_limit 次重试
    （总尝试 1 + retry_limit）；仍失败 → 章级只报告 failed，不阻塞其他章。
    """
    chapter: dict = cast(dict[str, Any], state)["chapter"]
    outline_id = str(chapter["outline_id"])
    attempts = 0
    for _ in range(1 + pipeline._retry_limit):
        attempts += 1
        try:
            execution_id = await pipeline._delegate_chapter(chapter)
        except Exception:
            # 任一步异常 → 重试整章（循环再次调用 writer_factory）
            continue
        else:
            return {"results": {outline_id: execution_id}, "steps": attempts}
    return {"results": {outline_id: "failed"}, "failed": [outline_id], "steps": attempts}


async def _join(state: VolumeState, pipeline: BookVolumePipeline) -> Command[Any]:
    """map-reduce 回收节点：判定顺序 = ① 护栏 ② 卷级失败 ③ 最后一卷/卷边界。"""
    if state.get("steps", 0) >= pipeline._limits.max_agent_calls:
        # 预算 = max_agent_calls（每次尝试含重试消耗 1 步）；超预算终止，不抛 interrupt
        return Command(update={"finished": True, "status": "aborted"}, goto=END)
    chapters = state["chapters"]
    results = state.get("results", {})
    failed_count = sum(1 for c in chapters if results.get(str(c["outline_id"])) == "failed")
    if chapters and failed_count == len(chapters):
        # 卷级失败判定 = 该卷全部章 failed（部分失败不触发 volume_failure）
        return Command(goto="volume_failure")
    if state["volume_index"] >= state["total_volumes"] - 1:
        # 最后一卷完成 → 不 interrupt → END（execute 返回 completed）
        return Command(update={"finished": True}, goto=END)
    return Command(goto="volume_boundary")


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
        action = await pipeline._delegate_supervisor(failed)
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
    ) -> None:
        """构造：llm_client 仅 UntrackedValue 通道传递（镜像 F29 bootstrap 节点），
        不参与执行决策；只在卷级失败 decision="supervisor" 补救时调用 chat。
        checkpointer 显式传入 → 优先使用（不打开文件）；否则 checkpoint_path →
        每次 execute/resume 临时打开 AsyncSqliteSaver 文件后端（跨实例/跨进程
        resume 可行）；两者皆无 → 进程内 InMemorySaver（阶段 3 默认）。"""
        self._llm = llm_client
        self._writer_factory = writer_factory
        self._draft_service = draft_service
        self._retry_limit = retry_limit
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
        """构建卷级图：bootstrap → volume_fan_out → write_chapter（Send 并行）→ join
        → volume_boundary / volume_failure（Command(goto) 动态路由，镜像 F29）；
        checkpointer 参数化（显式 InMemorySaver 或临时 AsyncSqliteSaver）。"""
        g = StateGraph(VolumeState)
        g.add_node("bootstrap", partial(_bootstrap_node, llm_client=self._llm))
        g.add_node("volume_fan_out", _volume_fan_out)
        g.add_node("write_chapter", partial(_write_chapter, pipeline=self))
        g.add_node("join", partial(_join, pipeline=self))
        g.add_node("volume_boundary", partial(_volume_boundary, pipeline=self))
        g.add_node("volume_failure", partial(_volume_failure, pipeline=self))
        g.add_edge(START, "bootstrap")
        g.add_edge("bootstrap", "volume_fan_out")
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
                "failed": [],
                "volume_index": 0,
                "total_volumes": len(volumes),
                "retries": 0,
                "steps": 0,
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
        """跳过当前卷推进到下一卷（fan_out）；已是最后一卷 → END（finished=True）。

        下一卷章列表从 state["volumes"] 读取（持久化通道：跨重启 resume 的 fresh
        实例也能继续），不依赖实例内存 _volumes。"""
        next_index = state["volume_index"] + 1
        if next_index >= state["total_volumes"]:
            return Command(update={"finished": True}, goto=END)
        return Command(
            update={
                "chapters": state["volumes"][next_index]["chapters"],
                "volume_index": next_index,
            },
            goto="volume_fan_out",
        )

    async def _delegate_chapter(self, chapter: dict) -> str:
        """委托契约核心（镜像 BookService._delegate_chapter）：章 brief → writer_factory
        → agent.invoke → draft_service.create 回收 → 返回 execution_id。"""
        plan = self._plan
        if plan is None:
            raise ValueError("plan 未装配")
        if self._writer_factory is None:
            raise ValueError("writer_factory 未装配")
        system_prompt = self._build_chapter_brief(plan, chapter)
        agent = await self._writer_factory(
            system_prompt=system_prompt,
            expected_project_id=plan.project_id,
            expected_chapter_id=chapter["chapter_id"],
        )
        result = await agent.invoke(  # type: ignore[attr-defined]  # 鸭子类型：agent 按 F27 契约提供 async invoke(messages)
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (f"请撰写章节《{chapter['name']}》：{chapter['description']}"),
                },
            ]
        )
        content = _extract_final_content(result)
        draft = await self._draft_service.create(  # type: ignore[union-attr]  # 鸭子类型：draft_service 按 F27 契约提供 async create
            project_id=plan.project_id,
            chapter_id=chapter["chapter_id"],
            content=content,
            summary="书级委托保存",
        )
        return str(getattr(draft, "id", ""))

    @staticmethod
    def _build_chapter_brief(plan: WritingPlan, chapter: dict) -> str:
        """构造章 brief：大纲切片 + 角色摘要 + 风格/偏好注入（镜像 BookService）。"""
        character_summary = (
            "主角自定" if not plan.character_ids else "见角色档案（plan.character_ids）"
        )
        return (
            "你是一位小说章节写作者。请严格按大纲切片撰写本章正文。\n"
            f"【章节大纲】{chapter['description']}\n"
            f"【角色摘要】{character_summary}\n"
            "【风格/偏好注入】遵循项目写作风格与用户偏好（偏好优先于通用文风）。"
        )

    async def _delegate_supervisor(self, failed: list[str]) -> str:
        """授权主 agent 补救（F29 supervisor 决策通道）：llm_client.chat → 解析
        {action: continue|abort}（解析失败默认 continue）。"""
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
        content = str(getattr(response, "content", ""))
        return _parse_supervisor_decision(content)
