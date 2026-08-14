"""F36 地图管理 REST API — 12 个端点（spec §3.1/§3.3）。

端点风格沿用 F10 world_settings.py：创建/列表嵌套项目路径
（/projects/{project_id}/maps），详情/更新/删除扁平（/maps/...）；
pin 子资源挂在地图下（/maps/{map_id}/pins），pin 详情/删除扁平
（/map-pins/...）。

创建地图与换图使用 multipart/form-data（file + Form 参数，spec §3.1
拍板——图片文件不进 JSON body）；PATCH/POST pins 用 JSON body 模型。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 MapService —— 单元测试通过
`@patch("inkflow.api.routers.maps.get_map_service")` mock 服务层。

错误映射（spec §3.3 异常映射表）:
- MapServiceError 子类（同名/根地点冲突/子图删除动作等）→ 422（消息即 detail）
- MapNotFoundError / MapPinNotFoundError / ProjectNotFoundError → 404
- MapAssetError（文件层）→ 500
- 非法 UUID（_parse_id）→ 404（detail 按端点语义：地图不存在 / pin 不存在）
- 非法 root_location_id / pin location_id → 422（父地点/pin 关联地点文案）

依据: specs/f36-world-map/spec.md §3.1/§3.3。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_map_service
from inkflow.domain.models.map import MapPinCreate, MapPinUpdate, WorldMapUpdate
from inkflow.domain.ports.map_errors import (
    MapAssetError,
    MapNotFoundError,
    MapPinNotFoundError,
    MapServiceError,
)
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.services.map_service import MapService

router = APIRouter(prefix="/api/v1", tags=["地图"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 F9 characters.py）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail=detail) from err


def _parse_location_id(location_id: str, detail: str) -> uuid.UUID:
    """解析地点 UUID 查询参数；非法 → 422（spec §3.1 父地点/pin 地点文案）。"""
    try:
        return uuid.UUID(location_id)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=detail) from err


def _get_svc(db: AsyncSession) -> MapService:
    """获取 MapService 实例（方便 mock）。"""
    return get_map_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）。"""
    try:
        return await coro
    except MapServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except MapNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except MapPinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except MapAssetError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── 地图 CRUD ───────────────────────────────────────────────


@router.post("/projects/{project_id}/maps", status_code=201)
async def create_map(
    project_id: str,
    file: UploadFile | None = File(None),
    name: str = Form(...),
    description: str = Form(""),
    root_location_id: str | None = Form(None),
    parent_map_id: str | None = Form(None),  # #368 v1.3：图挂父图 id
    bg_source: str = Form("image"),
    db: AsyncSession = Depends(get_db),
):
    """创建地图（multipart：图片文件 + Form 字段；spec §3.1 + F43 P2 bg_source）。

    F43 P2: bg_source=shape 时 file 可选（无图 → image_path 存空串）；读不到
    文件内容时透传空 bytes + 空 filename，由 service 按 bg_source 校验。
    #368 v1.3: parent_map_id=父图 id（None=根图）——router 侧解析非法 UUID → 422
    「父地图不存在或不在同一项目」；父图校验由 service 抛出 MapParentMapNotFoundError
    （继承 MapServiceError → _run_service 自动映射 422）。
    """
    pid = _parse_id(project_id, detail="项目不存在")
    root_uuid: uuid.UUID | None = None
    if root_location_id is not None:
        # router 侧解析；解析失败不调 service（测试锁定）
        root_uuid = _parse_location_id(root_location_id, detail="父地点不存在或不在同一项目")
    parent_uuid: uuid.UUID | None = None
    if parent_map_id is not None:
        # router 侧解析；解析失败不调 service（与 root_location_id 同款）
        parent_uuid = _parse_location_id(parent_map_id, detail="父地图不存在或不在同一项目")
    content = await file.read() if file is not None else b""
    filename = (file.filename or "main.png") if file is not None else ""
    svc = _get_svc(db)
    # F43 P2/ #368 v1.3: 非默认 bg_source / parent_map_id 以 kwargs 透传；缺省形态
    # 保持既有 6 参调用（兼容既有 F36 API 测试断言，服务层默认值一致）
    create_kwargs: dict[str, Any] = {}
    if bg_source != "image":
        create_kwargs["bg_source"] = bg_source
    if parent_uuid is not None:
        create_kwargs["parent_map_id"] = parent_uuid
    wm = await _run_service(
        svc.create_map(pid, name, description, root_uuid, filename, content, **create_kwargs)
    )
    return wm.model_dump(mode="json")


