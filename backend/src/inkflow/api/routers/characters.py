"""F9 角色管理 REST API — 15 个端点：角色 CRUD + 关系 + 分组 + AI 提取。

端点风格沿用 F2（spec §3）：创建/列表嵌套项目路径
（/projects/{project_id}/...），详情/更新/删除扁平（/characters/...、
/character-groups/...）。AI 提取为 POST /characters/extract，注册在
/characters/{character_id} 之前避免路径歧义。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 CharacterService —— 单元测试通过
`@patch("inkflow.api.routers.characters.get_character_service")` 来
mock 服务层（同 project.py 模式）。

错误映射（spec §3.5 异常映射表）:
- 无效 UUID / 资源不存在（Service 返回 None）→ 404
- CharacterServiceError 子类（同名/自环/跨项目/重复）→ 422（消息即 detail）
- CharacterNotFoundError / ProjectNotFoundError → 404
- CharacterExtractionError → 500「角色提取失败: LLM 输出无法解析，请重试」
- LLMRequestError → 500「LLM 调用失败，请稍后重试」

依据: specs/f9-character/spec.md §3/§5/§7。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_character_service, get_db
from inkflow.domain.models.character import (
    CharacterExtractRequest,
    CharacterRelationCreate,
    CharacterUpdate,
    _validate_name,
    _validate_relation_type,
)
from inkflow.domain.ports.character_errors import (
    CharacterExtractionError,
    CharacterNotFoundError,
    CharacterServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.character_service import CharacterService

router = APIRouter(prefix="/api/v1", tags=["角色"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 chapter.py）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail=detail) from err


def _get_svc(db: AsyncSession) -> CharacterService:
    """获取 CharacterService 实例（方便 mock）。"""
    return get_character_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.5）。"""
    try:
        return await coro
    except CharacterServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except CharacterNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CharacterExtractionError as err:
        raise HTTPException(
            status_code=500, detail="角色提取失败: LLM 输出无法解析，请重试"
        ) from err
    except LLMRequestError as err:
        raise HTTPException(status_code=500, detail="LLM 调用失败，请稍后重试") from err


def _validate_group_name(v: str) -> str:
    """分组名校验：去空白后非空且不超过 50 字符（spec §2.2）。"""
    stripped = v.strip()
    if not stripped:
        raise ValueError("分组名不能为空")
    if len(stripped) > 50:
        raise ValueError("分组名不能超过 50 个字符")
    return stripped


class CharacterCreateBody(BaseModel):
    """创建角色请求体 — project_id 取自路径参数，不在 body（spec §3.2）。"""

    name: str
    personality: str = ""
    background: str = ""
    goals: str = ""
    group_ids: list[uuid.UUID] = []
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证角色名：去空白后非空且不超过 50 字符."""
        return _validate_name(v)


class CharacterGroupCreateBody(BaseModel):
    """创建分组请求体（spec §3.3）。"""

    name: str
    description: str = ""
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证分组名：去空白后非空且不超过 50 字符."""
        return _validate_group_name(v)


class CharacterGroupUpdateBody(BaseModel):
    """更新分组请求体 — 全可选（None 表示不修改）。"""

    name: str | None = None
    description: str | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证分组名：None 直接返回，否则复用共享校验."""
        if v is None:
            return v
        return _validate_group_name(v)


class CharacterRelationUpdateBody(BaseModel):
    """更新关系请求体 — 仅 relation_type / description（from/to 不变）。"""

    relation_type: str | None = None
    description: str | None = None

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str | None) -> str | None:
        """验证关系类型：None 直接返回，否则复用共享校验."""
        if v is None:
            return v
        return _validate_relation_type(v)


# ── AI 提取（先于 /characters/{character_id} 注册，避免路径歧义）──


@router.post("/characters/extract")
async def extract_characters(
    request: CharacterExtractRequest,
    db: AsyncSession = Depends(get_db),
):
    """AI 提取角色/关系（spec §5.1）。"""
    svc = _get_svc(db)
    result = await _run_service(svc.extract(request))
    return result.model_dump(mode="json")


# ── Character ──────────────────────────────────────────────────


@router.post("/projects/{project_id}/characters", status_code=201)
async def create_character(
    project_id: str,
    data: CharacterCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建角色（spec §3.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    character = await _run_service(
        svc.create_character(
            pid,
            data.name,
            data.personality,
            data.background,
            data.goals,
            data.group_ids,
            extra=data.extra,
        )
    )
    return character.model_dump(mode="json")


@router.get("/projects/{project_id}/characters")
async def list_characters(
    project_id: str,
    search: str | None = Query(None),
    group_id: str | None = Query(None),
    sort_by: str = Query("updated_at"),
    sort_desc: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内角色列表（搜索 + 分组过滤 + 分页，spec §3.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    gid = _parse_id(group_id, detail="分组不存在") if group_id is not None else None
    svc = _get_svc(db)
    items, total = await _run_service(
        svc.list_characters(
            pid,
            search=search,
            group_id=gid,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )
    )
    groups = await _run_service(svc.list_groups(pid))
    name_by_id = {g.id: g.name for g in groups}
    items_json = []
    for c in items:
        item = c.model_dump(mode="json")
        item["group_names"] = [name_by_id[g] for g in c.group_ids if g in name_by_id]
        items_json.append(item)
    return {
        "items": items_json,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/characters/{character_id}")
async def get_character(
    character_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取角色详情（含 relations 双向聚合，spec §3.4）。"""
    cid = _parse_id(character_id, detail="角色不存在")
    svc = _get_svc(db)
    character = await _run_service(svc.get_character(cid))
    if character is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    groups = await _run_service(svc.list_groups(character.project_id))
    name_by_id = {g.id: g.name for g in groups}
    relations = await _run_service(svc.list_relations(cid))
    payload = character.model_dump(mode="json")
    payload["group_names"] = [name_by_id[g] for g in character.group_ids if g in name_by_id]
    payload["relations"] = []
    for rel in relations:
        other_id = (
            rel.to_character_id if rel.from_character_id == character.id else rel.from_character_id
        )
        other = await svc.get_character(other_id)
        payload["relations"].append(
            {
                "id": str(rel.id),
                "to_character_id": str(other_id),
                "to_name": other.name if other is not None else "",
                "relation_type": rel.relation_type,
                "description": rel.description,
            }
        )
    return payload


