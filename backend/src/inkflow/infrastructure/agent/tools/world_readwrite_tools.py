"""F51 世界读+写工具——地图/时间线/伏笔 8 工具（list_maps / create_map / update_map /
list_timeline_events / create_timeline_event / update_timeline_event /
create_foreshadowing / update_foreshadowing），输出统一 JSON 信封.

镜像 #748 setting_write_tools 形态：
- 动态 deps 构建（不进静态 TOOL_REGISTRY）
- 读工具成功: {"ok": True, "data": <序列化结果>}；失败: {"ok": False, "error": "..."}
- 写工具成功: {"ok": True, "<entity>_id": "<id>", ...}；失败: {"ok": False, "error": "..."}
- 写类成功/失败均落审计（audit_service.record，actor="agent:chat"）；审计自身异常静默
- project_id 不出现在 schema；func 保留可选 shim project_id（deepagents 只传 schema
  内参数，shim 兜底兼容 MCP/writer 直接调用）
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.models.foreshadowing import ForeshadowingCreate, ForeshadowingUpdate
from inkflow.domain.models.map import WorldMapUpdate
from inkflow.domain.models.timeline import TimelineEventUpdate
from inkflow.infrastructure.agent.tools import _tool_db_lock as _tool_db_lock_mod
from inkflow.infrastructure.agent.tools.reader_tools import (
    Tool,
    _fail,
    _fetch_all_pages,
    _ok,
    _serialize_data,
)
from inkflow.logging import instrument

T = TypeVar("T")


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _coerce_id(value: object) -> object:
    """尽力规范化实体 id：可解析为 UUID 则转 UUID（服务层再转 int），否则原样透传。

    #766 RED 契约：测试直传非 UUID 字符串（如 "map-1"）须成功 → 不强制校验；
    真实调用（LLM 传 UUID 字符串）转 UUID 供服务层 _to_int_id 转换。
    """
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return value


def _require_found(value: T, message: str) -> T:
    """更新类 service 返回 None（实体不存在）→ 抛 ValueError 走 _fail 信封."""
    if value is None:
        raise ValueError(message)
    return value


# ─── 参数模型（用于生成 ToolSpec.input_schema；project_id 由装配期绑定，不在 schema） ───


class ListMapsParams(BaseModel):
    """list_maps 工具参数。"""

    root_location_id: uuid.UUID | str | None = None
    top_level_only: bool = False


class CreateMapParams(BaseModel):
    """create_map 工具参数。"""

    name: str
    description: str = ""
    root_location_id: uuid.UUID | str | None = None
    parent_map_id: uuid.UUID | str | None = None


class UpdateMapParams(BaseModel):
    """update_map 工具参数（部分更新）。"""

    map_id: uuid.UUID | str
    name: str | None = None
    description: str | None = None


class ListTimelineEventsParams(BaseModel):
    """list_timeline_events 工具参数。"""

    search: str | None = None
    sort_by: str = "narrative_position"


class CreateTimelineEventParams(BaseModel):
    """create_timeline_event 工具参数。"""

    title: str
    description: str = ""
    time_value: float | None = None
    time_unit: str = ""
    time_display: str = ""
    narrative_position: int | None = None
    timeline_flag: str = ""


class UpdateTimelineEventParams(BaseModel):
    """update_timeline_event 工具参数（部分更新）。"""

    event_id: uuid.UUID | str
    title: str | None = None
    description: str | None = None
    time_value: float | str | None = None
    narrative_position: int | None = None


class CreateForeshadowingParams(BaseModel):
    """create_foreshadowing 工具参数（创建即 open，不含 status/resolved_at）。"""

    title: str
    description: str | None = None
    priority: int | None = None
    location: str | None = None
    event_id: uuid.UUID | str | None = None


class UpdateForeshadowingParams(BaseModel):
    """update_foreshadowing 工具参数（部分更新；状态迁移走 resolve/reopen，DTO 无此字段）。"""

    foreshadowing_id: uuid.UUID | str
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    location: str | None = None
    event_id: uuid.UUID | str | None = None


# ─── 工具 spec 静态常量（func 动态构建，镜像 setting_write_tools） ───


LIST_MAPS_SPEC = ToolSpec(
    name="list_maps",
    description="列出项目内地图（可按根位置过滤/仅顶层）",
    input_schema=ListMapsParams.model_json_schema(),
    group="retrieval",
)

CREATE_MAP_SPEC = ToolSpec(
    name="create_map",
    description="创建项目内地图并写入设定库，返回新地图 id；同名活动地图会失败",
    input_schema=CreateMapParams.model_json_schema(),
    group="writing",
)

UPDATE_MAP_SPEC = ToolSpec(
    name="update_map",
    description="更新地图元数据（部分更新；不换图）",
    input_schema=UpdateMapParams.model_json_schema(),
    group="writing",
)

LIST_TIMELINE_EVENTS_SPEC = ToolSpec(
    name="list_timeline_events",
    description="列出项目内时间线事件（可按关键字搜索/排序）",
    input_schema=ListTimelineEventsParams.model_json_schema(),
    group="retrieval",
)

CREATE_TIMELINE_EVENT_SPEC = ToolSpec(
    name="create_timeline_event",
    description="创建时间线事件并写入设定库，返回新事件 id",
    input_schema=CreateTimelineEventParams.model_json_schema(),
    group="writing",
)

UPDATE_TIMELINE_EVENT_SPEC = ToolSpec(
    name="update_timeline_event",
    description="更新时间线事件（部分更新）",
    input_schema=UpdateTimelineEventParams.model_json_schema(),
    group="writing",
)

CREATE_FORESHADOWING_SPEC = ToolSpec(
    name="create_foreshadowing",
    description="创建伏笔并写入设定库，返回新伏笔 id；创建即 open",
    input_schema=CreateForeshadowingParams.model_json_schema(),
    group="writing",
)

UPDATE_FORESHADOWING_SPEC = ToolSpec(
    name="update_foreshadowing",
    description="更新伏笔（部分更新；不含状态迁移）",
    input_schema=UpdateForeshadowingParams.model_json_schema(),
    group="writing",
)


@dataclass
class WorldRwToolDeps:
    """世界读+写工具工厂依赖——service 实例注入（鸭子类型，镜像 SettingWriteToolDeps）。

    expected_project_id: #766 绑定项目——每次 run 由装配层注入请求真实值；工具总是
    使用绑定值（LLM 无法编造全量 UUID 落孤儿数据），未注入时回退 caller 传入值
    （MCP/writer 兼容）。
    """

    map_service: object  # 有 list_maps/create_map/update_map（MapService 形态）
    timeline_service: object  # 有 list_events/create_event/update_event（TimelineService 形态）
    foreshadowing_service: object  # 有 create/update（ForeshadowingService 形态）
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    expected_project_id: uuid.UUID | None = None


def _bind_project_id(expected: uuid.UUID | None, project_id: object) -> uuid.UUID | None:
    """解析绑定项目 id：装配期 expected 优先，未注入回退 caller 传入值."""
    bound = expected if expected is not None else project_id
    if bound is None:
        return None
    return bound if isinstance(bound, uuid.UUID) else _coerce_uuid(bound)


def build_world_rw_tools(deps: WorldRwToolDeps) -> list[Tool]:
    """构建世界读+写工具（顺序固定：地图 → 时间线 → 伏笔）。

    Args:
        deps: 工具依赖（map/timeline/foreshadowing + audit service 实例）。

    Returns:
        八个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """

    @instrument(caller_type="tool")
    async def _list_maps(
        project_id: uuid.UUID | str | None = None,
        root_location_id: uuid.UUID | str | None = None,
        top_level_only: bool = False,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                root = _coerce_uuid(root_location_id) if root_location_id is not None else None
                items = await _fetch_all_pages(
                    deps.map_service.list_maps,  # type: ignore[attr-defined]  # 鸭子类型：map_service 按契约提供 list_maps
                    _project_id,
                    root_location_id=root,
                    top_level_only=top_level_only,
                )
                return _ok(_serialize_data(items))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _create_map(
        project_id: uuid.UUID | str | None = None,
        name: str = "",
        description: str = "",
        root_location_id: uuid.UUID | str | None = None,
        parent_map_id: uuid.UUID | str | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                root = _coerce_uuid(root_location_id) if root_location_id is not None else None
                parent = _coerce_uuid(parent_map_id) if parent_map_id is not None else None
                m = await deps.map_service.create_map(  # type: ignore[attr-defined]  # 鸭子类型：map_service 按契约提供 create_map
                    project_id=_project_id,
                    name=name,
                    description=description,
                    root_location_id=root,
                    parent_map_id=parent,
                )
                # 成功审计；审计自身异常静默，不影响主返回
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="create_map_created",
                        summary=f"地图创建 {name}",
                        degraded=True,
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "map_id": str(m.id),
                        "name": m.name or name,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                # 失败亦落审计；审计自身异常静默
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="create_map_create_failed",
                        summary=f"地图创建失败 {name}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _update_map(
        project_id: uuid.UUID | str | None = None,
        map_id: uuid.UUID | str = "",
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if name is not None:
                    update_fields["name"] = name
                if description is not None:
                    update_fields["description"] = description
                _require_found(
                    await deps.map_service.update_map(  # type: ignore[attr-defined]  # 鸭子类型：map_service 按契约提供 update_map
                        _coerce_id(map_id),
                        WorldMapUpdate(**update_fields),
                    ),
                    "地图不存在",
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_map_updated",
                        summary=f"地图更新 {map_id}",
                        degraded=True,
                    )
                return json.dumps({"ok": True, "map_id": str(map_id)}, ensure_ascii=False)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_map_update_failed",
                        summary=f"地图更新失败 {map_id}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _list_timeline_events(
        project_id: uuid.UUID | str | None = None,
        search: str | None = None,
        sort_by: str = "narrative_position",
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                items = await _fetch_all_pages(
                    deps.timeline_service.list_events,  # type: ignore[attr-defined]  # 鸭子类型：timeline_service 按契约提供 list_events
                    _project_id,
                    search=search,
                    sort_by=sort_by,
                )
                return _ok(_serialize_data(items))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _create_timeline_event(
        project_id: uuid.UUID | str | None = None,
        title: str = "",
        description: str = "",
        time_value: float | None = None,
        time_unit: str = "",
        time_display: str = "",
        narrative_position: int | None = None,
        timeline_flag: str = "",
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                evt = await deps.timeline_service.create_event(  # type: ignore[attr-defined]  # 鸭子类型：timeline_service 按契约提供 create_event
                    project_id=_project_id,
                    title=title,
                    description=description,
                    time_value=time_value,
                    time_unit=time_unit,
                    time_display=time_display,
                    narrative_position=narrative_position,
                    timeline_flag=timeline_flag,
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="create_timeline_event_created",
                        summary=f"时间线事件创建 {title}",
                        degraded=True,
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "event_id": str(evt.id),
                        "title": evt.title or title,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="create_timeline_event_create_failed",
                        summary=f"时间线事件创建失败 {title}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _update_timeline_event(
        project_id: uuid.UUID | str | None = None,
        event_id: uuid.UUID | str = "",
        title: str | None = None,
        description: str | None = None,
        time_value: float | str | None = None,
        narrative_position: int | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if title is not None:
                    update_fields["title"] = title
                if description is not None:
                    update_fields["description"] = description
                if time_value is not None:
                    update_fields["time_value"] = time_value
                if narrative_position is not None:
                    update_fields["narrative_position"] = narrative_position
                _require_found(
                    await deps.timeline_service.update_event(  # type: ignore[attr-defined]  # 鸭子类型：timeline_service 按契约提供 update_event
                        _coerce_id(event_id),
                        TimelineEventUpdate(**update_fields),
                    ),
                    "时间线事件不存在",
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_timeline_event_updated",
                        summary=f"时间线事件更新 {event_id}",
                        degraded=True,
                    )
                return json.dumps({"ok": True, "event_id": str(event_id)}, ensure_ascii=False)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_timeline_event_update_failed",
                        summary=f"时间线事件更新失败 {event_id}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _create_foreshadowing(
        project_id: uuid.UUID | str | None = None,
        title: str = "",
        description: str | None = None,
        priority: int | None = None,
        location: str | None = None,
        event_id: uuid.UUID | str | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                create_fields: dict[str, Any] = {"project_id": _project_id, "title": title}
                if description is not None:
                    create_fields["description"] = description
                if priority is not None:
                    create_fields["priority"] = priority
                if location is not None:
                    create_fields["location"] = location
                if event_id is not None:
                    create_fields["event_id"] = event_id
                fsh = await deps.foreshadowing_service.create(  # type: ignore[attr-defined]  # 鸭子类型：foreshadowing_service 按契约提供 create
                    ForeshadowingCreate(**create_fields)
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="create_foreshadowing_created",
                        summary=f"伏笔创建 {title}",
                        degraded=True,
                    )
                return json.dumps(
                    {"ok": True, "foreshadowing_id": str(fsh.id)},
                    ensure_ascii=False,
                )
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="create_foreshadowing_create_failed",
                        summary=f"伏笔创建失败 {title}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _update_foreshadowing(
        project_id: uuid.UUID | str | None = None,
        foreshadowing_id: uuid.UUID | str = "",
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        location: str | None = None,
        event_id: uuid.UUID | str | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if title is not None:
                    update_fields["title"] = title
                if description is not None:
                    update_fields["description"] = description
                if priority is not None:
                    update_fields["priority"] = priority
                if location is not None:
                    update_fields["location"] = location
                if event_id is not None:
                    update_fields["event_id"] = event_id
                _require_found(
                    await deps.foreshadowing_service.update(  # type: ignore[attr-defined]  # 鸭子类型：foreshadowing_service 按契约提供 update
                        _coerce_id(foreshadowing_id),
                        ForeshadowingUpdate(**update_fields),
                    ),
                    "伏笔不存在",
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_foreshadowing_updated",
                        summary=f"伏笔更新 {foreshadowing_id}",
                        degraded=True,
                    )
                return json.dumps(
                    {"ok": True, "foreshadowing_id": str(foreshadowing_id)},
                    ensure_ascii=False,
                )
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_foreshadowing_update_failed",
                        summary=f"伏笔更新失败 {foreshadowing_id}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return [
        Tool(spec=LIST_MAPS_SPEC, func=_list_maps),
        Tool(spec=CREATE_MAP_SPEC, func=_create_map),
        Tool(spec=UPDATE_MAP_SPEC, func=_update_map),
        Tool(spec=LIST_TIMELINE_EVENTS_SPEC, func=_list_timeline_events),
        Tool(spec=CREATE_TIMELINE_EVENT_SPEC, func=_create_timeline_event),
        Tool(spec=UPDATE_TIMELINE_EVENT_SPEC, func=_update_timeline_event),
        Tool(spec=CREATE_FORESHADOWING_SPEC, func=_create_foreshadowing),
        Tool(spec=UPDATE_FORESHADOWING_SPEC, func=_update_foreshadowing),
    ]
