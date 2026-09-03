"""F51 设定库更新工具——chat agent 三更新工具（update_character / update_world_setting /
update_outline），输出统一 JSON 信封.

镜像 #748 setting_write_tools 形态：
- 动态 deps 构建（不进静态 TOOL_REGISTRY）
- 成功: {"ok": True, "<entity>_id": "<id>", "name": "<name>"}
- 失败: {"ok": False, "error": "<异常消息>"}（工具内部捕获一切 Exception 不抛出）
- 成功/失败均落审计（audit_service.record，actor="agent:chat"）；审计自身异常静默
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
from inkflow.domain.models.character import CharacterUpdate
from inkflow.domain.models.outline import OutlineUpdate
from inkflow.domain.models.world import WorldUpdate
from inkflow.infrastructure.agent.tools import _tool_db_lock as _tool_db_lock_mod
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.logging import instrument

T = TypeVar("T")


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _coerce_id(value: object) -> object:
    """尽力规范化实体 id：可解析为 UUID 则转 UUID（服务层再转 int），否则原样透传。

    #766 RED 契约：测试直传非 UUID 字符串（如 "char-1"）须成功 → 不强制校验；
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


class UpdateCharacterParams(BaseModel):
    """update_character 工具参数（部分更新，未传字段保持不变）。"""

    character_id: uuid.UUID | str
    name: str | None = None
    personality: str | None = None
    background: str | None = None
    goals: str | None = None
    group_ids: list[uuid.UUID | str] | None = None


class UpdateWorldSettingParams(BaseModel):
    """update_world_setting 工具参数（部分更新）。"""

    setting_id: uuid.UUID | str
    name: str | None = None
    category: str | None = None
    content: str | None = None
    parent_id: uuid.UUID | str | None = None


class UpdateOutlineParams(BaseModel):
    """update_outline 工具参数（部分更新）。"""

    outline_id: uuid.UUID | str
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    level: str | None = None
    parent_id: uuid.UUID | str | None = None
    chapter_id: uuid.UUID | str | None = None


# ─── 工具 spec 静态常量（func 动态构建，镜像 setting_write_tools） ───


UPDATE_CHARACTER_SPEC = ToolSpec(
    name="update_character",
    description="更新项目内角色设置（部分更新，未传字段保持不变）",
    input_schema=UpdateCharacterParams.model_json_schema(),
    group="writing",
)

UPDATE_WORLD_SETTING_SPEC = ToolSpec(
    name="update_world_setting",
    description="更新项目内世界观设定条目（部分更新）",
    input_schema=UpdateWorldSettingParams.model_json_schema(),
    group="writing",
)

UPDATE_OUTLINE_SPEC = ToolSpec(
    name="update_outline",
    description="更新项目内大纲条目（部分更新）",
    input_schema=UpdateOutlineParams.model_json_schema(),
    group="writing",
)


@dataclass
class SettingUpdateToolDeps:
    """设定库更新工具工厂依赖——service 实例注入（鸭子类型，镜像 SettingWriteToolDeps）。

    expected_project_id: #766 绑定项目——每次 run 由装配层注入请求真实值；工具总是
    使用绑定值（LLM 无法编造全量 UUID 落孤儿数据），未注入时回退 caller 传入值
    （MCP/writer 兼容）。
    """

    character_service: object  # 有 update_character(character_id, CharacterUpdate) -> Character
    world_service: object  # 有 update_setting(setting_id, WorldUpdate) -> WorldSetting(.id)
    outline_service: object  # 有 update_outline(outline_id, OutlineUpdate) -> Outline(.id)
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    expected_project_id: uuid.UUID | None = None


def _bind_project_id(expected: uuid.UUID | None, project_id: object) -> uuid.UUID | None:
    """解析绑定项目 id：装配期 expected 优先，未注入回退 caller 传入值."""
    bound = expected if expected is not None else project_id
    if bound is None:
        return None
    return bound if isinstance(bound, uuid.UUID) else _coerce_uuid(bound)


