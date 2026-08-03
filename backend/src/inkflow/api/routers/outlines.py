"""F11 大纲管理 REST API — 19 个端点：大纲/情节点/弧线 CRUD + AI 生成.

端点风格沿用 F2/F9/F10（spec §3.1）：创建/列表嵌套项目或大纲路径
（/projects/{project_id}/outlines、/outlines/{outline_id}/plot-points），
详情/更新/删除扁平（/outlines/...、/plot-points/...、/story-arcs/...）。
AI 生成为 POST /outlines/generate，注册在 /outlines/{outline_id} 系列
之前避免路径歧义（同 F9 characters.py / F10 world_settings.py 做法）。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 OutlineService —— 单元测试通过
`@patch("inkflow.api.routers.outlines.get_outline_service")` 来
mock 服务层（同 F9/F10 模式）。

聚合字段（spec §3.2/§3.3 明确 API 层聚合，不入库）:
- 大纲列表/详情: point_count / plot_points（含 arc_name）
- 情节点列表/详情: arc_name
- 弧线列表/详情: point_count / points（含 outline_name）

错误映射（spec §3.5 异常映射表）:
- 无效 UUID / 资源不存在（Service 返回 None）→ 404
- OutlineServiceError 子类（同名大纲/弧线、弧线跨项目）→ 422（消息即 detail）
- OutlineNotFoundError / PlotPointNotFoundError / StoryArcNotFoundError /
  ProjectNotFoundError → 404
- OutlineGenerationError → 500「大纲生成失败: LLM 输出无法解析，请重试」
- LLMRequestError → 500「LLM 调用失败，请稍后重试」

依据: specs/f11-outline-service/spec.md §3/§5/§7。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_outline_service
from inkflow.domain.models.outline import (
    OutlineGenerateRequest,
    OutlineUpdate,
    PlotPoint,
    PlotPointUpdate,
    StoryArcUpdate,
    _validate_description,
    _validate_name,
    _validate_type,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.outline_errors import (
    OutlineGenerationError,
    OutlineNotFoundError,
    OutlineServiceError,
    PlotPointNotFoundError,
    ProjectNotFoundError,
    StoryArcNotFoundError,
)
from inkflow.domain.services.outline_service import OutlineService

router = APIRouter(prefix="/api/v1", tags=["大纲"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 F9/F10）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail=detail) from err


def _get_svc(db: AsyncSession) -> OutlineService:
    """获取 OutlineService 实例（方便 mock）。"""
    return get_outline_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.5）。"""
    try:
        return await coro
    except OutlineServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except OutlineNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PlotPointNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except StoryArcNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except OutlineGenerationError as err:
        raise HTTPException(
            status_code=500, detail="大纲生成失败: LLM 输出无法解析，请重试"
        ) from err
    except LLMRequestError as err:
        raise HTTPException(status_code=500, detail="LLM 调用失败，请稍后重试") from err


async def _point_payload(svc: OutlineService, point: PlotPoint) -> dict[str, Any]:
    """情节点 JSON 载荷 — 聚合 arc_name（API 层聚合，不入库，spec §3.3）。"""
    item = point.model_dump(mode="json")
    if point.arc_id is not None:
        arc = await svc.get_arc(point.arc_id)
        item["arc_name"] = arc.name if arc is not None else None
    else:
        item["arc_name"] = None
    return item


async def _points_of_arc(
    svc: OutlineService, arc_id: uuid.UUID, project_id: uuid.UUID
) -> list[dict]:
    """聚合弧线的活动成员情节点（可能跨多个大纲）+ outline_name（spec §3.3）。"""
    items: list[dict[str, Any]] = []
    outlines, _ = await _run_service(svc.list_outlines(project_id))
    for o in outlines:
        for p in await _run_service(svc.list_points(o.id)):
            if p.arc_id == arc_id:
                item = p.model_dump(mode="json")
                item["outline_name"] = o.name
                items.append(item)
    # 稳定排序: (position ASC, created_at ASC)，同 spec §2.2
    items.sort(key=lambda it: (it["position"], it["created_at"]))
    return items


# ── AI 生成（先于 /outlines/{outline_id} 注册，避免路径歧义）──


@router.post("/outlines/generate")
async def generate_outline(
    request: OutlineGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """AI 生成大纲（spec §3.4）：save=true 落库，save=false 仅预览。"""
    svc = _get_svc(db)
    result = await _run_service(svc.generate(request))
    return result.model_dump(mode="json")


# ── Outline ──────────────────────────────────────────────────


class OutlineCreateBody(BaseModel):
    """创建大纲请求体 — project_id 取自路径参数，不在 body（spec §3.2）。"""

    name: str
    description: str = ""
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证大纲名：去空白后非空且不超过 50 字符."""
        return _validate_name(v, "大纲名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证大纲描述：不超过 5000 字符."""
        return _validate_description(v, "大纲描述", 5000)

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: int) -> int:
        """验证排序权重：非负."""
        if v < 0:
            raise ValueError("排序权重不能为负数")
        return v


