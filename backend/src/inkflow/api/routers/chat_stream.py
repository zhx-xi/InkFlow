"""#541 chat 流式端点 — POST /api/v1/chat/stream（SSE 帧协议镜像 writing.py F23）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.chat_service import ChatService, ChatStreamEvent
from inkflow.infrastructure.agent.pipeline_templates import _CHAT_ASSISTANT_PROMPT
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

router = APIRouter(prefix="/api/v1/chat", tags=["AI 对话"])


class ChatStreamRequest(BaseModel):
    """chat 流式请求体。prompt 可缺省（None）——缺失/空白由 handler 统一 422 自定义文案。"""

    project_id: str
    prompt: str | None = None
    chapter_id: str | None = None
    chapter_context: str | None = None


def get_chat_service() -> ChatService:
    """装配 ChatService（llm_client + chat 系统提示词模板）。"""
    return ChatService(
        llm_client=LangChainLLMClient(),
        system_prompt=_CHAT_ASSISTANT_PROMPT,
    )


def _encode_frame(ev: ChatStreamEvent) -> str:
    """ChatStreamEvent → SSE 帧字符串（测试锁定三形态）：
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
            async for ev in svc.stream(
                prompt=prompt, chapter_context=data.chapter_context
            ):
                if await request.is_disconnected():
                    return
                yield _encode_frame(ev)
        except LLMRequestError:
            yield _encode_frame(
                ChatStreamEvent(done=True, error="LLM 调用失败，请稍后重试")
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
