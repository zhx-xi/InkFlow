"""#547 chat 消息持久化 API — POST/GET /api/v1/chat/messages + GET /conversations."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.chat_message import ChatMessage, ChatMessageCreate
from inkflow.domain.services.chat_message_service import ChatMessageService
from inkflow.infrastructure.database.repositories.chat_message_repo import (
    SQLiteChatMessageRepository,
)

router = APIRouter(prefix="/api/v1/chat", tags=["AI 对话"])


class ChatMessagePostRequest(BaseModel):
    """chat 消息请求体（role Literal 校验；content 空白由 handler 自定义 422）。"""

    project_id: uuid.UUID
    role: Literal["user", "ai"]
    content: str
    intent: Literal["content", "conversation"] | None = None


def get_chat_message_service(db: AsyncSession) -> ChatMessageService:
    """装配 ChatMessageService（repo=SQLiteChatMessageRepository）。"""
    return ChatMessageService(repo=SQLiteChatMessageRepository(db))


def _message_to_json(message: ChatMessage | dict) -> dict:
    """消息响应序列化：mock 轨 dict 原样透传，真实轨 ChatMessage → JSON dict。"""
    if isinstance(message, dict):
        return message
    return message.model_dump(mode="json")


@router.post("/messages", status_code=201)
async def post_message(
    data: ChatMessagePostRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """追加 chat 消息（content 空白 → 422 自定义文案；role 非法 → Pydantic 422 list）。"""
    if not data.content.strip():
        raise HTTPException(status_code=422, detail="chat 消息内容不能为空")
    svc = get_chat_message_service(db)
    created = await svc.add_message(
        ChatMessageCreate(
            project_id=data.project_id,
            role=data.role,
            content=data.content,
            intent=data.intent,
        )
    )
    return _message_to_json(created)


@router.get("/messages")
async def list_messages(
    project_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """项目 chat 消息列表（升序，分页）。"""
    svc = get_chat_message_service(db)
    items, total = await svc.list_messages(project_id, offset=offset, limit=limit)
    return {
        "items": [_message_to_json(m) for m in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """会话页聚合列表（按 updated_at 降序；total=len(items)）。"""
    svc = get_chat_message_service(db)
    items = await svc.list_conversations()
    return {"items": items, "total": len(items)}
