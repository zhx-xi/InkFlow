"""#766 阶段③ chat HITL 中断续跑端点 — POST /api/v1/chat/resume."""

from __future__ import annotations

import inspect
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import inkflow.api.deps as deps_module
from inkflow.api.deps import get_chat_agent_service, get_conversation_service

router = APIRouter(prefix="/api/v1/chat", tags=["AI 对话"])


class ChatResumeRequest(BaseModel):
    """HITL 中断续跑请求。conversation_id 存在性校验 + approved 布尔。"""

    conversation_id: str
    approved: bool


def _parse_conversation_id(raw: str) -> uuid.UUID:
    """conversation_id 非 UUID → ValueError（由依赖层映射 404）。"""
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="chat 会话不存在") from None


@router.post("/resume")
async def resume_chat(
    data: ChatResumeRequest,
    db: AsyncSession = Depends(deps_module.get_db),
) -> dict:
    """HITL 续跑：approved=true/false → ChatAgentService.resume 继续/中止删除。"""
    cid = _parse_conversation_id(data.conversation_id)
    # conversation 存在性校验（镜像 _chat_auth._ConversationService.get）
    conv_svc = get_conversation_service(db)
    conv = await conv_svc.get(cid)
    if conv is None:
        raise HTTPException(status_code=404, detail="chat 会话不存在")
    # 运行时经模块级 getter 取 ChatAgentService（test 契约 patch 双命名空间命中；
    # 真实路径为 async getter → await；测试 mock 为同步返回 → 直接使用）
    candidate = get_chat_agent_service(
        data=deps_module.ChatStreamRequest(
            project_id=str(conv.project_id),
            conversation_id=str(cid),
        ),
        db=db,
    )
    svc = candidate if not inspect.isawaitable(candidate) else await candidate
    await svc.resume(conversation_id=str(cid), approved=data.approved)
    return {"ok": True}