@router.post("/projects/{project_id}/outlines", status_code=201)
async def create_outline(
    project_id: str,
    data: OutlineCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建大纲（spec §3.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    outline = await _run_service(
        svc.create_outline(pid, data.name, data.description, data.sort_order)
    )
    return outline.model_dump(mode="json")


@router.get("/projects/{project_id}/outlines")
async def list_outlines(
    project_id: str,
    search: str | None = Query(None),
    sort_by: str = Query("updated_at"),
    sort_desc: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内大纲列表（搜索 + 分页 + point_count 聚合，spec §3.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    outlines, total = await _run_service(
        svc.list_outlines(
            pid,
            search=search,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )
    )
    items = []
    for o in outlines:
        points = await _run_service(svc.list_points(o.id))
        item = o.model_dump(mode="json")
        item["point_count"] = len(points)
        items.append(item)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/outlines/{outline_id}")
async def get_outline(
    outline_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取大纲详情（含 plot_points 聚合 + arc_name，spec §3.2）。"""
    oid = _parse_id(outline_id, detail="大纲不存在")
    svc = _get_svc(db)
    outline = await _run_service(svc.get_outline(oid))
    if outline is None:
        raise HTTPException(status_code=404, detail="大纲不存在")
    points = await _run_service(svc.list_points(oid))
    payload = outline.model_dump(mode="json")
    payload["plot_points"] = [await _point_payload(svc, p) for p in points]
    return payload


@router.patch("/outlines/{outline_id}")
async def update_outline(
    outline_id: str,
    data: OutlineUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新大纲（OutlineUpdate 全可选，exclude_unset 语义）。"""
    oid = _parse_id(outline_id, detail="大纲不存在")
    svc = _get_svc(db)
    outline = await _run_service(svc.update_outline(oid, data))
    if outline is None:
        raise HTTPException(status_code=404, detail="大纲不存在")
    return outline.model_dump(mode="json")


@router.delete("/outlines/{outline_id}", status_code=204)
async def delete_outline(
    outline_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除大纲（默认软删除 + 级联软删情节点，?force=true 硬删除，spec §3.2）。"""
    oid = _parse_id(outline_id, detail="大纲不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_outline(oid, force=force))
    if not ok:
        raise HTTPException(status_code=404, detail="大纲不存在")


@router.post("/outlines/{outline_id}/restore")
async def restore_outline(
    outline_id: str,
    db: AsyncSession = Depends(get_db),
):
    """恢复软删除大纲（级联恢复情节点，spec §6.1）。"""
    oid = _parse_id(outline_id, detail="大纲不存在")
    svc = _get_svc(db)
    outline = await _run_service(svc.restore_outline(oid))
    if outline is None:
        raise HTTPException(status_code=404, detail="大纲不存在")
    return outline.model_dump(mode="json")


# ── PlotPoint ────────────────────────────────────────────────


class PlotPointCreateBody(BaseModel):
    """创建情节点请求体 — outline_id 取自路径参数，不在 body（spec §3.3）。"""

    name: str
    type: str = ""
    description: str = ""
    position: int | None = None  # None = 追加到大纲末尾（max+1）
    arc_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证情节点名：去空白后非空且不超过 100 字符."""
        return _validate_name(v, "情节点名", 100)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """验证情节点类型：去空白且不超过 20 字符（空串合法）."""
        return _validate_type(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证情节点描述：不超过 5000 字符."""
        return _validate_description(v, "情节点描述", 5000)

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: int | None) -> int | None:
        """验证排序位置：None（追加语义）合法；否则须非负."""
        if v is not None and v < 0:
            raise ValueError("排序位置不能为负数")
        return v


@router.post("/outlines/{outline_id}/plot-points", status_code=201)
async def create_point(
    outline_id: str,
    data: PlotPointCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建情节点（spec §3.3；大纲不存在 → 404，弧线跨项目 → 422）。"""
    oid = _parse_id(outline_id, detail="大纲不存在")
    svc = _get_svc(db)
    point = await _run_service(
        svc.create_point(
            oid,
            data.name,
            data.type,
            data.description,
            data.position,
            data.arc_id,
        )
    )
    return point.model_dump(mode="json")


@router.get("/outlines/{outline_id}/plot-points")
async def list_points(
    outline_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取大纲内情节点列表（position 升序 + arc_name 聚合，spec §3.3）。"""
    oid = _parse_id(outline_id, detail="大纲不存在")
    svc = _get_svc(db)
    points = await _run_service(svc.list_points(oid))
    items = [await _point_payload(svc, p) for p in points]
    return {"items": items, "total": len(items)}


@router.get("/plot-points/{point_id}")
async def get_point(
    point_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取情节点详情（含 arc_name 聚合）。"""
    pid = _parse_id(point_id, detail="情节点不存在")
    svc = _get_svc(db)
    point = await _run_service(svc.get_point(pid))
    if point is None:
        raise HTTPException(status_code=404, detail="情节点不存在")
    return await _point_payload(svc, point)


@router.patch("/plot-points/{point_id}")
async def update_point(
    point_id: str,
    data: PlotPointUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新情节点（arc_id \"\" 清除弧线归属，spec §3.3）。"""
    pid = _parse_id(point_id, detail="情节点不存在")
    svc = _get_svc(db)
    point = await _run_service(svc.update_point(pid, data))
    if point is None:
        raise HTTPException(status_code=404, detail="情节点不存在")
    return point.model_dump(mode="json")


@router.delete("/plot-points/{point_id}", status_code=204)
async def delete_point(
    point_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除情节点（默认软删除，?force=true 硬删除，spec §3.3）。"""
    pid = _parse_id(point_id, detail="情节点不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_point(pid, force=force))
    if not ok:
        raise HTTPException(status_code=404, detail="情节点不存在")


@router.post("/plot-points/{point_id}/restore")
async def restore_point(
    point_id: str,
    db: AsyncSession = Depends(get_db),
):
    """恢复软删除情节点。"""
    pid = _parse_id(point_id, detail="情节点不存在")
    svc = _get_svc(db)
    point = await _run_service(svc.restore_point(pid))
    if point is None:
        raise HTTPException(status_code=404, detail="情节点不存在")
    return point.model_dump(mode="json")


# ── StoryArc ─────────────────────────────────────────────────


class StoryArcCreateBody(BaseModel):
    """创建弧线请求体 — project_id 取自路径参数，不在 body（spec §3.3）。"""

    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证弧线名：去空白后非空且不超过 50 字符."""
        return _validate_name(v, "弧线名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证弧线说明：不超过 500 字符."""
        return _validate_description(v, "弧线说明", 500)


@router.post("/projects/{project_id}/story-arcs", status_code=201)
async def create_arc(
    project_id: str,
    data: StoryArcCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建故事弧线（spec §3.3；同名活动弧线 → 422）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    arc = await _run_service(svc.create_arc(pid, data.name, data.description))
    return arc.model_dump(mode="json")


@router.get("/projects/{project_id}/story-arcs")
async def list_arcs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取项目内弧线列表（name ASC + point_count 聚合，spec §3.3）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    arcs = await _run_service(svc.list_arcs(pid))
    outlines, _ = await _run_service(svc.list_outlines(pid))
    items = []
    for a in arcs:
        count = 0
        for o in outlines:
            for p in await _run_service(svc.list_points(o.id)):
                if p.arc_id == a.id:
                    count += 1
        item = a.model_dump(mode="json")
        item["point_count"] = count
        items.append(item)
    return {"items": items, "total": len(items)}


@router.get("/story-arcs/{arc_id}")
async def get_arc(
    arc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取弧线详情（含成员情节点 points 聚合 + outline_name，spec §3.3）。"""
    aid = _parse_id(arc_id, detail="弧线不存在")
    svc = _get_svc(db)
    arc = await _run_service(svc.get_arc(aid))
    if arc is None:
        raise HTTPException(status_code=404, detail="弧线不存在")
    payload = arc.model_dump(mode="json")
    payload["points"] = await _points_of_arc(svc, arc.id, arc.project_id)
    return payload


@router.patch("/story-arcs/{arc_id}")
async def update_arc(
    arc_id: str,
    data: StoryArcUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新弧线（改名撞同名 → 422）。"""
    aid = _parse_id(arc_id, detail="弧线不存在")
    svc = _get_svc(db)
    arc = await _run_service(svc.update_arc(aid, data))
    if arc is None:
        raise HTTPException(status_code=404, detail="弧线不存在")
    return arc.model_dump(mode="json")


@router.delete("/story-arcs/{arc_id}", status_code=204)
async def delete_arc(
    arc_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除弧线（成员情节点 arc_id 置 NULL，情节点保留，spec §6.2）。"""
    aid = _parse_id(arc_id, detail="弧线不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_arc(aid, force=force))
    if not ok:
        raise HTTPException(status_code=404, detail="弧线不存在")


@router.post("/story-arcs/{arc_id}/restore")
async def restore_arc(
    arc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """恢复软删除弧线（不恢复成员关联，同 F9 分组语义）。"""
    aid = _parse_id(arc_id, detail="弧线不存在")
    svc = _get_svc(db)
    arc = await _run_service(svc.restore_arc(aid))
    if arc is None:
        raise HTTPException(status_code=404, detail="弧线不存在")
    return arc.model_dump(mode="json")
