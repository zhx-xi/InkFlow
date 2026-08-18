"""Agent 实体 REST API — 列表/工具目录/新建/详情/更新/删除（spec §3）.

端点前缀 /api/v1/agents（复数，F39 Agent 实体域；与 F4 编排管线单数
/api/v1/agent 不同域不冲突）。镜像 agent_templates.py 三层惯例：
_parse_id（非法格式 → 404「Agent 不存在」）/ _get_service / _run_service
（业务异常 → HTTP）/ _to_response（实体 → 响应字典）。

错误映射（spec §3.3 异常映射表）:
- AgentNotFoundError → 404（消息即 detail）
- AgentBuiltinError → 409（内置只读）
- AgentNameConflictError / ToolReferenceError / SkillReferenceError
  （AgentServiceError 子类）→ 422（消息即 detail）

路由顺序硬契约：GET /tools 必须声明在 GET /{agent_id} 之前（FastAPI 顺序
匹配，否则 "tools" 被吞进路径参数 404——镜像 agent_templates /default）。
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.agent import Agent, AgentCreate, AgentUpdate
from inkflow.domain.ports.agent_errors import (
    AgentBuiltinError,
    AgentNotFoundError,
    AgentServiceError,
)
from inkflow.domain.services.agent_entity_service import (
    BUILTIN_AGENT_SPECS,
    AgentEntityService,
)
from inkflow.infrastructure.agent.tools import TOOL_REGISTRY
from inkflow.infrastructure.database.repositories.agent_repo import (
    SQLiteAgentRepository,
)
from inkflow.infrastructure.database.repositories.skill_repo import (
    SQLiteSkillRepository,
)

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])

DETAIL_NOT_FOUND = "Agent 不存在"
"""id 不存在/非法格式的 404 detail（API 测试契约 #10 定稿文案）."""


def _parse_id(id_str: str, detail: str = DETAIL_NOT_FOUND) -> int:
    """安全解析 ID 字符串，仅接受整数格式；非法 → 404（镜像 foreshadowings 语义）."""
    try:
        return int(id_str)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=detail) from err


def _get_service(db: AsyncSession) -> AgentEntityService:
    """获取 AgentEntityService 实例（Agent + Skill 双仓储注入）."""
    return AgentEntityService(
        agent_repository=SQLiteAgentRepository(db),
        skill_repository=SQLiteSkillRepository(db),
    )


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）."""
    try:
        return await coro
    except AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AgentBuiltinError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except AgentServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _role_key_of(agent: Agent) -> str | None:
    """内置 Agent 的链角色键映射（#473 R1）；自定义/未命中 → None."""
    if not agent.builtin:
        return None
    for spec in BUILTIN_AGENT_SPECS:
        if spec["name"] == agent.name:
            return spec["role_key"]
    return None


def _to_response(agent: Agent) -> dict:
    """Agent 实体 → 响应字典（12 字段全集 + role_key 透出，id 原样 int）.

    role_key（#473 R1）：内置 Agent 按 name 反查 BUILTIN_AGENT_SPECS 的
    链角色键映射；非内置/未命中 → None（前端 AgentChainCard 按 role_key
    派生内置角色行，不再 hardcode 名称/图标/描述）。
    """
    resp = agent.model_dump(mode="json")
    resp["role_key"] = _role_key_of(agent)
    return resp


@router.get("")
async def list_agents(
    db: AsyncSession = Depends(get_db),
):
    """Agent 列表（spec §3.1）— {items, total} 信封，每项完整实体."""
    svc = _get_service(db)
    items = await _run_service(svc.list())
    return {"items": [_to_response(agent) for agent in items], "total": len(items)}


@router.get("/tools")
async def list_tool_catalog():
    """工具目录（spec §2.3/§5.1）— TOOL_REGISTRY 6 工具按目录原序（save_draft 末位）.

    路由顺序硬契约：本端点必须声明在 /{agent_id} 之前，否则 "tools" 被
    _parse_id 吞掉 → 404「Agent 不存在」（API 测试契约 #3）。
    """
    return {
        "items": [
            {
                "name": spec.name,
                "description": spec.description,
                "group": spec.group,
                "input_schema": spec.input_schema,
            }
            for spec in TOOL_REGISTRY
        ]
    }


@router.post("", status_code=201)
async def create_agent(
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """新建自定义 Agent — 201 + 完整实体（builtin 恒 False）."""
    svc = _get_service(db)
    agent = await _run_service(svc.create(data))
    return _to_response(agent)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Agent 详情；不存在/非法 id → 404「Agent 不存在」."""
    aid = _parse_id(agent_id)
    svc = _get_service(db)
    agent = await _run_service(svc.get(aid))
    return _to_response(agent)


@router.patch("/{agent_id}")
async def update_agent(
    agent_id: str,
    data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新（exclude_unset 浅合并）；不存在 → 404；内置 → 409；白名单/同名 → 422."""
    aid = _parse_id(agent_id)
    svc = _get_service(db)
    agent = await _run_service(svc.update(aid, data))
    return _to_response(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除自定义 Agent — 204 空响应；不存在 → 404；内置 → 409."""
    aid = _parse_id(agent_id)
    svc = _get_service(db)
    await _run_service(svc.delete(aid))
