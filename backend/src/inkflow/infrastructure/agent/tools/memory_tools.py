"""F51 记忆工具——3 工具（memory_list / memory_add / memory_update），输出统一 JSON 信封.

镜像 #748 setting_write_tools 形态：
- 动态 deps 构建（不进静态 TOOL_REGISTRY）
- 读工具成功: {"ok": True, "data": <序列化结果>}；失败: {"ok": False, "error": "..."}
- 写工具成功: {"ok": True, "preference_id": "<id>"}；失败: {"ok": False, "error": "..."}
- 写类成功/失败均落审计（audit_service.record，actor="agent:chat"）；审计自身异常静默
- project_id 不出现在 schema；func 保留可选 shim project_id（deepagents 只传 schema
  内参数，shim 兜底兼容 MCP/writer 直接调用）
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.models.preference import PreferenceCategory
from inkflow.infrastructure.agent.tools import _tool_db_lock as _tool_db_lock_mod
from inkflow.infrastructure.agent.tools.reader_tools import (
    Tool,
    _fail,
    _ok,
    _serialize_data,
)
from inkflow.logging import instrument


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _coerce_category(value: object) -> object:
    """尽力规范化偏好分类：合法枚举字符串转 PreferenceCategory，否则原样透传.

    #766 RED 契约：测试直传 "style"（非枚举值）须成功 → 不合法值原样透传，
    由 service/repo 抛错走 _fail 信封；合法值（addressing/style_word/...）转枚举
    满足真实 memory_service 的类型契约。
    """
    if value is None or isinstance(value, PreferenceCategory):
        return value
    try:
        return PreferenceCategory(str(value))
    except ValueError:
        return value


# ─── 参数模型（用于生成 ToolSpec.input_schema；project_id 由装配期绑定，不在 schema） ───


class MemoryListParams(BaseModel):
    """memory_list 工具参数。"""

    category: str | None = None


class MemoryAddParams(BaseModel):
    """memory_add 工具参数（note 对应领域 value——偏好值文本）。"""

    category: str
    pattern: str
    note: str = ""


class MemoryUpdateParams(BaseModel):
    """memory_update 工具参数（部分更新；note 对应领域 value）。"""

    preference_id: str
    category: str | None = None
    pattern: str | None = None
    note: str | None = None


# ─── 工具 spec 静态常量（func 动态构建，镜像 setting_write_tools） ───


MEMORY_LIST_SPEC = ToolSpec(
    name="memory_list",
    description="列出项目内记忆偏好（可按分类过滤）",
    input_schema=MemoryListParams.model_json_schema(),
    group="retrieval",
)

MEMORY_ADD_SPEC = ToolSpec(
    name="memory_add",
    description="添加一条记忆偏好并写入记忆库，返回新偏好 id",
    input_schema=MemoryAddParams.model_json_schema(),
    group="writing",
)

MEMORY_UPDATE_SPEC = ToolSpec(
    name="memory_update",
    description="更新一条记忆偏好（部分更新）",
    input_schema=MemoryUpdateParams.model_json_schema(),
    group="writing",
)


@dataclass
class MemoryToolDeps:
    """记忆工具工厂依赖——service 实例注入（鸭子类型，镜像 SettingWriteToolDeps）。

    expected_project_id: #766 绑定项目——每次 run 由装配层注入请求真实值；工具总是
    使用绑定值（LLM 无法编造全量 UUID 落孤儿数据），未注入时回退 caller 传入值
    （MCP/writer 兼容）。
    """

    memory_service: object  # 有 list_preferences/create_preference/update_preference
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    expected_project_id: uuid.UUID | None = None


def _bind_project_id(expected: uuid.UUID | None, project_id: object) -> uuid.UUID | None:
    """解析绑定项目 id：装配期 expected 优先，未注入回退 caller 传入值."""
    bound = expected if expected is not None else project_id
    if bound is None:
        return None
    return bound if isinstance(bound, uuid.UUID) else _coerce_uuid(bound)


def build_memory_tools(deps: MemoryToolDeps) -> list[Tool]:
    """构建记忆工具（顺序固定：memory_list → memory_add → memory_update）。

    Args:
        deps: 工具依赖（memory + audit service 实例）。

    Returns:
        三个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """

    @instrument(caller_type="tool")
    async def _memory_list(
        project_id: uuid.UUID | str | None = None,
        category: str | None = None,
    ) -> str:
        async with _tool_db_lock_mod._tool_db_lock:
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                result = await deps.memory_service.list_preferences(  # type: ignore[attr-defined]  # 鸭子类型：memory_service 按契约提供 list_preferences
                    _project_id,
                    category=_coerce_category(category),
                )
                items = result[0] if isinstance(result, tuple) else result
                return _ok(_serialize_data(items))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _memory_add(
        project_id: uuid.UUID | str | None = None,
        category: str = "",
        pattern: str = "",
        note: str = "",
    ) -> str:
        async with _tool_db_lock_mod._tool_db_lock:
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                pref = await deps.memory_service.create_preference(  # type: ignore[attr-defined]  # 鸭子类型：memory_service 按契约提供 create_preference
                    project_id=_project_id,
                    category=_coerce_category(category),
                    pattern=pattern,
                    value=note,
                )
                # 成功审计；审计自身异常静默，不影响主返回
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="memory_add_created",
                        summary=f"记忆偏好添加 {category}",
                        degraded=True,
                    )
                return json.dumps(
                    {"ok": True, "preference_id": str(pref.id)},
                    ensure_ascii=False,
                )
            except Exception as exc:
                # 失败亦落审计；审计自身异常静默
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="memory_add_create_failed",
                        summary=f"记忆偏好添加失败: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _memory_update(
        project_id: uuid.UUID | str | None = None,
        preference_id: str = "",
        category: str | None = None,
        pattern: str | None = None,
        note: str | None = None,
    ) -> str:
        async with _tool_db_lock_mod._tool_db_lock:
            _project_id = _bind_project_id(deps.expected_project_id, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if category is not None:
                    update_fields["category"] = _coerce_category(category)
                if pattern is not None:
                    update_fields["pattern"] = pattern
                if note is not None:
                    update_fields["value"] = note
                await deps.memory_service.update_preference(  # type: ignore[attr-defined]  # 鸭子类型：memory_service 按契约提供 update_preference
                    preference_id,
                    **update_fields,
                )
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="memory_update_updated",
                        summary=f"记忆偏好更新 {preference_id}",
                        degraded=True,
                    )
                return json.dumps(
                    {"ok": True, "preference_id": str(preference_id)},
                    ensure_ascii=False,
                )
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:chat",
                        project_id=_project_id,
                        severity_summary="memory_update_update_failed",
                        summary=f"记忆偏好更新失败 {preference_id}: {exc}",
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return [
        Tool(spec=MEMORY_LIST_SPEC, func=_memory_list),
        Tool(spec=MEMORY_ADD_SPEC, func=_memory_add),
        Tool(spec=MEMORY_UPDATE_SPEC, func=_memory_update),
    ]
