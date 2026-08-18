"""F48 知识图谱 REST API — 6 个端点（spec §3.1/§3.3）。

端点风格沿用 F36 maps.py：创建/列表/图谱聚合嵌套项目路径
（/projects/{project_id}/knowledge-relations、
/projects/{project_id}/knowledge-graph），详情/更新/删除扁平
（/knowledge-relations/...）。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 KnowledgeGraphService —— 单元测试通过
`@patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")`
mock 服务层。

错误映射（spec §3.3 异常映射表）:
- KnowledgeGraphServiceError 子类（冲突/自环/实体不存在/字段校验）→ 422（消息即 detail）
- KnowledgeRelationNotFoundError / ProjectNotFoundError（F10 复用）→ 404
- 非法 UUID（_parse_id）→ 404（detail 按端点语义：项目不存在 / 关系不存在）

依据: specs/f48-knowledge-graph/spec.md §3.1/§3.3。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_knowledge_graph_service
from inkflow.domain.models.knowledge_graph import (
    KnowledgeRelationCreate,
    KnowledgeRelationUpdate,
)
from inkflow.domain.ports.knowledge_graph_errors import (
    KnowledgeGraphServiceError,
    KnowledgeRelationNotFoundError,
)
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService

router = APIRouter(prefix="/api/v1", tags=["知识图谱"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 F9 characters.py）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail=detail) from err


def _get_svc(db: AsyncSession) -> KnowledgeGraphService:
    """获取 KnowledgeGraphService 实例（方便 mock）。"""
    return get_knowledge_graph_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）。"""
    try:
        return await coro
    except KnowledgeGraphServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except KnowledgeRelationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── KnowledgeRelation CRUD + 图谱聚合 ───────────────────────────


@router.post("/projects/{project_id}/knowledge-relations", status_code=201)
async def create_relation(
    project_id: str,
    data: KnowledgeRelationCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建图谱关系（六元组 + 可选描述；source 恒 manual，spec §3.1）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    # F48 契约（F9 惯例）：DTO 解包为展开字段调 service（禁止 DTO 透传——
    # service 签名见 test_knowledge_graph_service.py docstring）
    relation = await _run_service(svc.create_relation(pid, **data.model_dump()))
    return relation.model_dump(mode="json")


@router.get("/projects/{project_id}/knowledge-relations")
async def list_relations(
    project_id: str,
    source_type: str | None = Query(None),
    target_type: str | None = Query(None),
    relation_type: str | None = Query(None),
    source: str | None = Query(None),
    offset: int = Query(0),
    limit: int = Query(50),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内关系列表（过滤 + 分页；?source=ai 为 #479 预留，spec §3.1）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    # 过滤参数仅传有值者（缺省形态不携带 kwargs，测试锁定）
    filters: dict[str, str] = {}
    if source_type is not None:
        filters["source_type"] = source_type
    if target_type is not None:
        filters["target_type"] = target_type
    if relation_type is not None:
        filters["relation_type"] = relation_type
    if source is not None:
        filters["source"] = source
    items, total = await _run_service(
        svc.list_relations(pid, **filters, offset=offset, limit=limit)
    )
    return {
        "items": [r.model_dump(mode="json") for r in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/projects/{project_id}/knowledge-graph")
async def get_graph(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取图谱聚合视图（nodes + edges，合并 character_relations 去重，spec §3.1）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    view = await _run_service(svc.graph(pid))
    return view.model_dump(mode="json")


@router.get("/knowledge-relations/{relation_id}")
async def get_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取关系详情（spec §3.1）。"""
    rid = _parse_id(relation_id, detail="关系不存在")
    svc = _get_svc(db)
    relation = await _run_service(svc.get_relation(rid))
    return relation.model_dump(mode="json")


@router.patch("/knowledge-relations/{relation_id}")
async def update_relation(
    relation_id: str,
    data: KnowledgeRelationUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新关系（全可选，exclude_unset 语义，spec §3.1）。"""
    rid = _parse_id(relation_id, detail="关系不存在")
    svc = _get_svc(db)
    # F48 契约（F9 惯例）：DTO 解包展开字段调 service——exclude_unset
    # 保证未传字段不出现在调用参数中（测试锁定）
    relation = await _run_service(
        svc.update_relation(rid, **data.model_dump(exclude_unset=True))
    )
    return relation.model_dump(mode="json")


@router.delete("/knowledge-relations/{relation_id}", status_code=204)
async def delete_relation(
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """真删关系（spec §3.1）。"""
    rid = _parse_id(relation_id, detail="关系不存在")
    svc = _get_svc(db)
    await _run_service(svc.delete_relation(rid))
