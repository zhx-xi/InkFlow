"""Skill 实体 REST API — 列表（含 agent_ids 反查）/上传/详情/更新/删除（spec §3 + ADR-039 #522）.

端点前缀 /api/v1/skills。#522 文件系统真源：路径标识 = skill 目录名
（skill_name，N2 规则）；Skill 实体无 id 字段，响应兼容层 id 字段值 =
name。镜像 agent_templates.py 三层惯例：_get_service / _run_service（业务
异常 → HTTP）/ _to_response（实体 + agent_ids 反查）。

错误映射（spec §3.3 异常映射表 + #522 定稿文案）:
- SkillNotFoundError → 404「Skill 不存在」（不存在/非法名）
- SkillBuiltinError → 409「内置 skill 只读」
- SkillNameConflictError → 422「同名 skill 已存在」
- SkillFrontmatterError → 422「frontmatter 不合法」

agent_ids 反查（spec §5.4 双向视图数据源）：经 SQLiteAgentRepository
.list_agents_by_skill(skill_name) 按 skill_ids 精确含目录名反查，输出
[{id, name}]（无引用 = []）。
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.core.config import config
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
)
from inkflow.domain.services.skill_service import SkillService
from inkflow.infrastructure.database.repositories.agent_repo import (
    SQLiteAgentRepository,
)

router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])

DETAIL_NOT_FOUND = "Skill 不存在"
"""skill_name 不存在/非法格式的 404 detail（#522 定稿文案）."""

DETAIL_BUILTIN = "内置 skill 只读"
"""内置 skill PATCH/DELETE 的 409 detail（#522 定稿文案）."""

DETAIL_CONFLICT = "同名 skill 已存在"
"""同名 skill 上传/复制的 422 detail（#522 定稿文案）."""

DETAIL_FRONTMATTER = "frontmatter 不合法"
"""frontmatter 缺失/非法的 422 detail（#522 定稿文案）."""


def _get_service(db: AsyncSession) -> SkillService:
    """获取 SkillService 实例（文件系统真源根 = config.data_dir / "skills"，动态读取）."""
    return SkillService(
        skills_root=config.data_dir / "skills",
        agent_repository=SQLiteAgentRepository(db),
    )


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3 + #522 定稿文案）."""
    try:
        return await coro
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SkillBuiltinError as e:
        raise HTTPException(status_code=409, detail=DETAIL_BUILTIN) from e
    except SkillNameConflictError as e:
        raise HTTPException(status_code=422, detail=DETAIL_CONFLICT) from e
    except SkillFrontmatterError as e:
        raise HTTPException(status_code=422, detail=DETAIL_FRONTMATTER) from e


async def _agent_ids(db: AsyncSession, skill_name: str) -> list[dict]:
    """agent_ids 反查（spec §5.4）：引用该 skill 目录名的 Agent [{id, name}]（按 name 升序）."""
    refs = await SQLiteAgentRepository(db).list_agents_by_skill(skill_name)
    return [{"id": agent.id, "name": agent.name} for agent in refs]


def _to_response(skill: Skill, *, agent_ids: list[dict] | None = None) -> dict:
    """Skill 实体 → 响应字典（#522 兼容层：id 字段值 = name，其余字段全集 + agent_ids）."""
    data = skill.model_dump(mode="json")
    data["id"] = skill.name
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
        refs = await _agent_ids(db, skill.name)
        result.append(_to_response(skill, agent_ids=refs))
    return {"items": result, "total": len(items)}


@router.post("", status_code=201)
async def create_skill(
    data: SkillCreate,
    db: AsyncSession = Depends(get_db),
):
    """上传/创建 Skill — 201 + 完整实体（frontmatter 解析 name=目录名，
    source 恒 user_upload，agent_ids=[]；同名 → 422「同名 skill 已存在」）."""
    svc = _get_service(db)
    skill = await _run_service(svc.create(data))
    return _to_response(skill)


@router.post("/{skill_name}/duplicate", status_code=201)
async def duplicate_skill(
    skill_name: str,
    db: AsyncSession = Depends(get_db),
):
    """复制 Skill — 201 + 完整实体（name = f"{源名}-copy"，副本转用户态，
    agent_ids=[]；副本名冲突 → 422「同名 skill 已存在」）."""
    svc = _get_service(db)
    skill = await _run_service(svc.duplicate(skill_name))
    return _to_response(skill, agent_ids=[])


@router.get("/{skill_name}")
async def get_skill(
    skill_name: str,
    db: AsyncSession = Depends(get_db),
):
    """Skill 详情（含 agent_ids 反查）；不存在/非法名 → 404「Skill 不存在」."""
    svc = _get_service(db)
    skill = await _run_service(svc.get(skill_name))
    refs = await _agent_ids(db, skill.name)
    return _to_response(skill, agent_ids=refs)


@router.patch("/{skill_name}")
async def update_skill(
    skill_name: str,
    data: SkillUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新（exclude_unset 浅合并）；不存在 → 404；内置 → 409「内置 skill 只读」；
    content 写回文件（frontmatter 非法 → 422「frontmatter 不合法」）."""
    svc = _get_service(db)
    skill = await _run_service(svc.update(skill_name, data))
    refs = await _agent_ids(db, skill.name)
    return _to_response(skill, agent_ids=refs)


@router.delete("/{skill_name}", status_code=204)
async def delete_skill(
    skill_name: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 Skill — 204 空响应；不存在 → 404；内置 → 409「内置 skill 只读」；
    被引用 → 级联清 Agent.skill_ids 引用（#522 目录名语义）."""
    svc = _get_service(db)
    await _run_service(svc.delete(skill_name))
