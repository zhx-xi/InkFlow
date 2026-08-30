"""#597 chat 系统级 Agent 流式服务 + #615 trace 收集 — astream_events v2 → 帧 + steps 收集.

位于 infrastructure/agent/（ADR-015：domain 禁止 LangChain 依赖；调用 langgraph
astream_events 属基础设施职责）。接收已装配的 deepagents CompiledStateGraph 鸭子
对象，逐事件映射为 ChatStreamEvent 帧（delta / tool_call / tool_result / done）。
#615 增量：on_chat_model_end（完整 AIMessage）→ AgentStep 收集（含 tool_calls/
tokens），on_tool_end 按 run_id 回填 result/is_error；流结束后端点经
consume_trace() 取回 (steps, final_content, token_usage_total) 落 AgentRun。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from inkflow.domain.models.agent_run import AgentStep, AgentToolCall
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.chat_service import ChatStreamEvent


def _chunk_stream(text: str, size: int = 6) -> list[str]:
    """#642：完整响应按固定大小切块，模拟流式增量输出。"""
    return [text[i : i + size] for i in range(0, len(text), size)]


def _extract_reasoning_content(output: object) -> str:
    """从 on_chat_model_end 的 AIMessage 提取思考内容（reasoning_content，#727）。

    DeepSeek 等推理模型把思考过程放进 additional_kwargs["reasoning_content"]，
    个别实现直接暴露 reasoning_content 属性；均用 getattr 守卫，缺失时返回空串。
    """
    if output is None:
        return ""
    additional = getattr(output, "additional_kwargs", None)
    if isinstance(additional, dict):
        reasoning = additional.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            return reasoning
    reasoning = getattr(output, "reasoning_content", None)
    if isinstance(reasoning, str) and reasoning:
        return reasoning
    return ""


