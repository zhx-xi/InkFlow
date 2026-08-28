"""#748 设定库写入工具——chat agent 三写工具（create_character / create_world_setting /
create_outline），输出统一 JSON 信封.

背景（#748 实锤）：chat agent 只注册 [readers, save_draft]，AI 调用设定库写入工具时
工具不存在 → 卡 running。本模块补齐写工具，形态镜像 F27 save_draft_tool.py：
- 动态 deps 构建（不进静态 TOOL_REGISTRY）
- 成功: {"ok": True, "<entity>_id": "<id>", "name": "<name>"}
- 失败: {"ok": False, "error": "<异常消息>"}（工具内部捕获一切 Exception 不抛出）
- 约束①：成功/失败均落审计（audit_service.record，actor="agent:chat"）；审计调用
  自身异常静默（不影响主返回）
- project_id 不出现在 schema（LLM 不自报项目），装配期 deps.expected_project_id
  绑定；func 保留可选 shim project_id（dict args_schema 下 deepagents 只传 schema
  内参数，shim 兜底兼容 MCP/writer 直接调用）。
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import Tool


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# ─── 参数模型（用于生成 ToolSpec.input_schema；project_id 由装配期绑定，不在 schema） ───


class CreateCharacterParams(BaseModel):
    """create_character 工具参数。"""

    name: str
    personality: str = ""
    background: str = ""
    goals: str = ""
    group_ids: list[uuid.UUID | str] | None = None


class CreateWorldSettingParams(BaseModel):
    """create_world_setting 工具参数。"""

    name: str
    category: str = ""
    content: str = ""
    parent_id: uuid.UUID | str | None = None


class CreateOutlineParams(BaseModel):
    """create_outline 工具参数。"""

    name: str
    description: str = ""
    sort_order: int = 0
    level: str = "chapter"
    parent_id: uuid.UUID | str | None = None


# ─── 工具 spec 静态常量（func 动态构建，镜像 save_draft_tool） ───


CREATE_CHARACTER_SPEC = ToolSpec(
    name="create_character",
    description="创建项目内角色设定并写入设定库，返回新角色 id；同名活动角色会失败。",
    input_schema=CreateCharacterParams.model_json_schema(),
    group="writing",
)

CREATE_WORLD_SETTING_SPEC = ToolSpec(
    name="create_world_setting",
    description="创建项目内世界观设定条目并写入设定库，返回新条目 id；同级同名会失败。",
    input_schema=CreateWorldSettingParams.model_json_schema(),
    group="writing",
)

CREATE_OUTLINE_SPEC = ToolSpec(
    name="create_outline",
    description="创建项目内大纲条目并写入设定库，返回新大纲 id；同名活动大纲会失败。",
    input_schema=CreateOutlineParams.model_json_schema(),
    group="writing",
)


@dataclass
class SettingWriteToolDeps:
    """设定库写工具工厂依赖——service 实例注入（鸭子类型，镜像 SaveDraftToolDeps）。

    expected_project_id: #748 绑定项目——每次 run 由装配层注入请求真实值；工具总是
    使用绑定值（LLM 无法编造全量 UUID 落孤儿数据），未注入时回退 caller 传入值
    （MCP/writer 兼容）。
    """

    character_service: object  # 有 create_character(project_id, name, personality="",
    #   background="", goals="", group_ids=None, extra=None) -> Character(.id)
    world_service: object  # 有 create_setting(project_id, name, category="", content="",
    #   parent_id=None) -> WorldSetting(.id)
    outline_service: object  # 有 create_outline(project_id, name, description="",
    #   sort_order=0, level="chapter", parent_id=None) -> Outline(.id)
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    expected_project_id: uuid.UUID | None = None


def build_setting_write_tools(deps: SettingWriteToolDeps) -> list[Tool]:
    """构建设定库写入工具（顺序固定：create_character → create_world_setting → create_outline）。

    Args:
        deps: 工具依赖（character/world/outline + audit service 实例）。

    Returns:
        三个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """
    async def _create_character(
        project_id: uuid.UUID | str | None = None,
        name: str = "",
        personality: str = "",
        background: str = "",
        goals: str = "",
        group_ids: list[uuid.UUID | str] | None = None,
    ) -> str:
        # #748: 绑定到装配期项目（LLM 无需也不能自报 id，杜绝编造全量 UUID 孤儿数据）
        bound_project_id = (
            deps.expected_project_id if deps.expected_project_id is not None else project_id
        )
        _project_id: uuid.UUID | None = None
        try:
            _project_id = (
                bound_project_id
                if isinstance(bound_project_id, uuid.UUID)
                else _coerce_uuid(bound_project_id)
            )
            group_ids_coerced = None
            if group_ids:
                group_ids_coerced = [_coerce_uuid(gid) for gid in group_ids]
            character = await deps.character_service.create_character(  # type: ignore[attr-defined]  # 鸭子类型：character_service 按契约提供 create_character
                project_id=_project_id,
                name=name,
                personality=personality,
                background=background,
                goals=goals,
                group_ids=group_ids_coerced or None,
                extra=None,
            )
            # 成功审计（约束①）；审计自身异常静默，不影响主返回
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="create_character_created",
                    summary=f"角色创建 {name}",
                    degraded=True,
                )
            return json.dumps(
                {
                    "ok": True,
                    "character_id": str(character.id),
                    "name": name,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            # 失败亦落审计（约束①）；审计自身异常静默
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="create_character_create_failed",
                    summary=f"角色创建失败 {name}: {exc}",
                    degraded=True,
                )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _create_world_setting(
        project_id: uuid.UUID | str | None = None,
        name: str = "",
        category: str = "",
        content: str = "",
        parent_id: uuid.UUID | str | None = None,
    ) -> str:
        bound_project_id = (
            deps.expected_project_id if deps.expected_project_id is not None else project_id
        )
        _project_id: uuid.UUID | None = None
        try:
            _project_id = (
                bound_project_id
                if isinstance(bound_project_id, uuid.UUID)
                else _coerce_uuid(bound_project_id)
            )
            parent_coerced = None
            if parent_id is not None:
                parent_coerced = _coerce_uuid(parent_id)
            setting = await deps.world_service.create_setting(  # type: ignore[attr-defined]  # 鸭子类型：world_service 按契约提供 create_setting
                project_id=_project_id,
                name=name,
                category=category,
                content=content,
                parent_id=parent_coerced or None,
            )
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="create_world_setting_created",
                    summary=f"世界观创建 {name}",
                    degraded=True,
                )
            return json.dumps(
                {
                    "ok": True,
                    "setting_id": str(setting.id),
                    "name": name,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="create_world_setting_create_failed",
                    summary=f"世界观创建失败 {name}: {exc}",
                    degraded=True,
                )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _create_outline(
        project_id: uuid.UUID | str | None = None,
        name: str = "",
        description: str = "",
        sort_order: int = 0,
        level: str = "chapter",
        parent_id: uuid.UUID | str | None = None,
    ) -> str:
        bound_project_id = (
            deps.expected_project_id if deps.expected_project_id is not None else project_id
        )
        _project_id: uuid.UUID | None = None
        try:
            _project_id = (
                bound_project_id
                if isinstance(bound_project_id, uuid.UUID)
                else _coerce_uuid(bound_project_id)
            )
            parent_coerced = None
            if parent_id is not None:
                parent_coerced = _coerce_uuid(parent_id)
            outline = await deps.outline_service.create_outline(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 create_outline
                project_id=_project_id,
                name=name,
                description=description,
                sort_order=sort_order,
                level=level,
                parent_id=parent_coerced or None,
            )
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="create_outline_created",
                    summary=f"大纲创建 {name}",
                    degraded=True,
                )
            return json.dumps(
                {
                    "ok": True,
                    "outline_id": str(outline.id),
                    "name": name,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="create_outline_create_failed",
                    summary=f"大纲创建失败 {name}: {exc}",
                    degraded=True,
                )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return [
        Tool(spec=CREATE_CHARACTER_SPEC, func=_create_character),
        Tool(spec=CREATE_WORLD_SETTING_SPEC, func=_create_world_setting),
        Tool(spec=CREATE_OUTLINE_SPEC, func=_create_outline),
    ]
