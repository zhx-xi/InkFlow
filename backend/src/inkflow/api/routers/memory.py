"""F28 agent memory REST API — 偏好/统计端点（spec §3）.

与既有 agent.py / agent_runs.py 同前缀 /api/v1/agent、不同文件——FastAPI
按路由路径去重，三个 router 允许共存（本文件管 preferences/stats）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from inkflow.api.deps import get_memory_service
from inkflow.domain.models.preference import PreferenceCategory
from inkflow.domain.ports.semantic_summary_errors import SemanticSummaryError
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


class ProjectPreferenceCreate(BaseModel):
    """手动创建项目偏好请求体（#521）."""

    project_id: uuid.UUID
    category: PreferenceCategory
    pattern: str = Field(min_length=1)
    value: str = Field(min_length=1)
    confidence: float | None = None
    count: int | None = None


class UserPreferenceCreate(BaseModel):
    """手动创建用户级偏好请求体（#521）."""

    category: PreferenceCategory
    pattern: str = Field(min_length=1)
    value: str
    confidence: float | None = None
    count: int | None = None


class PreferenceUpdate(BaseModel):
    """偏好编辑请求体（#521）：至少提供一个编辑字段."""

    category: PreferenceCategory | None = None
    pattern: str | None = None
    value: str | None = None

    @model_validator(mode="after")
    def _check_not_all_empty(self) -> PreferenceUpdate:
        if not any((self.category is not None, self.pattern, self.value)):
            raise ValueError("至少提供一个编辑字段")
        if self.pattern is not None and not self.pattern.strip():
            raise ValueError("pattern 不能为空")
        if self.value is not None and not self.value.strip():
            raise ValueError("value 不能为空")
        return self


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


@router.post("/preferences", status_code=201)
async def create_preference(
    body: ProjectPreferenceCreate,
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """手动创建项目偏好（#521）→ 201 flat ProjectPreference dict."""
    pref = await svc.create_preference(**body.model_dump())
    return _dump(pref)


@router.post("/user-preferences", status_code=201)
async def create_user_preference(
    body: UserPreferenceCreate,
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """手动创建用户级偏好（#521）→ 201 flat UserPreference dict."""
    pref = await svc.create_user_preference(**body.model_dump())
    return _dump(pref)


@router.patch("/preferences/{preference_id}")
async def update_preference(
    preference_id: str,
    body: PreferenceUpdate,
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """编辑项目偏好（#521）→ 200 flat ProjectPreference dict / 404."""
    try:
        pref = await svc.update_preference(preference_id, **body.model_dump(exclude_unset=True))
    except PreferenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _dump(pref)


@router.patch("/user-preferences/{preference_id}")
async def update_user_preference(
    preference_id: str,
    body: PreferenceUpdate,
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """编辑用户级偏好（#521）→ 200 flat UserPreference dict / 404."""
    try:
        pref = await svc.update_user_preference(
            preference_id, **body.model_dump(exclude_unset=True)
        )
    except PreferenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _dump(pref)


@router.get("/memory/stats")
async def memory_stats(
    project_id: uuid.UUID = Query(...),
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """修改率统计（对照 F27 基线，spec §5.7）→ stats dict 原样返回."""
    return await svc.stats(project_id=project_id)


@router.get("/memory/summaries")
async def memory_summaries(
    project_id: uuid.UUID = Query(...),
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """语义总结列表（项目级 + 用户级，spec §3.1）→ {"project_id", "project"|None, "user"|None}."""
    return await svc.get_summaries(project_id=project_id)


@router.post("/memory/summarize")
async def memory_summarize(
    project_id: uuid.UUID = Query(...),
    force: bool = Query(False, description="忽略锚点哈希强制重新总结（CLI --force）"),
    svc: MemoryService = Depends(get_memory_service),
) -> dict:
    """手动触发语义总结（幂等——锚点未变化返回既有总结，spec §3.1/§3.2）→ 502."""
    try:
        return await svc.summarize(project_id=project_id, force=force)
    except SemanticSummaryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