@router.get("/projects/{project_id}/maps")
async def list_maps(
    project_id: str,
    root_location_id: str | None = Query(None),
    offset: int = Query(0),
    limit: int = Query(50),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内地图列表（?root_location_id=<uuid> 过滤 / none=全局图，spec §3.1）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    if root_location_id is not None and root_location_id.lower() == "none":
        items, total = await _run_service(svc.list_maps(pid, top_level_only=True))
    elif root_location_id:
        root_uuid = _parse_location_id(root_location_id, detail="父地点不存在或不在同一项目")
        items, total = await _run_service(svc.list_maps(pid, root_location_id=root_uuid))
    else:
        items, total = await _run_service(svc.list_maps(pid))
    return {
        "items": [m.model_dump(mode="json") for m in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/maps/{map_id}")
async def get_map(
    map_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取地图详情（spec §3.1）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    svc = _get_svc(db)
    wm = await _run_service(svc.get_map(sid))
    if wm is None:
        raise HTTPException(status_code=404, detail="地图不存在")
    return wm.model_dump(mode="json")


@router.get("/maps/{map_id}/image")
async def get_map_image(
    map_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取地图图片（FileResponse；spec §3.1）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    svc = _get_svc(db)
    path = await _run_service(svc.get_image_file(sid))
    if path is None:
        raise HTTPException(status_code=404, detail="地图不存在")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片文件缺失")
    return FileResponse(path)


@router.get("/maps/{map_id}/children")
async def get_map_children(
    map_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取地图子地图列表（drill-down，spec §3.1）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    svc = _get_svc(db)
    items = await _run_service(svc.children(sid))
    return {"items": [m.model_dump(mode="json") for m in items], "total": len(items)}


@router.patch("/maps/{map_id}")
async def update_map(
    map_id: str,
    data: WorldMapUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新地图元数据（WorldMapUpdate 全可选，exclude_unset 语义，spec §3.1）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    svc = _get_svc(db)
    wm = await _run_service(svc.update_map(sid, data))
    if wm is None:
        raise HTTPException(status_code=404, detail="地图不存在")
    return wm.model_dump(mode="json")


@router.put("/maps/{map_id}/image")
async def replace_map_image(
    map_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """替换地图图片（multipart；先写新成功后删旧由 service 编排，spec §5.1 D5）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    content = await file.read()
    svc = _get_svc(db)
    wm = await _run_service(svc.replace_image(sid, file.filename or "main.png", content))
    if wm is None:
        raise HTTPException(status_code=404, detail="地图不存在")
    return wm.model_dump(mode="json")


@router.delete("/maps/{map_id}", status_code=204)
async def delete_map(
    map_id: str,
    cascade: bool = Query(False),
    reparent_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """真删地图（D6 参数矩阵：?cascade=true 级联 | ?reparent_to=<id> 子改挂，spec §3.1）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    svc = _get_svc(db)
    if reparent_to is not None:
        ruuid = _parse_id(reparent_to, detail="reparent 目标地图不存在/不在同一项目/是自身子孙地图")
        await _run_service(svc.delete_map(sid, reparent_to=ruuid))
    elif cascade:
        await _run_service(svc.delete_map(sid, cascade=True))
    else:
        await _run_service(svc.delete_map(sid))


# ── pin CRUD ────────────────────────────────────────────────


@router.post("/maps/{map_id}/pins", status_code=201)
async def add_pin(
    map_id: str,
    data: MapPinCreate,
    db: AsyncSession = Depends(get_db),
):
    """添加地图 pin（JSON body；坐标 0-100 Pydantic 校验，spec §3.1 + F43 P2 type/ref_id）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    svc = _get_svc(db)
    # F43 P2: type/ref_id 仅非默认值时以 kwargs 透传——默认值走既有 5 参形态
    # （兼容既有 F36 测试断言）；显式值锁定 kwargs 形态（mock 位置/关键字比较分离）
    pin_kwargs: dict[str, Any] = {}
    if data.type != "location":
        pin_kwargs["type"] = data.type
    if data.ref_id is not None:
        pin_kwargs["ref_id"] = data.ref_id
    pin = await _run_service(
        svc.add_pin(sid, data.location_id, data.x, data.y, data.label, **pin_kwargs)
    )
    return pin.model_dump(mode="json")


@router.get("/maps/{map_id}/pins")
async def list_pins(
    map_id: str,
    location_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取地图 pin 列表（?location_id=<uuid> 过滤可选，spec §3.1）。"""
    sid = _parse_id(map_id, detail="地图不存在")
    svc = _get_svc(db)
    if location_id:
        luuid = _parse_location_id(location_id, detail="pin 关联地点不存在或不在同一项目")
        items = await _run_service(svc.list_pins(sid, location_id=luuid))
    else:
        items = await _run_service(svc.list_pins(sid))
    return {"items": [p.model_dump(mode="json") for p in items], "total": len(items)}


@router.patch("/map-pins/{pin_id}")
async def update_pin(
    pin_id: str,
    data: MapPinUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新 pin（全可选，exclude_unset 语义，spec §3.1）。"""
    pid = _parse_id(pin_id, detail="pin 不存在")
    svc = _get_svc(db)
    pin = await _run_service(svc.update_pin(pid, data))
    if pin is None:
        raise HTTPException(status_code=404, detail="pin 不存在")
    return pin.model_dump(mode="json")


@router.delete("/map-pins/{pin_id}", status_code=204)
async def delete_pin(
    pin_id: str,
    db: AsyncSession = Depends(get_db),
):
    """真删 pin（spec §3.1）。"""
    pid = _parse_id(pin_id, detail="pin 不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_pin(pid))
    if not ok:
        raise HTTPException(status_code=404, detail="pin 不存在")
