"""#597 chat 系统级 Agent 流式服务 — deepagents astream_events v2 事件流 → ChatStreamEvent 帧.

位于 infrastructure/agent/（ADR-015：domain 禁止 LangChain 依赖；调用 langgraph
astream_events 属基础设施职责）。接收已装配的 deepagents CompiledStateGraph 鸭子
对象，逐事件映射为 ChatStreamEvent 帧（delta / tool_call / tool_result / done）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage

from inkflow.domain.services.chat_service import ChatStreamEvent


class ChatAgentService:
    """deepagents 系统级 Agent 流式服务（组装消息 → astream_events v2 → 帧映射）。

    Args:
        agent: deepagents CompiledStateGraph 鸭子对象（提供 astream_events v2）。
        system_prompt: 系统级 Agent 提示词（注入 SystemMessage）。
    """

    def __init__(self, *, agent: object, system_prompt: str) -> None:
        self._agent = agent
        self._system_prompt = system_prompt

    async def stream_events(
        self, prompt: str, chapter_context: str | None = None
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """astream_events v2 事件流 → ChatStreamEvent 帧序列。

        messages 组装镜像 ChatService.stream：[SystemMessage(system_prompt),
        HumanMessage(prompt + 章节上下文)]；事件映射：
        - on_chat_model_stream（run_type=llm）→ delta 帧
        - on_tool_start → tool_call 帧（id=run_id / name / args）
        - on_tool_end → tool_result 帧（id=run_id / name / result）
        - 流结束 → done 帧

        LLMRequestError 原样传播（service 不吞异常，端点层转 error 帧）。
        """
        user_content = prompt
        if chapter_context:
            user_content = f"{prompt}\n\n章节上下文：\n{chapter_context}"
        messages = [SystemMessage(self._system_prompt), HumanMessage(user_content)]
        async for ev in self._agent.astream_events(  # type: ignore[attr-defined]  # 鸭子类型：deepagents CompiledStateGraph 提供 astream_events（v2 事件 dict 流）
            {"messages": messages}, version="v2"
        ):
            if ev.get("event") == "on_chat_model_stream" and ev.get("run_type") == "llm":
                chunk = ev.get("data", {}).get("chunk")
                yield ChatStreamEvent(type="delta", delta=chunk.content)
            elif ev.get("event") == "on_tool_start":
                yield ChatStreamEvent(
                    type="tool_call",
                    id=ev.get("run_id"),
                    name=ev.get("name"),
                    args=ev.get("data", {}).get("input"),
                )
            elif ev.get("event") == "on_tool_end":
                yield ChatStreamEvent(
                    type="tool_result",
                    id=ev.get("run_id"),
                    name=ev.get("name"),
                    result=ev.get("data", {}).get("output"),
                )
        yield ChatStreamEvent(type="done", done=True)