class ChatAgentService:
    """deepagents 系统级 Agent 流式服务（组装消息 → astream_events v2 → 帧映射 + trace 收集）。

    Args:
        agent: deepagents CompiledStateGraph 鸭子对象（提供 astream_events v2）。
        system_prompt: 系统级 Agent 提示词（注入 SystemMessage）。
        project_context_getter: #680 可选注入——async fn(prompt, project_id) -> str
            （渲染好的项目上下文段）；stream_events 组装 SystemMessage 前调用增强
            系统提示词，失败回退基础提示词（失败隔离，不阻断流）。
        history_getter: #748 可选注入——async fn(project_id) -> list[历史消息对象]
            （对象含 .role（"user"/"ai"）与 .content）；stream_events 组装消息链时
            按序插入 SystemMessage 之后：role=user → HumanMessage、role=ai →
            AIMessage，随后追加当前 HumanMessage；getter 异常 → 回退
            [System, Human(current)]（失败隔离，不阻断流）。
    """

    def __init__(
        self,
        *,
        agent: object,
        system_prompt: str,
        project_context_getter: Callable[[str, str], Awaitable[str]] | None = None,
        history_getter: Callable[[str], Awaitable[list[object]]] | None = None,
        thread_id: str = "",
    ) -> None:
        self._agent = agent
        self._system_prompt = system_prompt
        self._project_context_getter: Callable[[str, str], Awaitable[str]] | None = (
            project_context_getter
        )
        self._history_getter: Callable[[str], Awaitable[list[object]]] | None = history_getter
        # #615 trace 收集器（每次 stream_events 独立，consume_trace 消费后清空防跨请求污染）
        self._trace: list[AgentStep] = []
        self._final_content: str = ""
        self._token_usage_total: int = 0
        # on_tool_end.run_id → (step_index, tool_index) 映射（AgentToolCall 无 id 字段，
        # 结果回填按 AIMessage.tool_calls[].id ↔ on_tool_end.run_id 匹配）
        self._tool_call_index: dict[str, tuple[int, int]] = {}
        # #766 阶段③/#821：HITL resume 与 stream_events 共用 thread_id（装配期注入，空时 uuid 兜底）
        self._thread_id: str = thread_id

    async def stream_events(
        self,
        prompt: str,
        project_id: str | None = None,
        chapter_context: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """astream_events v2 事件流 → ChatStreamEvent 帧序列 + #615 steps 收集。

        #680: project_id 非空且注入 project_context_getter 时，先渲染项目上下文段
        并追加到系统提示词（`{system_prompt}\n\n{ctx}`）；getter 异常 → 回退基础
        提示词（失败隔离，不阻断流）。

        messages 组装镜像 ChatService.stream：[SystemMessage(system_prompt),
        HumanMessage(prompt + 章节上下文)]；#748 注入 history_getter 时，消息链变为
        [System, 历史 user/ai..., Human(current)]（失败隔离回退无历史形态）；事件映射：
        - on_chat_model_stream（run_type=llm）→ delta 帧
        - on_chat_model_end（完整 AIMessage）→ 收集 AgentStep（message_content +
          tool_calls + tokens）；若无流式 delta，则将完整 content 切块产出 delta 帧
        - on_tool_start → tool_call 帧（id=run_id / name / args）
        - on_tool_end → tool_result 帧（id=run_id / name / result），并按 run_id
          回填已收集 step 的 tool_calls[].result/is_error
        - 流结束 → done 帧

        LLMRequestError 原样传播（service 不吞异常，端点层转 error 帧）。
        """
        self._reset_trace()
        system_prompt = self._system_prompt
        if self._project_context_getter is not None and project_id is not None:
            try:
                ctx = await self._project_context_getter(prompt, project_id)
                if ctx:
                    system_prompt = f"{system_prompt}\n\n{ctx}"
            except Exception:
                pass  # 失败隔离：回退基础 system_prompt，不阻断流
        user_content = prompt
        if chapter_context:
            user_content = f"{prompt}\n\n章节上下文：\n{chapter_context}"
        messages: list[object] = [SystemMessage(system_prompt), HumanMessage(user_content)]
        if self._history_getter is not None and project_id is not None:
            try:
                history = await self._history_getter(project_id)
                history_messages: list[object] = []
                for item in history:
                    # 防御：已归档历史跳过（对象无 is_deleted 属性则不过滤）
                    if getattr(item, "is_deleted", False):
                        continue
                    role = getattr(item, "role", None)
                    content = getattr(item, "content", "")
                    if role == "user":
                        history_messages.append(HumanMessage(content=content))
                    elif role == "ai":
                        history_messages.append(AIMessage(content=content))
                messages = [
                    SystemMessage(system_prompt),
                    *history_messages,
                    HumanMessage(user_content),
                ]
            except Exception:
                pass  # 失败隔离：回退 [System, Human(current)]，不阻断流
        streamed_any = False
        cancelled = False
        try:
            async for ev in self._agent.astream_events(  # type: ignore[attr-defined]  # 鸭子类型：deepagents CompiledStateGraph 提供 astream_events（v2 事件 dict 流）
                {"messages": messages},
                version="v2",
                config={"configurable": {"thread_id": self._thread_id or str(uuid.uuid4())}},
            ):
                # #719：用户中断 → 停止继续 yield 事件（done 终帧由路由层落 TERMINATED 后自行发出）
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if ev.get("event") == "on_chat_model_stream" and ev.get("run_type") == "llm":
                    chunk = ev.get("data", {}).get("chunk")
                    yield ChatStreamEvent(type="delta", delta=chunk.content)
                    streamed_any = True
                elif ev.get("event") == "on_chat_model_end":
                    output = ev.get("data", {}).get("output")
                    # #727：思考过程帧在 done/delta 之前产出（无思考时不影响原有行为）
                    reasoning = _extract_reasoning_content(output)
                    if reasoning:
                        yield ChatStreamEvent(type="reasoning", delta=reasoning, done=False)
                    content = getattr(output, "content", "") or ""
                    if content and not streamed_any:
                        for c in _chunk_stream(content, size=6):
                            await asyncio.sleep(0.05)
                            yield ChatStreamEvent(type="delta", delta=c)
                    self._collect_model_end(output)
                elif ev.get("event") == "on_tool_start":
                    yield ChatStreamEvent(
                        type="tool_call",
                        id=ev.get("run_id"),
                        name=ev.get("name"),
                        args=ev.get("data", {}).get("input"),
                    )
                elif ev.get("event") == "on_tool_end":
                    result = ev.get("data", {}).get("output")
                    if not isinstance(result, str):
                        result = getattr(result, "content", str(result))
                    self._collect_tool_result(ev.get("run_id"), result)
                    yield ChatStreamEvent(
                        type="tool_result",
                        id=ev.get("run_id"),
                        name=ev.get("name"),
                        result=result,
                    )
                elif ev.get("event") == "on_chain_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    # #766 阶段③：langgraph interrupt 经 chunk["__interrupt__"] 流出
                    # （父侧探针实测 langgraph 1.2.10）。提取 Interrupt.value → interrupt 帧。
                    if isinstance(chunk, dict) and "__interrupt__" in chunk:
                        interrupts = chunk["__interrupt__"]
                        payload = None
                        # Interrupt 对象 .value 属性（或元组元素）；payload 为 tool 三键
                        if interrupts:
                            first = (
                                interrupts[0]
                                if isinstance(interrupts, (list, tuple))
                                else interrupts
                            )
                            value = getattr(first, "value", None) or (
                                first if isinstance(first, dict) else None
                            )
                            if isinstance(value, dict):
                                payload = value
                        yield ChatStreamEvent(type="interrupt", payload=payload, done=False)
            if not cancelled:
                yield ChatStreamEvent(type="done", done=True)
        except LLMRequestError:
            raise
        except Exception as exc:
            yield ChatStreamEvent(type="error", done=True, error=f"工具执行失败: {exc}")
            yield ChatStreamEvent(type="done", done=True)

    async def resume(self, *, conversation_id: str, approved: bool) -> dict:
        """#766 阶段③：HITL 中断续跑——给 agent invoke Command(resume={"approved": approved})。

        复用书级 HITL resume 模式（book_agentic_pipeline.py::resume）：需 checkpointer +
        thread_id（本服务 agent 已由装配期注入 InMemorySaver + 每次 run thread_id，见 harness）。
        """
        from langgraph.types import Command

        await self._agent.ainvoke(  # type: ignore[attr-defined]  # 鸭子类型：deepagents CompiledStateGraph 提供 ainvoke
            Command(resume={"approved": approved}),
            config={"configurable": {"thread_id": self._thread_id}},
        )
        return {"ok": True}

    def consume_trace(self) -> tuple[list[AgentStep], str, int]:
        """#615：消费 trace 收集器 → (steps, final_content, token_usage_total) 并清空。

        每次 stream_events 独立收集；端点流结束后调用一次，随后置空防止跨请求污染。
        """
        steps, final_content, token_total = (
            self._trace,
            self._final_content,
            self._token_usage_total,
        )
        self._reset_trace()
        return steps, final_content, token_total

    def _reset_trace(self) -> None:
        """清空 trace 收集器（stream_events 前置防御 + consume_trace 消费后置空）。"""
        self._trace = []
        self._final_content = ""
        self._token_usage_total = 0
        self._tool_call_index = {}

    def _collect_model_end(self, output: object) -> None:
        """#615：on_chat_model_end 完整 AIMessage → 追加一条 AgentStep。

        output 鸭子：.content（str）/ .tool_calls（list[dict]：name/args/id）/
        .response_metadata.usage.total_tokens（int，缺省 0）。
        """
        if output is None:
            return
        step_index = len(self._trace)
        calls: list[AgentToolCall] = []
        for tool_index, tc in enumerate(getattr(output, "tool_calls", None) or []):
            call_id = str(tc.get("id", ""))
            calls.append(
                AgentToolCall(
                    step_index=step_index,
                    tool_name=tc.get("name", ""),
                    arguments=dict(tc.get("args") or {}),
                    result="",
                    is_error=False,
                )
            )
            if call_id:
                self._tool_call_index[call_id] = (step_index, tool_index)
        content = getattr(output, "content", "") or ""
        tokens = int(
            (getattr(output, "response_metadata", None) or {})
            .get("usage", {})
            .get("total_tokens", 0)
        )
        # （在构造 AgentStep 之前）提取 reasoning（#740：推理模型写入思考过程，缺省空串）
        reasoning = _extract_reasoning_content(output)
        self._trace.append(
            AgentStep(
                index=step_index,
                message_content=content,
                reasoning=reasoning,
                tool_calls=calls,
                tokens=tokens,
            )
        )
        self._final_content = content
        self._token_usage_total += tokens

    def _collect_tool_result(self, run_id: object, output: object) -> None:
        """#615：on_tool_end 结果回填 — 按 run_id（AIMessage.tool_calls[].id）定位。

        result 为 str 输出；is_error = '"ok": false' in result（工具失败语义，镜像 F27）。
        """
        entry = self._tool_call_index.get("" if run_id is None else str(run_id))
        if entry is None:
            return
        step_index, tool_index = entry
        result_str = "" if output is None else str(output)
        call = self._trace[step_index].tool_calls[tool_index]
        call.result = result_str
        call.is_error = '"ok": false' in result_str
