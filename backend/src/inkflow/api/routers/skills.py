"""Skill 实体 REST API — 列表（含 agent_ids 反查）/上传/详情/更新/删除（spec §3）.

端点前缀 /api/v1/skills（单数，DB Skill 实体域；与 F19-skills 复数文件系统
CLI 不同域）。镜像 agent_templates.py 三层惯例：_parse_id（非法格式 → 404
「Skill 不存在」）/ _get_service / _run_service（业务异常 → HTTP）/
_to_response（实体 + agent_ids 反查）。

错误映射（spec §3.3 异常映射表）:
- SkillNotFoundError → 404（消息即 detail）
- SkillBuiltinError → 409（内置只读）
- SkillNameConflictError / SkillFrontmatterError（SkillServiceError 子类）
  → 422（消息即 detail）

agent_ids 反查（spec §5.4 双向视图数据源）：经 SQLiteAgentRepository
.list_agents_by_skill 按 skill_ids 精确含 str(skill_id) 反查，输出
[{id, name}]（无引用 = []）。
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillNotFoundError,
    SkillServiceError,
)
from inkflow.domain.services.skill_service import SkillService
from inkflow.infrastructure.database.repositories.agent_repo import (
    SQLiteAgentRepository,
)
from inkflow.infrastructure.database.repositories.skill_repo import (
    SQLiteSkillRepository,
)

router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])

DETAIL_NOT_FOUND = "Skill 不存在"
"""id 不存在/非法格式的 404 detail（API 测试契约 #8 定稿文案）."""


def _parse_id(id_str: str, detail: str = DETAIL_NOT_FOUND) -> int:
    """安全解析 ID 字符串，仅接受整数格式；非法 → 404（镜像 foreshadowings 语义）."""
    try:
        return int(id_str)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=detail) from err


def _get_service(db: AsyncSession) -> SkillService:
    """获取 SkillService 实例（Skill + Agent 双仓储注入，级联清引用用）."""
    return SkillService(
        skill_repository=SQLiteSkillRepository(db),
        agent_repository=SQLiteAgentRepository(db),
    )


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）."""
    try:
        return await coro
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SkillBuiltinError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SkillServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


async def _agent_ids(db: AsyncSession, skill_id: int) -> list[dict]:
    """agent_ids 反查（spec §5.4）：引用该 Skill 的 Agent [{id, name}]（按 name 升序）."""
    refs = await SQLiteAgentRepository(db).list_agents_by_skill(skill_id)
    return [{"id": agent.id, "name": agent.name} for agent in refs]


def _to_response(skill: Skill, *, agent_ids: list[dict] | None = None) -> dict:
    """Skill 实体 → 响应字典（8 字段全集 + agent_ids 反查列表）."""
    data = skill.model_dump(mode="json")
    data["agent_ids"] = agent_ids if agent_ids is not None else []
    return data


@router.get("")
async def list_skills(
    db: AsyncSession = Depends(get_db),
):
    """Skill 列表（spec §3.1）— {items, total} 信封，每项含 agent_ids 反查."""
    svc = _get_service(db)
    items = await _run_service(svc.list())
    result = []
    for skill in items:
        assert skill.id is not None  # list() 仅返回已持久化 Skill（id 由 repo 分配）
        refs = await _agent_ids(db, skill.id)
        result.append(_to_response(skill, agent_ids=refs))
    return {"items": result, "total": len(items)}


@router.post("", status_code=201)
async def create_skill(
    data: SkillCreate,
    db: AsyncSession = Depends(get_db),
):
    """上传/创建 Skill — 201 + 完整实体（frontmatter 解析 name/description，
    source 恒 user_upload，agent_ids=[]）."""
    svc = _get_service(db)
    skill = await _run_service(svc.create(data))
    return _to_response(skill)


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Skill 详情（含 agent_ids 反查）；不存在/非法 id → 404「Skill 不存在」."""
    sid = _parse_id(skill_id)
    svc = _get_service(db)
    skill = await _run_service(svc.get(sid))
    refs = await _agent_ids(db, sid)
    return _to_response(skill, agent_ids=refs)


@router.patch("/{skill_id}")
async def update_skill(
    skill_id: str,
    data: SkillUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新（exclude_unset 浅合并）；不存在 → 404；内置 → 409；改名冲突 → 422."""
    sid = _parse_id(skill_id)
    svc = _get_service(db)
    skill = await _run_service(svc.update(sid, data))
    refs = await _agent_ids(db, sid)
    return _to_response(skill, agent_ids=refs)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 Skill — 204 空响应；不存在 → 404；内置 → 409；被引用 → 级联清引用."""
    sid = _parse_id(skill_id)
    svc = _get_service(db)
    await _run_service(svc.delete(sid))
