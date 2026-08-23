"""项目 REST API 路由 — 7 个端点：CRUD + 软删除 + 恢复。

注意：各端点通过 `Depends(get_db)` 注入数据库 session，然后直接调用
模块级别的 `get_project_service(db)` 来创建 service 实例。这种写法
使得单元测试可以通过 `@patch("inkflow.api.routers.project.get_project_service")`
来 mock service 层。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_project_service
from inkflow.domain.models.project import ProjectConfig, ProjectCreate, ProjectUpdate
from inkflow.domain.services.project_service import ProjectService


def _parse_project_id(project_id: str) -> uuid.UUID:
    """安全解析项目 ID，无效格式返回 404。"""
    try:
        return uuid.UUID(project_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail="项目不存在") from err


def _get_svc(db: AsyncSession) -> ProjectService:
    """获取 ProjectService 实例（方便 mock）。"""
    return get_project_service(db)


router = APIRouter(prefix="/api/v1/projects", tags=["项目"])


@router.post("", status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新项目。"""
    service = _get_svc(db)
    config = data.config or ProjectConfig()
    if data.template_id is not None:
        config = config.model_copy(update={"template_id": str(data.template_id)})
    project = await service.create_project(
        name=data.name,
        tags=data.tags,
        language=data.language,
        target_words=data.target_words,
        config=config,
    )
    return project.model_dump(mode="json")


@router.get("")
async def list_projects(
    search: str | None = Query(None),
    sort_by: str = Query("updated_at"),
    sort_desc: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取项目列表（分页，支持搜索/排序）。"""
    service = _get_svc(db)
    items, total = await service.list_projects(
        search=search,
        sort_by=sort_by,
        sort_desc=sort_desc,
        offset=offset,
        limit=limit,
    )
    return {
        "items": [p.model_dump(mode="json") for p in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取项目详情。"""
    pid = _parse_project_id(project_id)
    service = _get_svc(db)
    project = await service.get(pid)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project.model_dump(mode="json")


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新项目。"""
    pid = _parse_project_id(project_id)
    service = _get_svc(db)
    try:
        project = await service.update(pid, data)
    except ValueError as e:
        # C1：agent_order 语义校验（配置驱动模式缺启用角色等）→ 422 + 中文 detail
        raise HTTPException(status_code=422, detail=str(e)) from e
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project.model_dump(mode="json")


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除项目（默认软删除，?force=true 为硬删除）。"""
    pid = _parse_project_id(project_id)
    service = _get_svc(db)
    if force:
        success = await service.hard_delete(pid)
    else:
        success = await service.soft_delete(pid)
    if not success:
        raise HTTPException(status_code=404, detail="项目不存在")


@router.post("/{project_id}/restore")
async def restore_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """从回收站恢复项目。"""
    pid = _parse_project_id(project_id)
    service = _get_svc(db)
    project = await service.restore(pid)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project.model_dump(mode="json")