@router.patch("/characters/{character_id}")
async def update_character(
    character_id: str,
    data: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新角色（CharacterUpdate 全可选，exclude_unset 语义）。"""
    cid = _parse_id(character_id, detail="角色不存在")
    svc = _get_svc(db)
    character = await _run_service(svc.update_character(cid, data))
    if character is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    return character.model_dump(mode="json")


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    character_id: str,
    db: AsyncSession = Depends(get_db),
):
    """真删角色（v1.1 默认真删，无 force 参数，spec §3.2）。"""
    cid = _parse_id(character_id, detail="角色不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_character(cid))
    if not ok:
        raise HTTPException(status_code=404, detail="角色不存在")


# ── CharacterRelation ──────────────────────────────────────────


@router.get("/characters/{character_id}/relations")
async def list_character_relations(
    character_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取角色关系列表（双向，聚合 from_name/to_name，spec §3.3）。"""
    cid = _parse_id(character_id, detail="角色不存在")
    svc = _get_svc(db)
    relations = await _run_service(svc.list_relations(cid))
    items = []
    for rel in relations:
        from_char = await svc.get_character(rel.from_character_id)
        to_char = await svc.get_character(rel.to_character_id)
        item = rel.model_dump(mode="json")
        item["from_name"] = from_char.name if from_char is not None else ""
        item["to_name"] = to_char.name if to_char is not None else ""
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post("/characters/{character_id}/relations", status_code=201)
async def create_relation(
    character_id: str,
    data: CharacterRelationCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建关系（from = 路径角色，spec §3.3）。"""
    cid = _parse_id(character_id, detail="角色不存在")
    svc = _get_svc(db)
    relation = await _run_service(
        svc.create_relation(cid, data.to_character_id, data.relation_type, data.description)
    )
    return relation.model_dump(mode="json")


@router.patch("/characters/{character_id}/relations/{relation_id}")
async def update_relation(
    character_id: str,
    relation_id: str,
    data: CharacterRelationUpdateBody,
    db: AsyncSession = Depends(get_db),
):
    """部分更新关系（仅 relation_type / description）。"""
    cid = _parse_id(character_id, detail="角色不存在")
    rid = _parse_id(relation_id, detail="关系不存在")
    svc = _get_svc(db)
    relation = await _run_service(
        svc.update_relation(
            cid,
            rid,
            relation_type=data.relation_type,
            description=data.description,
        )
    )
    if relation is None:
        raise HTTPException(status_code=404, detail="关系不存在")
    return relation.model_dump(mode="json")


@router.delete("/characters/{character_id}/relations/{relation_id}", status_code=204)
async def delete_relation(
    character_id: str,
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """真删关系（v1.1，spec §7）。"""
    cid = _parse_id(character_id, detail="角色不存在")
    rid = _parse_id(relation_id, detail="关系不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_relation(cid, rid))
    if not ok:
        raise HTTPException(status_code=404, detail="关系不存在")


# ── CharacterGroup ─────────────────────────────────────────────


@router.post("/projects/{project_id}/character-groups", status_code=201)
async def create_character_group(
    project_id: str,
    data: CharacterGroupCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建角色分组（spec §3.3）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    group = await _run_service(svc.create_group(pid, data.name, data.description, data.sort_order))
    return group.model_dump(mode="json")


@router.get("/projects/{project_id}/character-groups")
async def list_character_groups(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取项目内分组列表（含 member_count，spec §3.3）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    groups = await _run_service(svc.list_groups(pid))
    items = []
    for group in groups:
        _, member_count = await _run_service(
            svc.list_characters(group.project_id, group_id=group.id)
        )
        item = group.model_dump(mode="json")
        item["member_count"] = member_count
        items.append(item)
    return {"items": items, "total": len(items)}


@router.get("/character-groups/{group_id}")
async def get_character_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取分组详情（含 member_count）。"""
    gid = _parse_id(group_id, detail="分组不存在")
    svc = _get_svc(db)
    group = await _run_service(svc.get_group(gid))
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    _, member_count = await _run_service(svc.list_characters(group.project_id, group_id=gid))
    payload = group.model_dump(mode="json")
    payload["member_count"] = member_count
    return payload


@router.patch("/character-groups/{group_id}")
async def update_character_group(
    group_id: str,
    data: CharacterGroupUpdateBody,
    db: AsyncSession = Depends(get_db),
):
    """部分更新分组（改名撞同名 → 422）。"""
    gid = _parse_id(group_id, detail="分组不存在")
    svc = _get_svc(db)
    group = await _run_service(
        svc.update_group(
            gid,
            name=data.name,
            description=data.description,
            sort_order=data.sort_order,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    return group.model_dump(mode="json")


@router.delete("/character-groups/{group_id}", status_code=204)
async def delete_character_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """真删分组（v1.1，成员 group_id 置 NULL，spec §6.2）。"""
    gid = _parse_id(group_id, detail="分组不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_group(gid))
    if not ok:
        raise HTTPException(status_code=404, detail="分组不存在")
