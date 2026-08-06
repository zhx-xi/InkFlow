"""AgentTemplate REST API — 列表/新建/详情/更新/删除/复制/默认查询/设为默认.

端点风格沿用既有扁平路由（spec §9.3）：前缀 /api/v1/agent-templates。
各端点通过 Depends(get_db) 注入数据库 session，再调用模块级 _get_service(db)
获取 AgentTemplateService。

错误映射（spec §9.3 契约）:
- id 缺失/非法格式（非整数）→ 404「模板不存在」（镜像 foreshadowings
  _parse_id 404 语义，非法格式不 422）
- AgentTemplateNotFoundError → 404（消息即 detail）
- AgentTemplateNameConflictError → 422（消息即 detail）
- AgentTemplateBuiltinError（默认/内置模板）→ 409「默认模板不可删除」
  （API 测试契约 #12 定稿；service 侧 BuiltinError 消息为「内置模板不可删除」）
- /default 路由必须声明在 /{template_id} 之前（FastAPI 顺序匹配，
  否则 "default" 被吞进 path 参数 404 —— API 测试契约 #3 硬性要求）

响应结构: 模板 10 字段全集（roles 固定四角色键 architect/writer/auditor/
reviser，缺省 key 用默认 RoleTemplate() 补齐）；详情端点额外含 used_by
引用项目列表 [{id, name}]。
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_project_service
from inkflow.domain.models.agent_template import (
    AgentTemplate,
    AgentTemplateCreate,
    AgentTemplateUpdate,
    RoleTemplate,
)
from inkflow.domain.ports.agent_template_errors import (
    AgentTemplateBuiltinError,
    AgentTemplateNotFoundError,
    AgentTemplateServiceError,
)
from inkflow.domain.services.agent_template_service import AgentTemplateService
from inkflow.infrastructure.database.repositories.agent_template_repo import (
    SQLiteAgentTemplateRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)

router = APIRouter(prefix="/api/v1/agent-templates", tags=["AgentTemplates"])

ROLE_KEYS = ("architect", "writer", "auditor", "reviser")
"""模板 roles 四角色键（spec §9.1，顺序契约：API 响应固定键序）."""

DEFAULT_DELETE_DETAIL = "默认模板不可删除"
"""删除默认模板的 409 detail（API 测试契约 #12 定稿；service 侧 BuiltinError
消息为「内置模板不可删除」，路由层映射为本契约文案）."""

BUILTIN_DEFAULT_MODEL = "openai/gpt-4o"
"""内置默认模型（与 pipeline_templates.py 四角色默认一致）.
roles 输出时 model 为 None 的角色回填该值（spec §9.2.5「关闭 = 该角色使用默认模型」）."""


def _parse_id(id_str: str, detail: str = "模板不存在") -> int:
    """安全解析 ID 字符串，仅接受整数格式；非法 → 404（镜像 foreshadowings 语义）."""
    try:
        return int(id_str)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=detail) from err


class SetDefaultRequest(BaseModel):
    """PATCH /default 请求体 — {id: 模板 id}（必填，去空白后非空）."""

    id: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """验证模板 id：去空白后非空（缺失/空白 → 422 Pydantic 校验错误列表）."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("模板 id 不能为空")
        return stripped


def _get_service(db: AsyncSession) -> AgentTemplateService:
    """获取 AgentTemplateService 实例（双仓储注入：模板 + 项目级联清引用用）."""
    return AgentTemplateService(
        template_repository=SQLiteAgentTemplateRepository(db),
        project_repository=SQLiteProjectRepository(db),
    )