def build_setting_update_tools(deps: SettingUpdateToolDeps) -> list[Tool]:
    """构建设定库更新工具（顺序固定：update_character → update_world_setting → update_outline）。

    Args:
        deps: 工具依赖（character/world/outline + audit service 实例）。

    Returns:
        三个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """

    @instrument(caller_type="tool")
    async def _update_character(
        project_id: uuid.UUID | str | None = None,
        character_id: uuid.UUID | str = "",
        name: str | None = None,
        personality: str | None = None,
        background: str | None = None,
        goals: str | None = None,
        group_ids: list[uuid.UUID | str] | None = None,
    ) -> str:
        async with _tool_db_lock_mod._tool_db_lock:
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if name is not None:
                    update_fields["name"] = name
                if personality is not None:
                    update_fields["personality"] = personality
                if background is not None:
                    update_fields["background"] = background
                if goals is not None:
                    update_fields["goals"] = goals
                if group_ids is not None:
                    update_fields["group_ids"] = group_ids
                character = _require_found(
                    await deps.character_service.update_character(  # type: ignore[attr-defined]  # 鸭子类型：character_service 按契约提供 update_character
                        _coerce_id(character_id),
                        CharacterUpdate(**update_fields),
                    ),
                    "角色不存在",
                )
                # 成功审计；审计自身异常静默，不影响主返回
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_character_updated",
                        summary=f"角色更新 {name or ''}",
                        degraded=True,
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "character_id": str(character.id),
                        "name": character.name or name or "",
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                # 失败亦落审计；审计自身异常静默
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_character_update_failed",
                        summary=f"角色更新失败 {name or ''}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _update_world_setting(
        project_id: uuid.UUID | str | None = None,
        setting_id: uuid.UUID | str = "",
        name: str | None = None,
        category: str | None = None,
        content: str | None = None,
        parent_id: uuid.UUID | str | None = None,
    ) -> str:
        async with _tool_db_lock_mod._tool_db_lock:
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if name is not None:
                    update_fields["name"] = name
                if category is not None:
                    update_fields["category"] = category
                if content is not None:
                    update_fields["content"] = content
                if parent_id is not None:
                    update_fields["parent_id"] = parent_id
                setting = _require_found(
                    await deps.world_service.update_setting(  # type: ignore[attr-defined]  # 鸭子类型：world_service 按契约提供 update_setting
                        _coerce_id(setting_id),
                        WorldUpdate(**update_fields),
                    ),
                    "设定条目不存在",
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_world_setting_updated",
                        summary=f"世界观更新 {name or ''}",
                        degraded=True,
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "setting_id": str(setting.id),
                        "name": setting.name or name or "",
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_world_setting_update_failed",
                        summary=f"世界观更新失败 {name or ''}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _update_outline(
        project_id: uuid.UUID | str | None = None,
        outline_id: uuid.UUID | str = "",
        name: str | None = None,
        description: str | None = None,
        sort_order: int | None = None,
        level: str | None = None,
        parent_id: uuid.UUID | str | None = None,
        chapter_id: uuid.UUID | str | None = None,
    ) -> str:
        async with _tool_db_lock_mod._tool_db_lock:
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if name is not None:
                    update_fields["name"] = name
                if description is not None:
                    update_fields["description"] = description
                if sort_order is not None:
                    update_fields["sort_order"] = sort_order
                if level is not None:
                    update_fields["level"] = level
                if parent_id is not None:
                    update_fields["parent_id"] = parent_id
                if chapter_id is not None:
                    update_fields["chapter_id"] = chapter_id
                outline = _require_found(
                    await deps.outline_service.update_outline(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 update_outline
                        _coerce_id(outline_id),
                        OutlineUpdate(**update_fields),
                    ),
                    "大纲条目不存在",
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_outline_updated",
                        summary=f"大纲更新 {name or ''}",
                        degraded=True,
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "outline_id": str(outline.id),
                        "name": outline.name or name or "",
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="update_outline_update_failed",
                        summary=f"大纲更新失败 {name or ''}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return [
        Tool(spec=UPDATE_CHARACTER_SPEC, func=_update_character),
        Tool(spec=UPDATE_WORLD_SETTING_SPEC, func=_update_world_setting),
        Tool(spec=UPDATE_OUTLINE_SPEC, func=_update_outline),
    ]
