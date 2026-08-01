"""F12 时间线管理 REST API — 8 个端点：事件 CRUD + 双线总览 + 一致性检查。

端点风格沿用 F2/F9/F10/F11（spec §3.1）：创建/列表/双线总览/一致性检查
嵌套项目路径（/projects/{project_id}/timeline...），详情/更新/删除扁平
（/timeline/events/{event_id}...）。`/timeline`、`/timeline/events`、
`/timeline/check` 均为静态路径段（无动态段冲突），无需注册顺序注意。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 TimelineService —— 单元测试通过
`@patch("inkflow.api.routers.timeline.get_timeline_service")` 来
mock 服务层（同 F9/F10/F11 模式）。

错误映射（spec §3.4 异常映射表）:
- 无效 UUID / 资源不存在（Service 返回 None）→ 404
- TimelineServiceError（配置错误等业务校验）→ 422（消息即 detail）
- TimelineNotFoundError / ProjectNotFoundError → 404
- 无 LLM 相关错误（F12 一致性检查为确定性算法，无 LLM）

依据: specs/f12-timeline-service/spec.md §3/§5/§7。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_timeline_service
from inkflow.domain.models.timeline import (
    TimelineEventUpdate,
    _validate_description,
    _validate_short_text,
    _validate_time_value,
    _validate_title,
)
from inkflow.domain.ports.timeline_errors import (
    ProjectNotFoundError,
    TimelineNotFoundError,
    TimelineServiceError,
)
from inkflow.domain.services.timeline_service import TimelineService

router = APIRouter(prefix="/api/v1", tags=["时间线"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 F9/F10/F11）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError):
            raise HTTPException(status_code=404, detail=detail)


def _get_svc(db: AsyncSession) -> TimelineService:
    """获取 TimelineService 实例（方便 mock）。"""
    return get_timeline_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.4）。"""
    try:
        return await coro
    except TimelineServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except TimelineNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class TimelineEventCreateBody(BaseModel):
    """创建时间线事件请求体 — project_id 取自路径参数，不在 body（spec §3.2）。"""

    title: str
    description: str = ""
    time_value: float | None = None  # None = 时间未知
    time_unit: str = ""
    time_display: str = ""
    narrative_position: int | None = None  # None = 追加到叙事末尾（max+1）
    timeline_flag: str = ""

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """验证事件标题：去空白后非空且不超过 100 字符."""
        return _validate_title(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证事件描述：不超过 5000 字符."""
        return _validate_description(v)

    @field_validator("time_value")
    @classmethod
    def validate_time_value(cls, v: float | None) -> float | None:
        """验证世界内时间：None 合法；否则须有限且 |v| ≤ 1e12."""
        return _validate_time_value(v)

    @field_validator("time_unit")
    @classmethod
    def validate_time_unit(cls, v: str) -> str:
        """验证时间单位：去空白且不超过 20 字符（空串合法）."""
        return _validate_short_text(v, "时间单位", 20)

    @field_validator("time_display")
    @classmethod
    def validate_time_display(cls, v: str) -> str:
        """验证时间显示文本：去空白且不超过 100 字符（空串合法）."""
        return _validate_short_text(v, "时间显示文本", 100)

    @field_validator("narrative_position")
    @classmethod
    def validate_narrative_position(cls, v: int | None) -> int | None:
        """验证叙事位置：None（追加语义）合法；否则须非负."""
        if v is not None and v < 0:
            raise ValueError("叙事位置不能为负数")
        return v

    @field_validator("timeline_flag")
    @classmethod
    def validate_timeline_flag(cls, v: str) -> str:
        """验证时间线标记：去空白且不超过 20 字符（空串合法）."""
        return _validate_short_text(v, "时间线标记", 20)


# ── 事件 CRUD（嵌套项目路径）──────────────────────────────────


@router.post("/projects/{project_id}/timeline/events", status_code=201)
async def create_timeline_event(
    project_id: str,
    data: TimelineEventCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建时间线事件（spec §3.2；narrative_position 缺省 = 叙事末尾追加）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    event = await _run_service(
        svc.create_event(
            pid,
            data.title,
            description=data.description,
            time_value=data.time_value,
            time_unit=data.time_unit,
            time_display=data.time_display,
            narrative_position=data.narrative_position,
            timeline_flag=data.timeline_flag,
        )
    )
    return event.model_dump(mode="json")


@router.get("/projects/{project_id}/timeline/events")
async def list_timeline_events(
    project_id: str,
    search: str | None = Query(None),
    sort_by: str = Query("narrative_position"),
    sort_desc: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内事件列表（搜索 + 排序 + 分页，spec §6.3）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    items, total = await _run_service(
        svc.list_events(
            pid,
            search=search,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )
    )
    return {
        "items": [e.model_dump(mode="json") for e in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/projects/{project_id}/timeline")
async def get_timeline_view(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """双线总览（事件时间线 + 叙事时间线两种投影，spec §3.3/§5.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    view = await _run_service(svc.get_timeline_view(pid))
    if view is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return view.model_dump(mode="json")


@router.get("/projects/{project_id}/timeline/check")
async def check_timeline_consistency(
    project_id: str,
    include_flashbacks: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """时间线一致性检查（确定性算法，spec §3.3/§5.3）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    report = await _run_service(svc.check_consistency(pid, include_flashbacks=include_flashbacks))
    if report is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return report.model_dump(mode="json")


# ── 事件详情/更新/删除/恢复（扁平路径）──────────────────────────


@router.get("/timeline/events/{event_id}")
async def get_timeline_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取事件详情（spec §3.1）。"""
    eid = _parse_id(event_id, detail="事件不存在")
    svc = _get_svc(db)
    event = await _run_service(svc.get_event(eid))
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    return event.model_dump(mode="json")


@router.patch("/timeline/events/{event_id}")
async def update_timeline_event(
    event_id: str,
    data: TimelineEventUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新事件（TimelineEventUpdate 全可选，exclude_unset 语义）。"""
    eid = _parse_id(event_id, detail="事件不存在")
    svc = _get_svc(db)
    event = await _run_service(svc.update_event(eid, data))
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    return event.model_dump(mode="json")


@router.delete("/timeline/events/{event_id}", status_code=204)
async def delete_timeline_event(
    event_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除事件（默认软删除，?force=true 硬删除，spec §3.1/§7）。"""
    eid = _parse_id(event_id, detail="事件不存在")
    svc = _get_svc(db)
    if force:
        ok = await _run_service(svc.hard_delete_event(eid))
    else:
        ok = await _run_service(svc.soft_delete_event(eid))
    if not ok:
        raise HTTPException(status_code=404, detail="事件不存在")


@router.post("/timeline/events/{event_id}/restore")
async def restore_timeline_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """恢复软删除事件（重复操作无毒，同 F1，spec §3.1/§7）。"""
    eid = _parse_id(event_id, detail="事件不存在")
    svc = _get_svc(db)
    event = await _run_service(svc.restore_event(eid))
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    return event.model_dump(mode="json")