def _get_project_service(db: AsyncSession):
    """获取 ProjectService 实例（deps 工厂镜像；级联清引用由 service 内部完成）."""
    return get_project_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码."""
    try:
        return await coro
    except AgentTemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AgentTemplateBuiltinError as e:
        raise HTTPException(status_code=409, detail=DEFAULT_DELETE_DETAIL) from e
    except AgentTemplateServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _to_response(template: AgentTemplate, *, used_by: list[dict] | None = None) -> dict:
    """实体 → 响应字典：模板 10 字段 + roles 四角色键归一 + 可选 used_by.

    回填语义：未配置角色（model=None）回填 BUILTIN_DEFAULT_MODEL，保证
    roles[role].model 恒为 str（API 测试契约；spec §9.2.5 enabled=False 亦然）."""
    data = template.model_dump(mode="json")
    roles: dict[str, dict] = {}
    for key in ROLE_KEYS:
        role = template.roles.get(key, RoleTemplate())
        role_dict = role.model_dump(mode="json")
        # 契约：roles[role].model 必须为 str；未配置角色（None）回填内置默认模型
        # （spec §9.2.5 enabled=False 语义「关闭 = 使用默认模型」）
        role_dict["model"] = role_dict["model"] or BUILTIN_DEFAULT_MODEL
        roles[key] = role_dict
    data["roles"] = roles
    if used_by is not None:
        data["used_by"] = used_by
    return data


@router.get("")
async def list_agent_templates(
    db: AsyncSession = Depends(get_db),
):
    """模板列表（spec §9.3）— {items, total} 信封，每项含 10 字段响应."""
    svc = _get_service(db)
    items = await _run_service(svc.list())
    return {"items": [_to_response(t) for t in items], "total": len(items)}


@router.post("", status_code=201)
async def create_agent_template(
    data: AgentTemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    """新建模板 — 201 + 完整响应结构（roles 四键归一）."""
    svc = _get_service(db)
    template = await _run_service(svc.create(data))
    return _to_response(template)


@router.get("/default")
async def get_default_template(
    db: AsyncSession = Depends(get_db),
):
    """默认模板查询（spec §9.3）— 200 {template: null|完整响应}（不 404）."""
    svc = _get_service(db)
    templates = await _run_service(svc.list())
    default = next((t for t in templates if t.is_default), None)
    return {"template": _to_response(default) if default else None}


@router.patch("/default")
async def set_default_template(
    data: SetDefaultRequest,
    db: AsyncSession = Depends(get_db),
):
    """设为默认（spec §9.3）— 200 + 完整响应；id 不存在/非法 → 404；单例由 repo 保证."""
    tid = _parse_id(data.id)
    svc = _get_service(db)
    template = await _run_service(svc.set_default(tid))
    return _to_response(template)


@router.get("/{template_id}")
async def get_agent_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    """模板详情（含 used_by 引用列表）；不存在/非法 id → 404."""
    tid = _parse_id(template_id)
    svc = _get_service(db)
    template = await _run_service(svc.get(tid))
    refs = await SQLiteAgentTemplateRepository(db).list_projects_by_template(tid)
    used_by = [{"id": str(p.id), "name": p.name} for p in refs]
    return _to_response(template, used_by=used_by)


@router.patch("/{template_id}")
async def update_agent_template(
    template_id: str,
    data: AgentTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新（exclude_unset 浅合并；roles 整体替换）；不存在 → 404."""
    tid = _parse_id(template_id)
    svc = _get_service(db)
    template = await _run_service(svc.update(tid, data))
    return _to_response(template)


@router.delete("/{template_id}", status_code=204)
async def delete_agent_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除模板 — 204 空响应；不存在 → 404；默认模板 → 409 保护；被引用 → 级联清空."""
    tid = _parse_id(template_id)
    svc = _get_service(db)
    await _run_service(svc.delete(tid))


@router.post("/{template_id}/duplicate", status_code=201)
async def duplicate_agent_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    """复制模板 — 201 + 完整响应；name = 原名称 副本；不存在 → 404."""
    tid = _parse_id(template_id)
    svc = _get_service(db)
    template = await _run_service(svc.duplicate(tid))
    return _to_response(template)
