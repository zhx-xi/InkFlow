"""#766 阶段② 删除工具——7 工具（delete_character / delete_world_setting / delete_outline /
delete_map / delete_timeline_event / delete_foreshadowing / memory_remove），统一 JSON 信封.

镜像 setting_write_tools.py 形态：
- 动态 deps 构建（不进静态 TOOL_REGISTRY，由装配守卫按 per-conversation 授权挂载）
- 成功: {"ok": True, "<entity>_id": "<id>"}；失败: {"ok": False, "error": "<异常消息>"}
  （工具内部捕获一切 Exception 不抛出）
- service 返回 False（记录不存在）→ {"ok": False, "error": "记录不存在"}（防假成功）
- 成功/失败均落审计（audit_service.record，actor="agent:chat"）；审计自身异常静默
- project_id 不出现在 schema（用于审计绑定），func 保留可选 shim（deepagents 只传
  schema 内参数，shim 兜底兼容 MCP/writer 直接调用）
- 删除授权（deps.auth，ToolAuth）：ask_once → 每次 func 内部先 interrupt（HITL），
  approved=True 执行本次删除、False 返回「用户拒绝删除」且不执行；auto → 直接执行
  不 interrupt（manual 不注册，见 test_delete_assembly.py 装配守卫契约）。
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langgraph.types import interrupt
from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolAuth, ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import Tool


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# ─── 参数模型（用于生成 ToolSpec.input_schema；project_id 由装配期绑定，不在 schema） ───


class DeleteCharacterParams(BaseModel):
    """delete_character 工具参数。"""

    character_id: uuid.UUID


class DeleteWorldSettingParams(BaseModel):
    """delete_world_setting 工具参数。"""

    setting_id: uuid.UUID


class DeleteOutlineParams(BaseModel):
    """delete_outline 工具参数。"""

    outline_id: uuid.UUID


class DeleteMapParams(BaseModel):
    """delete_map 工具参数。"""

    map_id: uuid.UUID


class DeleteTimelineEventParams(BaseModel):
    """delete_timeline_event 工具参数。"""

    event_id: uuid.UUID


class DeleteForeshadowingParams(BaseModel):
    """delete_foreshadowing 工具参数。"""

    foreshadowing_id: uuid.UUID


class MemoryRemoveParams(BaseModel):
    """memory_remove 工具参数。"""

    preference_id: uuid.UUID


# ─── 工具 spec 静态常量（func 动态构建，镜像 setting_write_tools） ───


DELETE_CHARACTER_SPEC = ToolSpec(
    name="delete_character",
    description="删除项目内角色设定（按会话删除授权执行，ask_once 需用户确认）",
    input_schema=DeleteCharacterParams.model_json_schema(),
    group="writing",
)

DELETE_WORLD_SETTING_SPEC = ToolSpec(
    name="delete_world_setting",
    description="删除项目内世界观设定条目（按会话删除授权执行，ask_once 需用户确认）",
    input_schema=DeleteWorldSettingParams.model_json_schema(),
    group="writing",
)

DELETE_OUTLINE_SPEC = ToolSpec(
    name="delete_outline",
    description="删除项目内大纲条目（按会话删除授权执行，ask_once 需用户确认）",
    input_schema=DeleteOutlineParams.model_json_schema(),
    group="writing",
)

DELETE_MAP_SPEC = ToolSpec(
    name="delete_map",
    description="删除项目内地图（含关联 pin 清理，按会话删除授权执行）",
    input_schema=DeleteMapParams.model_json_schema(),
    group="writing",
)

DELETE_TIMELINE_EVENT_SPEC = ToolSpec(
    name="delete_timeline_event",
    description="删除项目内时间线事件（按会话删除授权执行，ask_once 需用户确认）",
    input_schema=DeleteTimelineEventParams.model_json_schema(),
    group="writing",
)

DELETE_FORESHADOWING_SPEC = ToolSpec(
    name="delete_foreshadowing",
    description="删除项目内伏笔（按会话删除授权执行，ask_once 需用户确认）",
    input_schema=DeleteForeshadowingParams.model_json_schema(),
    group="writing",
)

MEMORY_REMOVE_SPEC = ToolSpec(
    name="memory_remove",
    description="删除项目内记忆偏好（按会话删除授权执行，ask_once 需用户确认）",
    input_schema=MemoryRemoveParams.model_json_schema(),
    group="writing",
)


@dataclass
class DeleteToolDeps:
    """删除工具工厂依赖——service 实例注入（鸭子类型，镜像 SettingWriteToolDeps）。

    auth: per-conversation 删除授权状态（manual 不注册由装配守卫处理；ask_once 每次
    interrupt 确认；auto 直接执行）。expected_project_id: #766 绑定项目——仅供审计
    绑定，不出现在 schema；删除服务方法只按实体 id 删除（源码核实 2026-08-30）。
    """

    character_service: object  # 有 delete_character(character_id) -> bool
    world_service: object  # 有 delete_setting(setting_id) -> bool
    outline_service: object  # 有 delete_outline(outline_id) -> bool
    map_service: object  # 有 delete_map(map_id) -> bool
    timeline_service: object  # 有 delete_event(event_id) -> bool
    foreshadowing_service: object  # 有 delete(foreshadowing_id) -> bool
    memory_service: object  # 有 remove_preference(preference_id) -> ProjectPreference
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    auth: ToolAuth
    expected_project_id: uuid.UUID | None = None


# (工具名, deps 服务字段, service 方法名, 实体 id 参数名, 实体中文名, id 是否字符串型, spec)
_DELETE_TOOL_TABLE: list[tuple[str, str, str, str, str, bool, ToolSpec]] = [
    (
        "delete_character",
        "character_service",
        "delete_character",
        "character_id",
        "角色",
        False,
        DELETE_CHARACTER_SPEC,
    ),
    (
        "delete_world_setting",
        "world_service",
        "delete_setting",
        "setting_id",
        "世界观设定",
        False,
        DELETE_WORLD_SETTING_SPEC,
    ),
    (
        "delete_outline",
        "outline_service",
        "delete_outline",
        "outline_id",
        "大纲",
        False,
        DELETE_OUTLINE_SPEC,
    ),
    ("delete_map", "map_service", "delete_map", "map_id", "地图", False, DELETE_MAP_SPEC),
    (
        "delete_timeline_event",
        "timeline_service",
        "delete_event",
        "event_id",
        "时间线事件",
        False,
        DELETE_TIMELINE_EVENT_SPEC,
    ),
    (
        "delete_foreshadowing",
        "foreshadowing_service",
        "delete",
        "foreshadowing_id",
        "伏笔",
        False,
        DELETE_FORESHADOWING_SPEC,
    ),
    (
        "memory_remove",
        "memory_service",
        "remove_preference",
        "preference_id",
        "记忆偏好",
        True,
        MEMORY_REMOVE_SPEC,
    ),
]


def build_delete_tools(deps: DeleteToolDeps) -> list[Tool]:
    """构建删除工具（顺序固定：delete_character → memory_remove）。

    Args:
        deps: 工具依赖（7 删除 service + audit + per-conversation 授权状态 + 绑定项目）。

    Returns:
        七个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """

    def _build_func(
        tool_name: str,
        svc_field: str,
        method_name: str,
        entity_key: str,
        entity_label: str,
        str_id: bool,
    ) -> Callable[..., Awaitable[str]]:
        async def _delete(
            project_id: uuid.UUID | str | None = None,
            **kwargs: object,
        ) -> str:
            # #766: 绑定到装配期项目（LLM 无需也不能自报 id，审计绑定用）
            bound_project_id = (
                deps.expected_project_id if deps.expected_project_id is not None else project_id
            )
            _project_id: uuid.UUID | None = None
            entity_id = kwargs.get(entity_key)
            try:
                if bound_project_id is not None:
                    _project_id = (
                        bound_project_id
                        if isinstance(bound_project_id, uuid.UUID)
                        else _coerce_uuid(bound_project_id)
                    )
                # HITL（ask_once）：每次调用都走 interrupt，批准仅放行本次（不升级 auto）
                if deps.auth.delete_permission == "ask_once":
                    decision = interrupt(
                        {
                            "tool": tool_name,
                            "entity_id": entity_id,
                            "entity_name": entity_label,
                        }
                    )
                    if not decision.get("approved", False):
                        # 拒绝亦落审计（失败语义）；审计自身异常静默
                        with contextlib.suppress(Exception):
                            await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                                actor="agent:chat",
                                project_id=_project_id,
                                severity_summary=f"{tool_name}_rejected",
                                summary=f"{entity_label}删除被用户拒绝",
                                degraded=True,
                            )
                        return json.dumps(
                            {"ok": False, "error": "用户拒绝删除"}, ensure_ascii=False
                        )
                # 实体 id：memory 走字符串型，其余规范化为 UUID（非法格式回退原值由
                # service 校验/报错——测试契约要求 service 异常消息透传）
                entity_value: object
                if str_id:
                    entity_value = str(entity_id)
                elif isinstance(entity_id, str):
                    try:
                        entity_value = _coerce_uuid(entity_id)
                    except ValueError:
                        entity_value = entity_id
                else:
                    entity_value = entity_id
                service = getattr(deps, svc_field)  # 鸭子类型：deps 按契约提供各删除 service 字段
                method = getattr(service, method_name)  # 鸭子类型：service 按契约提供删除方法
                # 鸭子类型：删除方法按契约返回 bool（memory 返回实体，False 兜底）
                result: bool = await method(entity_value)
                if result is False:
                    return json.dumps(
                        {"ok": False, "error": "记录不存在"}, ensure_ascii=False
                    )
                # 成功审计；审计自身异常静默，不影响主返回
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary=f"{tool_name}_deleted",
                        summary=f"{entity_label}删除 {entity_id}",
                        degraded=True,
                    )
                return json.dumps(
                    {"ok": True, entity_key: str(entity_id)}, ensure_ascii=False
                )
            except Exception as exc:
                # 失败亦落审计；审计自身异常静默
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary=f"{tool_name}_delete_failed",
                        summary=f"{entity_label}删除失败: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

        return _delete

    return [
        Tool(spec=row[6], func=_build_func(*row[:6])) for row in _DELETE_TOOL_TABLE
    ]
