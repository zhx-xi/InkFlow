"""#541 chat 流式端点 + #597 chat 系统级 Agent 端点 — SSE 帧协议（镜像 writing.py F23）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import inkflow.api.deps as deps_module
from inkflow.api.deps import get_chat_agent_service
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.chat_service import ChatService, ChatStreamEvent
from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService
from inkflow.infrastructure.agent.pipeline_templates import _CHAT_ASSISTANT_PROMPT
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

router = APIRouter(prefix="/api/v1/chat", tags=["AI 对话"])


class ChatStreamRequest(BaseModel):
    """chat 流式请求体。prompt 可缺省（None）——缺失/空白由 handler 统一 422 自定义文案。"""

    project_id: str
    prompt: str | None = None
    chapter_id: str | None = None
    chapter_context: str | None = None


# #597 循环依赖规避：deps.get_chat_agent_service 的函数体惰性 import ChatStreamRequest
# （deps ↔ chat_stream 互相引用，模块级 from-import 会循环失败）；FastAPI 在端点注册时
# 需从 deps 模块全局解析该注解名，故此处把本类显式注册进 deps 命名空间（f27 绑定名
# 同一性不受影响，dependency_overrides 仍以 deps 模块函数对象为键）。
deps_module.ChatStreamRequest = ChatStreamRequest  # type: ignore[misc]  # 运行时注册：FastAPI 需从 deps 全局解析注解名（mypy 静态视图禁止对模块级类型属性重赋值）


def get_chat_service() -> ChatService:
    """装配 ChatService（llm_client + chat 系统提示词模板）。"""
    return ChatService(
        llm_client=LangChainLLMClient(),
        system_prompt=_CHAT_ASSISTANT_PROMPT,
    )


def _encode_legacy_frame(ev: ChatStreamEvent) -> str:
    """ChatStreamEvent → SSE 帧字符串（#541 既有协议，测试锁定三形态，不含 type 键）：
    - delta 帧：{"delta": str, "done": false}（恰两键）
    - done 帧：{"done": true}（恰一键）
    - error 帧：{"done": true, "error": str}
    """
    if ev.error:
        payload: dict = {"done": True, "error": ev.error}
    elif ev.done:
        payload = {"done": True}
    else:
        payload = {"delta": ev.delta, "done": False}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _encode_frame(ev: ChatStreamEvent) -> str:
    """ChatStreamEvent → SSE 帧字符串（#597 type 键扩展，spec f47 §14.2 帧表）：
    - delta → {"type": "delta", "delta": str, "done": false}
    - tool_call → {"type": "tool_call", "id"/"name"/"args", "done": false}
    - tool_result → {"type": "tool_result", "id"/"name"/"result", "done": false}
    - done → {"type": "done", "done": true}
    - error → {"type": "error", "error": str, "done": true}
    """
    type_field = ev.type or "delta"
    if type_field == "error":
        payload: dict = {"type": "error", "error": ev.error, "done": True}
    elif type_field == "done":
        payload = {"type": "done", "done": True}
    elif type_field == "tool_call":
        payload = {
            "type": "tool_call",
            "id": ev.id,
            "name": ev.name,
            "args": ev.args,
            "done": False,
        }
    elif type_field == "tool_result":
        payload = {
            "type": "tool_result",
            "id": ev.id,
            "name": ev.name,
            "result": ev.result,
            "done": False,
        }
    else:
        payload = {"type": "delta", "delta": ev.delta, "done": False}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def stream_chat(
    data: ChatStreamRequest,
    request: Request,
    svc: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """chat 流式对话 — SSE 逐 token 推送（帧协议见测试契约）。"""
    prompt = (data.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="chat 流式请求需要 prompt")

    async def _event_stream():
        try:
            async for ev in svc.stream(prompt=prompt, chapter_context=data.chapter_context):
                if await request.is_disconnected():
                    return
                yield _encode_legacy_frame(ev)
        except LLMRequestError:
            yield _encode_legacy_frame(ChatStreamEvent(done=True, error="LLM 调用失败，请稍后重试"))

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/stream")
async def stream_chat_agent(
    data: ChatStreamRequest,
    request: Request,
    svc: ChatAgentService = Depends(get_chat_agent_service),
) -> StreamingResponse:
    """chat 系统级 Agent 流式对话 — SSE 逐帧推送（spec f47 §14.2 帧表）。"""
    prompt = (data.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="chat 流式请求需要 prompt")

    async def _event_stream():
        try:
            async for ev in svc.stream_events(prompt=prompt, chapter_context=data.chapter_context):
                if await request.is_disconnected():
                    return
                yield _encode_frame(ev)
        except LLMRequestError:
            yield _encode_frame(
                ChatStreamEvent(type="error", done=True, error="LLM 调用失败，请稍后重试")
            )

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
