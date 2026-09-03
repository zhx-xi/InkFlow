"""#547/#744 chat 消息持久化 API -- POST/GET /api/v1/chat/messages + conversations 线程级."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.chat_message import ChatMessage, ChatMessageCreate
from inkflow.domain.models.conversation import Conversation, ConversationCreate
from inkflow.domain.services.chat_message_service import ChatMessageService
from inkflow.infrastructure.database.repositories.chat_message_repo import (
    SQLiteChatMessageRepository,
)
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1/chat", tags=["AI 对话"])


class ChatMessagePostRequest(BaseModel):
    """chat 消息请求体（role Literal 校验；content 空白由 handler 自定义 422）。"""

    project_id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "ai"]
    content: str
    intent: Literal["content", "conversation"] | None = None


class ConversationPatchRequest(BaseModel):
    """PATCH conversation 通用请求（title 改名 #770 / delete_permission 删除权限 #766，
    至少一个字段）。"""

    title: str | None = None
    delete_permission: Literal["manual", "ask_once", "auto"] | None = None


def get_chat_message_service(db: AsyncSession) -> ChatMessageService:
    """装配 ChatMessageService（repo=SQLiteChatMessageRepository）。"""
    return ChatMessageService(repo=SQLiteChatMessageRepository(db))


def _message_to_json(message: ChatMessage | dict) -> dict:
    """消息响应序列化：mock 转 dict 原样透传，真实实体 ChatMessage -> JSON dict。"""
    if isinstance(message, dict):
        return message
    return message.model_dump(mode="json")


def _conversation_to_json(conv: Conversation | dict) -> dict:
    """线程响应序列化：mock 转 dict 原样透传；真实实体 -> conversation_id/project_id 等。"""
    if isinstance(conv, dict):
        return conv
    return {
        "conversation_id": str(conv.id),
        "project_id": str(conv.project_id),
        "created_at": conv.created_at.isoformat(),
        "is_deleted": conv.is_deleted,
        "title": conv.title,
    }


@router.post("/messages", status_code=201)
@instrument(caller_type="api")
async def post_message(
    data: ChatMessagePostRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """追加 chat 消息（content 空白 -> 422 自定义文案；role 非法 -> Pydantic 422 list）。"""
    if not data.content.strip():
        raise HTTPException(status_code=422, detail="chat 消息内容不能为空")
    svc = get_chat_message_service(db)
    created = await svc.add_message(
        ChatMessageCreate(
            project_id=data.project_id,
            conversation_id=data.conversation_id,
            role=data.role,
            content=data.content,
            intent=data.intent,
        )
    )
    return _message_to_json(created)


@router.get("/messages")
@instrument(caller_type="api")
async def list_messages(
    conversation_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """线程 chat 消息列表（升序，分页）。"""
    svc = get_chat_message_service(db)
    items, total = await svc.list_messages_by_conversation(
        conversation_id, offset=offset, limit=limit
    )
    return {
        "items": [_message_to_json(m) for m in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/conversations")
@instrument(caller_type="api")
async def list_conversations(
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """会话页聚合列表（按 updated_at 降序；total=len(items)）。

    include_deleted=true 时含已归档线程（会话页归档视图）。
    """
    svc = get_chat_message_service(db)
    items = await svc.list_conversations(include_deleted=include_deleted)
    return {"items": items, "total": len(items)}


@router.post("/conversations", status_code=201)
@instrument(caller_type="api")
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建新线程（#744 归档后开新线程：不复用旧 conversation）。"""
    svc = get_chat_message_service(db)
    # title 非空才传（#770）：保持无 title 时调用形态不变（既有契约
    # create_conversation(PROJECT_ID)），有 title 时透传
    if data.title:
        created = await svc.create_conversation(data.project_id, data.title)
    else:
        created = await svc.create_conversation(data.project_id)
    return _conversation_to_json(created)


@router.delete("/messages/{message_id}", status_code=204)
@instrument(caller_type="api")
async def delete_message(
    message_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除 chat 消息（默认归档；?force=true 真实删除，镜像 sessions 两级删除）。"""
    try:
        mid = uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="chat 消息不存在") from None
    svc = get_chat_message_service(db)
    ok = await svc.force_delete_message(mid) if force else await svc.archive_message(mid)
    if not ok:
        raise HTTPException(status_code=404, detail="chat 消息不存在")


@router.post("/messages/{message_id}/restore")
@instrument(caller_type="api")
async def restore_message(
    message_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解除归档 chat 消息（未归档幂等）。"""
    try:
        mid = uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="chat 消息不存在") from None
    svc = get_chat_message_service(db)
    message = await svc.restore_message(mid)
    if message is None:
        raise HTTPException(status_code=404, detail="chat 消息不存在")
    return _message_to_json(message)


@router.delete("/conversations/{conversation_id}", status_code=204)
@instrument(caller_type="api")
async def delete_conversation(
    conversation_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除线程（默认归档；?force=true 真实删除会话 + 消息）。"""
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="chat 会话不存在") from None
    svc = get_chat_message_service(db)
    ok = await svc.force_delete_conversation(cid) if force else await svc.archive_conversation(cid)
    if not ok:
        raise HTTPException(status_code=404, detail="chat 会话不存在")


@router.patch("/conversations/{conversation_id}")
@instrument(caller_type="api")
async def patch_conversation(
    conversation_id: str,
    data: ConversationPatchRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """PATCH 会话字段：#770 title 改名 / #766 delete_permission 删除权限
    （至少一个字段；同时提供时按 title 处理）。"""
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="chat 会话不存在") from None
    svc = get_chat_message_service(db)
    # title 改名（#770）
    if data.title is not None:
        stripped = data.title.strip()
        if not stripped:
            raise HTTPException(status_code=422, detail="会话标题不能为空")
        if len(stripped) > 200:
            raise HTTPException(status_code=422, detail="会话标题不能超过 200 个字符")
        ok = await svc.rename_conversation(cid, stripped)
        if not ok:
            raise HTTPException(status_code=404, detail="chat 会话不存在")
        return {"conversation_id": str(cid), "title": stripped}
    # delete_permission 删除权限（#766）
    if data.delete_permission is not None:
        updated = await svc.update_delete_permission(
            conversation_id=cid, delete_permission=data.delete_permission
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="chat 会话不存在")
        return updated
    # 两者皆空 → 422
    raise HTTPException(status_code=422, detail="title 或 delete_permission 至少提供一个")


@router.post("/conversations/{conversation_id}/restore")
@instrument(caller_type="api")
async def restore_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解除归档线程（无已归档会话 -> 404，镜像 delete_conversation）。"""
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="chat 会话不存在") from None
    svc = get_chat_message_service(db)
    restored = await svc.restore_conversation(cid)
    if not restored:
        raise HTTPException(status_code=404, detail="chat 会话不存在")
    return {"conversation_id": str(cid), "is_deleted": False}
