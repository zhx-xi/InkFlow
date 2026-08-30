from __future__ import annotations

import dataclasses
from collections.abc import AsyncGenerator

from inkflow.domain.ports.llm_client import ChatMessage


@dataclasses.dataclass
class ChatStreamEvent:
    """chat 流式事件（router 层转 SSE 帧）。"""

    delta: str = ""
    done: bool = False
    error: str | None = None
    # #597 chat 系统级 Agent 扩展字段（保留既有 delta/done/error，向后兼容）：
    # type 区分帧类型（delta/tool_call/tool_result/done/error），id/name/args/result
    # 供工具调用帧透传（spec f47 §14.2 帧表）。
    type: str = "delta"
    id: str | None = None
    name: str | None = None
    args: dict | None = None
    result: str | None = None
    payload: dict | None = None  # #766 interrupt 帧：HITL 删除授权 payload


class ChatService:
    """chat 对话流式服务：组装 [system, user] 消息 → LLM 流透传。

    Args:
        llm_client: LLMClientProtocol 鸭子对象（chat_stream 为普通方法返回 async generator）。
        system_prompt: 系统提示词模板（含 {prompt} 占位；无占位时原样使用）。
    """

    def __init__(self, *, llm_client: object, system_prompt: str) -> None:
        self._llm_client = llm_client
        self._system_prompt = system_prompt

    async def stream(
        self, prompt: str, chapter_context: str | None = None
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """LLM 流 → ChatStreamEvent delta 序列，结束后 done=True。

        - messages[0] = system（system_prompt.replace("{prompt}", prompt)——
          无 {prompt} 占位时 replace 无副作用，原样保留）
        - messages[1] = user（content=prompt；chapter_context 非空时追加章节上下文段落）
        - 逐 chunk 转 ChatStreamEvent(delta=chunk.content)；LLMRequestError 向上传播。
        """
        system = self._system_prompt.replace("{prompt}", prompt)
        user_content = prompt
        if chapter_context:
            user_content = f"{prompt}\n\n章节上下文：\n{chapter_context}"
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user_content),
        ]
        stream = self._llm_client.chat_stream(messages)  # type: ignore[attr-defined]  # 鸭子类型：LLMClientProtocol 提供 chat_stream
        if hasattr(stream, "__aiter__"):
            # 异步生成器（真实 LangChainLLMClient.chat_stream）
            async for chunk in stream:
                yield ChatStreamEvent(delta=chunk.content)
        else:
            # 同步生成器（单元测试 fake 契约：普通方法返回生成器）
            for chunk in stream:
                yield ChatStreamEvent(delta=chunk.content)
        yield ChatStreamEvent(done=True)
