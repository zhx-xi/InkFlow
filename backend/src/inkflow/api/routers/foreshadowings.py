"""F13 伏笔管理 REST API — 8 个端点：伏笔 CRUD + restore/resolve/reopen 状态机动作。

端点风格沿用 F2/F9/F10/F11/F12（spec §3.1）：创建/列表嵌套项目路径
（/projects/{project_id}/foreshadowings），详情/更新/删除/状态动作扁平
（/foreshadowings/{foreshadowing_id}...）。`/foreshadowings` 下全部为
静态路径段 + 固定动作段（restore/resolve/reopen），无动态段冲突，
无需注册顺序注意。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 ForeshadowingService —— 单元测试通过
`@patch("inkflow.api.routers.foreshadowings.get_foreshadowing_service")`
来 mock 服务层（同 F9/F10/F11/F12 模式）。

错误映射（spec §3.4 异常映射表）:
- 无效 UUID / 资源不存在（Service 返回 None）→ 404
- ForeshadowingServiceError 子类（同名冲突 / 事件锚点校验失败 /
  配置错误）→ 422（消息即 detail）
- ForeshadowingNotFoundError / ProjectNotFoundError → 404
- 无 LLM 相关错误（F13 无 LLM，伏笔状态追踪为确定性逻辑）

依据: specs/f13-foreshadowing-service/spec.md §3/§5/§7。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_foreshadowing_service
from inkflow.domain.models.foreshadowing import (
    ForeshadowingCreate,
    ForeshadowingUpdate,
    _validate_description,
    _validate_location,
    _validate_priority,
    _validate_title,
)
from inkflow.domain.ports.foreshadowing_errors import (
    ForeshadowingNotFoundError,
    ForeshadowingServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.services.foreshadowing_service import ForeshadowingService

router = APIRouter(prefix="/api/v1", tags=["伏笔"])


def _parse_id(id_str: str, detail: str = "伏笔不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 F9/F10/F11/F12）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError):
            raise HTTPException(status_code=404, detail=detail)


def _get_svc(db: AsyncSession) -> ForeshadowingService:
    """获取 ForeshadowingService 实例（方便 mock）。"""
    return get_foreshadowing_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.4）。"""
    try:
        return await coro
    except ForeshadowingServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ForeshadowingNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class ForeshadowingCreateBody(BaseModel):
    """创建伏笔请求体 — project_id 取自路径参数，不在 body（spec §3.2）。"""

    title: str
    description: str = ""
    priority: int = 50
    location: str = ""
    event_id: uuid.UUID | None = None  # F12 事件锚点（None = 不挂接；存在性校验在服务层）

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """验证伏笔名：去空白后非空且不超过 100 字符."""
        return _validate_title(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证伏笔详情：不超过 5000 字符."""
        return _validate_description(v)

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        """验证注入优先级：0-100 闭区间."""
        return _validate_priority(v)

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str) -> str:
        """验证埋设位置：去空白且不超过 200 字符（空串合法）."""
        return _validate_location(v)


# ── 创建/列表（嵌套项目路径）────────────────────────────────


@router.post("/projects/{project_id}/foreshadowings", status_code=201)
async def create_foreshadowing(
    project_id: str,
    data: ForeshadowingCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建伏笔（spec §3.2；status 固定为 open，回收走 resolve 端点）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    foreshadowing = await _run_service(
        svc.create(
            ForeshadowingCreate(
                project_id=pid,
                title=data.title,
                description=data.description,
                priority=data.priority,
                location=data.location,
                event_id=data.event_id,
            )
        )
    )
    return foreshadowing.model_dump(mode="json")


@router.get("/projects/{project_id}/foreshadowings")
async def list_foreshadowings(
    project_id: str,
    search: str | None = Query(None),
    status: str | None = Query(None),
    sort_by: str = Query("priority"),
    sort_desc: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内伏笔列表（搜索 + 状态过滤 + 排序 + 分页，spec §6.3）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    items, total = await _run_service(
        svc.list(
            pid,
            search=search,
            status=status,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )
    )
    return {
        "items": [f.model_dump(mode="json") for f in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ── 详情/更新/删除/状态动作（扁平路径）──────────────────────


@router.get("/foreshadowings/{foreshadowing_id}")
async def get_foreshadowing(
    foreshadowing_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取伏笔详情（spec §3.1）。"""
    fid = _parse_id(foreshadowing_id, detail="伏笔不存在")
    svc = _get_svc(db)
    foreshadowing = await _run_service(svc.get(fid))
    if foreshadowing is None:
        raise HTTPException(status_code=404, detail="伏笔不存在")
    return foreshadowing.model_dump(mode="json")


@router.patch("/foreshadowings/{foreshadowing_id}")
async def update_foreshadowing(
    foreshadowing_id: str,
    data: ForeshadowingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新伏笔（ForeshadowingUpdate 全可选，exclude_unset 语义；status 不可改）。

    event_id 双语义（spec §2.5）: None 不修改；"" 解除事件挂接；UUID 挂接。
    """
    fid = _parse_id(foreshadowing_id, detail="伏笔不存在")
    svc = _get_svc(db)
    foreshadowing = await _run_service(svc.update(fid, data))
    if foreshadowing is None:
        raise HTTPException(status_code=404, detail="伏笔不存在")
    return foreshadowing.model_dump(mode="json")


@router.delete("/foreshadowings/{foreshadowing_id}", status_code=204)
async def delete_foreshadowing(
    foreshadowing_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除伏笔（默认软删除，?force=true 硬删除，spec §3.1/§7）。"""
    fid = _parse_id(foreshadowing_id, detail="伏笔不存在")
    svc = _get_svc(db)
    if force:
        ok = await _run_service(svc.hard_delete(fid))
    else:
        ok = await _run_service(svc.soft_delete(fid))
    if not ok:
        raise HTTPException(status_code=404, detail="伏笔不存在")


@router.post("/foreshadowings/{foreshadowing_id}/restore")
async def restore_foreshadowing(
    foreshadowing_id: str,
    db: AsyncSession = Depends(get_db),
):
    """恢复软删除伏笔（原 status/resolved_at 原样保留，spec §2.4）。"""
    fid = _parse_id(foreshadowing_id, detail="伏笔不存在")
    svc = _get_svc(db)
    foreshadowing = await _run_service(svc.restore(fid))
    if foreshadowing is None:
        raise HTTPException(status_code=404, detail="伏笔不存在")
    return foreshadowing.model_dump(mode="json")


@router.post("/foreshadowings/{foreshadowing_id}/resolve")
async def resolve_foreshadowing(
    foreshadowing_id: str,
    db: AsyncSession = Depends(get_db),
):
    """标记回收（spec §2.4: open→resolved，自动设置 resolved_at；已 resolved 幂等）。"""
    fid = _parse_id(foreshadowing_id, detail="伏笔不存在")
    svc = _get_svc(db)
    foreshadowing = await _run_service(svc.resolve(fid))
    if foreshadowing is None:
        raise HTTPException(status_code=404, detail="伏笔不存在")
    return foreshadowing.model_dump(mode="json")


@router.post("/foreshadowings/{foreshadowing_id}/reopen")
async def reopen_foreshadowing(
    foreshadowing_id: str,
    db: AsyncSession = Depends(get_db),
):
    """重新开启（spec §2.4: resolved→open，清空 resolved_at；已 open 幂等）。"""
    fid = _parse_id(foreshadowing_id, detail="伏笔不存在")
    svc = _get_svc(db)
    foreshadowing = await _run_service(svc.reopen(fid))
    if foreshadowing is None:
        raise HTTPException(status_code=404, detail="伏笔不存在")
    return foreshadowing.model_dump(mode="json")
