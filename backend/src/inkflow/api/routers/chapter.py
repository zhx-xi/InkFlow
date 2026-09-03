"""章节 REST API — Volume + Chapter CRUD 端点.

注意：各端点通过 `Depends(get_db)` 注入数据库 session，然后直接调用
模块级别的 `get_chapter_service(db)` 来创建 service 实例。这种写法
使得单元测试可以通过 `@patch("inkflow.api.routers.chapter.get_chapter_service")`
来 mock service 层。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_chapter_service, get_db
from inkflow.domain.models.chapter import (
    ChapterCreate,
    ChapterStatus,
    ChapterUpdate,
    VolumeCreate,
    VolumeUpdate,
)
from inkflow.domain.services.chapter_service import (
    ChapterService,
    VolumeMoveError,
    VolumeNotEmptyError,
)
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1", tags=["章节"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail=detail) from err


def _svc(db: AsyncSession) -> ChapterService:
    """获取 ChapterService 实例（方便 mock）。"""
    return get_chapter_service(db)


# ---- Volume ----


@router.post("/projects/{project_id}/volumes", status_code=201)
@instrument(caller_type="api")
async def create_volume(project_id: str, data: VolumeCreate, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    pid = _parse_id(project_id, detail="项目不存在")
    vol = await svc.create_volume(pid, data.title, data.order_index)
    return vol.model_dump(mode="json")


@router.get("/projects/{project_id}/volumes")
@instrument(caller_type="api")
async def list_volumes(project_id: str, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    pid = _parse_id(project_id, detail="项目不存在")
    volumes = await svc.list_volumes(pid)
    return {"items": [v.model_dump(mode="json") for v in volumes]}


@router.get("/volumes/{volume_id}")
@instrument(caller_type="api")
async def get_volume(volume_id: str, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    vid = _parse_id(volume_id, detail="卷不存在")
    vol = await svc.get_volume(vid)
    if vol is None:
        raise HTTPException(status_code=404, detail="卷不存在")
    return vol.model_dump(mode="json")


@router.patch("/volumes/{volume_id}")
@instrument(caller_type="api")
async def update_volume(volume_id: str, data: VolumeUpdate, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    vid = _parse_id(volume_id, detail="卷不存在")
    vol = await svc.update_volume(vid, data)
    if vol is None:
        raise HTTPException(status_code=404, detail="卷不存在")
    return vol.model_dump(mode="json")


@router.delete("/volumes/{volume_id}", status_code=204)
@instrument(caller_type="api")
async def delete_volume(
    volume_id: str,
    delete_chapters: bool = Query(False),
    move_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    vid = _parse_id(volume_id, detail="卷不存在")
    mvid = _parse_id(move_to, detail="目标卷不存在") if move_to else None
    try:
        ok = await svc.delete_volume(vid, delete_chapters=delete_chapters, move_to=mvid)
    except VolumeNotEmptyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except VolumeMoveError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="卷不存在")


# ---- Chapter ----


@router.post("/projects/{project_id}/chapters", status_code=201)
@instrument(caller_type="api")
async def create_chapter(project_id: str, data: ChapterCreate, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    pid = _parse_id(project_id, detail="项目不存在")
    ch = await svc.create_chapter(
        pid,
        data.title,
        data.volume_id,
        data.content,
        data.order_index,
    )
    return ch.model_dump(mode="json")


@router.get("/projects/{project_id}/chapters")
@instrument(caller_type="api")
async def list_chapters(
    project_id: str,
    volume_id: str | None = Query(None),
    status: ChapterStatus | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    pid = _parse_id(project_id, detail="项目不存在")
    vid = _parse_id(volume_id) if volume_id else None
    items, total = await svc.list_chapters(pid, vid, status, offset, limit)
    return {
        "items": [c.model_dump(mode="json") for c in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/chapters/{chapter_id}")
@instrument(caller_type="api")
async def get_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    cid = _parse_id(chapter_id, detail="章节不存在")
    ch = await svc.get_chapter(cid)
    if ch is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ch.model_dump(mode="json")


@router.patch("/chapters/{chapter_id}")
@instrument(caller_type="api")
async def update_chapter(chapter_id: str, data: ChapterUpdate, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    cid = _parse_id(chapter_id, detail="章节不存在")
    ch = await svc.update_chapter(cid, data)
    if ch is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ch.model_dump(mode="json")


@router.delete("/chapters/{chapter_id}", status_code=204)
@instrument(caller_type="api")
async def delete_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)):
    svc = _svc(db)
    cid = _parse_id(chapter_id, detail="章节不存在")
    ok = await svc.delete_chapter(cid)
    if not ok:
        raise HTTPException(status_code=404, detail="章节不存在")


@router.post("/chapters/{chapter_id}/move")
@instrument(caller_type="api")
async def move_chapter(
    chapter_id: str,
    target_volume_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    cid = _parse_id(chapter_id, detail="章节不存在")
    tvid = _parse_id(target_volume_id) if target_volume_id else None
    ch = await svc.move_chapter(cid, tvid)
    if ch is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ch.model_dump(mode="json")
