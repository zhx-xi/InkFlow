"""Agent 管线 REST API 端点。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.agent_pipeline import PipelineConfig, PipelineExecuteRequest
from inkflow.domain.services.agent_service import AgentService, AgentServiceError
from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

router = APIRouter(prefix="/api/v1/agent", tags=["Agent"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 UUID。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        raise HTTPException(status_code=404, detail=detail)


def _svc(db: AsyncSession) -> AgentService:
    """获取 AgentService 实例。"""
    pipeline = LangGraphAgentPipeline(llm_client=LangChainLLMClient())
    return AgentService(pipeline=pipeline, db_session=db)


@router.post("/pipelines/execute", status_code=202)
async def execute_pipeline(
    data: PipelineExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """执行管线（异步），返回 202。"""
    svc = _svc(db)
    try:
        return await svc.execute(data)
    except AgentServiceError as e:
        detail = str(e)
        if "项目不存在" in detail or "章节不存在" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=422, detail=detail)


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
