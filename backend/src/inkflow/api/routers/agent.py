"""Agent 管线 REST API 端点。"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_summary_service
from inkflow.domain.models.agent_pipeline import PipelineConfig, PipelineExecuteRequest
from inkflow.domain.ports.agent_pipeline import PipelineStreamEvent
from inkflow.domain.services.agent_service import AgentService, AgentServiceError
from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline
from inkflow.infrastructure.agent.supervisor_pipeline import SupervisorPipeline
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

router = APIRouter(prefix="/api/v1/agent", tags=["Agent"])


class ConfirmRequest(BaseModel):
    """HITL 确认请求体。"""

    approved: bool = Field(..., description="True=继续执行；False=拒绝（回退固定链）")
    comment: str | None = Field(default=None, description="确认备注（可选）")


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 UUID。"""
    try:
        return uuid.UUID(id_str)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=detail) from err


# HITL 进程内共享单例：checkpointer 存于实例内，execute/confirm 须同实例（#343 根因 5）
_supervisor_pipeline: SupervisorPipeline | None = None


def _svc(db: AsyncSession) -> AgentService:
    """获取 AgentService 实例（static + supervisor 双管线装配，#414 repo 注入保持）。"""
    global _supervisor_pipeline
    from inkflow.infrastructure.database.repositories.character_repo import (
        SQLiteCharacterRepository,
    )
    from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository
    from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository

    llm_client = LangChainLLMClient()
    pipeline = LangGraphAgentPipeline(llm_client=llm_client)
    if _supervisor_pipeline is None:
        _supervisor_pipeline = SupervisorPipeline(llm_client=llm_client)
    return AgentService(
        pipeline=pipeline,
        db_session=db,
        summary_service=get_summary_service(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        outline_repo=SQLiteOutlineRepository(db),
        supervisor_pipeline=_supervisor_pipeline,
    )


def _encode_frame_pipeline(ev: PipelineStreamEvent) -> str:
    """PipelineStreamEvent → SSE 帧字符串（#642-1，镜像 chat_stream._encode_frame）：
    stage → {"type":"stage","stage_id":...,"stage_name":...,"done":false}
    delta → {"type":"delta","delta":...,"done":false}
    done → {"type":"done","done":true,"final_output":...,"intent":"content"[, "execution_id"]}
    error → {"type":"error","error":...,"done":true}
    """
    if getattr(ev, "type", "") == "stage":
        # #681：阶段切换帧——必须在 error/done 分支之前（stage 帧 done=False 否则落入 delta 分支）
        payload: dict = {
            "type": "stage",
            "stage_id": ev.stage_id,
            "stage_name": ev.stage_name,
            "done": False,
        }
    elif ev.error:
        payload = {"type": "error", "error": ev.error, "done": True}
    elif ev.done:
        payload = {"type": "done", "done": True}
        if ev.final_output:
            payload["final_output"] = ev.final_output
        if ev.intent:
            payload["intent"] = ev.intent
        if ev.execution_id:
            payload["execution_id"] = ev.execution_id
    else:
        payload = {"type": "delta", "delta": ev.delta, "done": False}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _encode_pipeline_error(message: str) -> str:
    """异常兜底 → SSE error 帧（done=true，协议 §5）。"""
    return _encode_frame_pipeline(PipelineStreamEvent(type="done", done=True, error=message))


@router.post("/pipelines/stream")
async def stream_pipeline(
    data: PipelineExecuteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """#642-1：管线 SSE 流式执行。done 帧携带 final_output + intent='content'。"""
    # 校验（镜像 execute_pipeline：builtin:chat 单轮对话必须携带非空 variables.prompt）
    if data.pipeline == "builtin:chat" and not ((data.variables or {}).get("prompt") or "").strip():
        raise HTTPException(status_code=422, detail="chat 管线需要 variables.prompt")
    svc = _svc(db)

    async def _event_stream():
        try:
            async for ev in svc.stream_pipeline(data):
                if await request.is_disconnected():
                    return
                yield _encode_frame_pipeline(ev)
        except Exception as e:
            yield _encode_pipeline_error(str(e))

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/pipelines/execute", status_code=202)
async def execute_pipeline(
    data: PipelineExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """执行管线（异步），返回 202。"""
    # F47 #379：builtin:chat 单轮对话必须携带非空 variables.prompt
    if data.pipeline == "builtin:chat" and not ((data.variables or {}).get("prompt") or "").strip():
        raise HTTPException(status_code=422, detail="chat 管线需要 variables.prompt")
    svc = _svc(db)
    try:
        return await svc.execute(data)
    except AgentServiceError as e:
        detail = str(e)
        if "项目不存在" in detail or "章节不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        raise HTTPException(status_code=422, detail=detail) from e


@router.get("/pipelines/executions/{execution_id}")
async def get_execution_status(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
):
    """查询执行状态。"""
    svc = _svc(db)
    result = await svc.get_status(execution_id)
    if result is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return result


@router.post("/pipelines/executions/{execution_id}/confirm")
async def confirm_execution(
    execution_id: str,
    data: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """HITL 人工确认（waiting_hitl 执行记录 → resume/回退）。"""
    svc = _svc(db)
    try:
        return await svc.confirm_execution(execution_id, approved=data.approved)
    except AgentServiceError as e:
        detail = str(e)
        if "执行记录不存在" in detail:
            raise HTTPException(status_code=404, detail=detail) from e
        raise HTTPException(status_code=422, detail=detail) from e


@router.get("/pipelines/executions")
async def list_executions(
    project_id: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询执行记录列表。"""
    svc = _svc(db)
    return await svc.list_executions(project_id, limit)


@router.post("/pipelines/validate")
async def validate_pipeline(
    config: PipelineConfig,
    db: AsyncSession = Depends(get_db),
):
    """校验管线配置。"""
    svc = _svc(db)
    return svc.validate_pipeline(config)


@router.get("/pipelines/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    """列出内置管线模板。"""
    svc = _svc(db)
    return svc.list_templates()
