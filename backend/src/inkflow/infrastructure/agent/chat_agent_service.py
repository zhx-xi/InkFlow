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
from collections.abc import AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage

from inkflow.domain.models.agent_run import AgentStep, AgentToolCall
from inkflow.domain.services.chat_service import ChatStreamEvent


def _chunk_stream(text: str, size: int = 6) -> list[str]:
    """#642：完整响应按固定大小切块，模拟流式增量输出。"""
    return [text[i : i + size] for i in range(0, len(text), size)]


class ChatAgentService:
    """deepagents 系统级 Agent 流式服务（组装消息 → astream_events v2 → 帧映射 + trace 收集）。

    Args:
        agent: deepagents CompiledStateGraph 鸭子对象（提供 astream_events v2）。
        system_prompt: 系统级 Agent 提示词（注入 SystemMessage）。
    """

    def __init__(self, *, agent: object, system_prompt: str) -> None:
        self._agent = agent
        self._system_prompt = system_prompt
        # #615 trace 收集器（每次 stream_events 独立，consume_trace 消费后清空防跨请求污染）
        self._trace: list[AgentStep] = []
        self._final_content: str = ""
        self._token_usage_total: int = 0
        # on_tool_end.run_id → (step_index, tool_index) 映射（AgentToolCall 无 id 字段，
        # 结果回填按 AIMessage.tool_calls[].id ↔ on_tool_end.run_id 匹配）
        self._tool_call_index: dict[str, tuple[int, int]] = {}

    async def stream_events(
        self, prompt: str, chapter_context: str | None = None
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """astream_events v2 事件流 → ChatStreamEvent 帧序列 + #615 steps 收集。

        messages 组装镜像 ChatService.stream：[SystemMessage(system_prompt),
        HumanMessage(prompt + 章节上下文)]；事件映射：
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
        user_content = prompt
        if chapter_context:
            user_content = f"{prompt}\n\n章节上下文：\n{chapter_context}"
        messages = [SystemMessage(self._system_prompt), HumanMessage(user_content)]
        streamed_any = False
        async for ev in self._agent.astream_events(  # type: ignore[attr-defined]  # 鸭子类型：deepagents CompiledStateGraph 提供 astream_events（v2 事件 dict 流）
            {"messages": messages}, version="v2"
        ):
            if ev.get("event") == "on_chat_model_stream" and ev.get("run_type") == "llm":
                chunk = ev.get("data", {}).get("chunk")
                yield ChatStreamEvent(type="delta", delta=chunk.content)
                streamed_any = True
            elif ev.get("event") == "on_chat_model_end":
                output = ev.get("data", {}).get("output")
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
                self._collect_tool_result(ev.get("run_id"), result)
                yield ChatStreamEvent(
                    type="tool_result",
                    id=ev.get("run_id"),
                    name=ev.get("name"),
                    result=result,
                )
        yield ChatStreamEvent(type="done", done=True)

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
        self._trace.append(
            AgentStep(
                index=step_index,
                message_content=content,
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
