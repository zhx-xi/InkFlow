"""#541 ChatService 单元测试 — fake LLM 客户端，锁定 messages 组装 + delta/done 帧序列。

RED 阶段（本文件首次提交）：inkflow.domain.services.chat_service 模块不存在 →
模块级 import 抛 ModuleNotFoundError → 文件级 collection error（任务书口径的合法 RED）。

GREEN 实现契约（backend/src/inkflow/domain/services/chat_service.py）：
1. ChatStreamEvent：dataclass，字段 delta: str = ""、done: bool = False、
   error: str | None = None。
2. ChatService.__init__(self, *, llm_client, system_prompt: str)。
3. async def stream(self, prompt: str, chapter_context: str | None = None)
   -> AsyncGenerator[ChatStreamEvent, None]：
   - messages 组装（list[ChatMessage]）：
     messages[0] = ChatMessage(role="system", content=system_prompt)（system_prompt
     为已渲染完成的模板）；
     messages[1] = ChatMessage(role="user", content=prompt)——chapter_context 非空时
     user content 追加章节上下文段落（prompt + 章节上下文）。
   - async for chunk in llm_client.chat_stream(messages)：yield ChatStreamEvent(delta=chunk.content)
   - 流结束后 yield ChatStreamEvent(done=True)。
   - LLMRequestError 直接向上传播（router 层转 SSE error 帧）。
"""

from __future__ import annotations

import pytest

from inkflow.domain.ports.llm_client import ChatMessage, StreamEvent
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.chat_service import ChatService, ChatStreamEvent

SYSTEM_PROMPT = "你是资深网文创作助手，请以精炼、流畅的中文回答。"


class _FakeLLM:
    """fake llm_client — chat_stream 返回预置 chunk 序列；error 非空则抛 LLMRequestError。

    chat_stream 是普通方法返回 async generator（镜像 LLMClientProtocol 桩签名：
    `def chat_stream(...) -> AsyncGenerator[StreamEvent, None]`）。
    """

    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        self._chunks = chunks
        self._error = error
        self.calls: list[list[ChatMessage]] = []

    def chat_stream(self, messages: list[ChatMessage], **kwargs):
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        for c in self._chunks:
            yield StreamEvent(content=c)


@pytest.fixture
def svc_and_llm():
    llm = _FakeLLM(chunks=["你", "好"])
    svc = ChatService(llm_client=llm, system_prompt=SYSTEM_PROMPT)
    return svc, llm


def test_chat_stream_event_defaults() -> None:
    """ChatStreamEvent 默认值契约：delta=""、done=False、error=None。"""
    ev = ChatStreamEvent()
    assert ev.delta == ""
    assert ev.done is False
    assert ev.error is None


@pytest.mark.asyncio
async def test_stream_yields_deltas_then_done_frame(svc_and_llm) -> None:
    """chunk 序列 → delta 事件 + 终帧 done=True；delta 拼接 == "你好"。"""
    svc, _ = svc_and_llm
    events = [ev async for ev in svc.stream(prompt="你好")]
    assert [ev.delta for ev in events[:-1]] == ["你", "好"]
    assert all(not ev.done for ev in events[:-1])
    assert events[-1].done is True
    assert events[-1].delta == ""
    assert "".join(ev.delta for ev in events[:-1]) == "你好"


@pytest.mark.asyncio
async def test_messages_system_then_user(svc_and_llm) -> None:
    """chat_stream 收到 [system, user]：system=system_prompt，user 含 prompt。"""
    svc, llm = svc_and_llm
    async for _ in svc.stream(prompt="介绍一下主角"):
        pass
    (messages,) = llm.calls
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[0].content == SYSTEM_PROMPT
    assert messages[1].role == "user"
    assert "介绍一下主角" in messages[1].content


@pytest.mark.asyncio
async def test_chapter_context_appended_to_user_message(svc_and_llm) -> None:
    """chapter_context 非空 → user content 追加章节上下文段落。"""
    svc, llm = svc_and_llm
    async for _ in svc.stream(
        prompt="继续写", chapter_context="第一章：主角初入宗门，遭遇同门挑衅。"
    ):
        pass
    (messages,) = llm.calls
    assert messages[1].role == "user"
    assert "继续写" in messages[1].content
    assert "第一章：主角初入宗门，遭遇同门挑衅。" in messages[1].content


@pytest.mark.asyncio
async def test_chapter_context_none_keeps_user_content_as_prompt(svc_and_llm) -> None:
    """chapter_context 缺省 → user content 就是 prompt 本身（无追加段落）。"""
    svc, llm = svc_and_llm
    async for _ in svc.stream(prompt="继续写"):
        pass
    (messages,) = llm.calls
    assert messages[1].role == "user"
    assert messages[1].content == "继续写"


@pytest.mark.asyncio
async def test_stream_async_generator_path(svc_and_llm) -> None:
    """真实客户端路径：llm_client.chat_stream 为 async 生成器（LangChainLLMClient 形态）。

    #541 coverage 补测：既有 fake 是普通方法返回同步生成器（走 sync 分支）；
    本用例覆盖 async for 分支（hasattr(stream, '__aiter__') 为真）。
    """

    class _AsyncLLM:
        def __init__(self, chunks: list[str]) -> None:
            self._chunks = chunks

        async def chat_stream(self, messages: list[ChatMessage], **kwargs):
            for c in self._chunks:
                yield StreamEvent(content=c)

    svc = ChatService(llm_client=_AsyncLLM(["你", "好"]), system_prompt=SYSTEM_PROMPT)
    events = [ev async for ev in svc.stream(prompt="你好")]
    assert [ev.delta for ev in events[:-1]] == ["你", "好"]
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_stream_propagates_llm_error() -> None:
    """LLM 抛 LLMRequestError → 向上传播（router 层转 SSE error 帧）。"""
    llm = _FakeLLM(chunks=["你"], error=LLMRequestError("API key invalid"))
    svc = ChatService(llm_client=llm, system_prompt=SYSTEM_PROMPT)
    with pytest.raises(LLMRequestError):
        async for _ in svc.stream(prompt="你好"):
            pass
