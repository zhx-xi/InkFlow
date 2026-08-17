"""F28 agent memory REST API — 偏好/统计端点（spec §3）.

与既有 agent.py / agent_runs.py 同前缀 /api/v1/agent、不同文件——FastAPI
按路由路径去重，三个 router 允许共存（本文件管 preferences/stats）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from inkflow.api.deps import get_memory_service
from inkflow.domain.models.preference import PreferenceCategory
from inkflow.domain.services.memory_service import (
    MemoryService,
    PreferenceNotFoundError,
)

router = APIRouter(prefix="/api/v1/agent", tags=["AgentMemory"])


def _dump(obj: BaseModel | dict) -> dict:
    """领域实体 → JSON dict；测试 mock 直返 dict 时原样透传（镜像 agent_runs.py 同款 helper）."""
    if isinstance(obj, dict):
        return obj
    return dict(obj.model_dump(mode="json"))


@router.get("/preferences")
async def list_preferences(
    project_id: uuid.UUID = Query(...),
    category: str | None = Query(None),
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """项目已学偏好列表（可分类过滤）→ {"items": [...], "total": N}."""
    category_enum = PreferenceCategory(category) if category else None
    items, total = await svc.list_preferences(project_id=project_id, category=category_enum)
    return {"items": [_dump(p) for p in items], "total": total}


@router.delete("/preferences/{preference_id}")
async def remove_preference(
    preference_id: str,
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """删除偏好（删除后停止注入）→ {"preference_id", "deleted": true} / 404."""
    try:
        await svc.remove_preference(preference_id)
    except PreferenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"preference_id": preference_id, "deleted": True}


@router.get("/user-preferences")
async def list_user_preferences(
    category: str | None = Query(None),
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """用户级偏好列表（全局跨项目，可分类过滤）→ {"items": [...], "total": N}（spec §3.1/§3.2）"""
    category_enum = PreferenceCategory(category) if category else None
    items, total = await svc.list_user_preferences(category=category_enum)
    return {"items": [_dump(p) for p in items], "total": total}


@router.delete("/user-preferences/{preference_id}")
async def remove_user_preference(
    preference_id: str,
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """删除用户级偏好（所有项目立即停止注入）→ {"preference_id", "deleted": true} / 404."""
    try:
        await svc.remove_user_preference(preference_id)
    except PreferenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"preference_id": preference_id, "deleted": True}


@router.get("/memory/stats")
async def memory_stats(
    project_id: uuid.UUID = Query(...),
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """修改率统计（对照 F27 基线，spec §5.7）→ stats dict 原样返回."""
    return await svc.stats(project_id=project_id)
