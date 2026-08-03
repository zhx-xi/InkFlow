"""F14 统一提取 REST API — 4 个端点：统一提取 + runs 查询 + 向量索引/检索。

端点风格（spec §3.1）: 统一提取入口**扁平**（POST /api/v1/extract——type 是
资源维度而非项目维度，镜像 F9 `/characters/extract` 扁平先例）；runs 查询与
向量动作**嵌套项目路径**（/projects/{project_id}/extractions/runs、
/projects/{project_id}/vector/reindex、/projects/{project_id}/vector/retrieve）。
`/extract` 为静态路径段，无与既有路由的歧义（spec §3.1 注）。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级 `_get_svc(db)`
获取 ExtractionService —— 单元测试通过
`@patch("inkflow.api.routers.extractions.get_extraction_service")` 来 mock
服务层（同 F9-F13 模式）。

错误映射（spec §3.4 异常映射表）:
- 无效 UUID（路径参数）→ 404（同 F1-F13 `_parse_id` 模式，detail=「项目不存在」）
- ProjectNotFoundError → 404（消息即 detail）
- ExtractionServiceError 子类（ExtractionValidationError /
  UnsupportedExtractionTypeError / ChapterNotFoundError /
  ChapterNotInProjectError）与 F11 OutlineNameConflictError、F16
  StyleValidationError → 422（消息即 detail）
- LLMRequestError → 500（固定文案，同 F9-F11）
- 提取/生成管线解析失败（CharacterExtractionError / WorldExtractionError /
  OutlineGenerationError / ForeshadowingExtractionError /
  TimelineExtractionError）→ 500（消息即 detail）
- RAGUnavailableError / VectorStoreError / ExtractionRunError → 500
  （消息即 detail）

依据: specs/f14-extraction-service/spec.md §3/§5/§7 +
specs/f16-style-service/spec.md §3.3/§8.2（StyleValidationError 映射）。
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_extraction_service
from inkflow.domain.models.extraction import ExtractionRequest, ExtractionType
from inkflow.domain.ports.character_errors import (
    CharacterExtractionError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.extraction_errors import (
    ExtractionRunError,
    ExtractionServiceError,
    RAGUnavailableError,
    VectorStoreError,
)
from inkflow.domain.ports.foreshadowing_errors import ForeshadowingExtractionError
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.outline_errors import (
    OutlineGenerationError,
    OutlineNameConflictError,
)
from inkflow.domain.ports.style_errors import StyleValidationError
from inkflow.domain.ports.timeline_errors import TimelineExtractionError
from inkflow.domain.ports.vector_store import EntityType
from inkflow.domain.ports.world_errors import WorldExtractionError
from inkflow.domain.services.extraction_service import ExtractionService

router = APIRouter(prefix="/api/v1", tags=["提取"])


def _parse_id(project_id: str) -> uuid.UUID:
    """安全解析项目 ID 字符串，支持 UUID 格式和整数格式（同 F1-F13）。"""
    try:
        return uuid.UUID(project_id)
    except ValueError:
        try:
            return uuid.UUID(int=int(project_id))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail="项目不存在") from err


def _get_svc(db: AsyncSession) -> ExtractionService:
    """获取 ExtractionService 实例（方便 mock）。"""
    return get_extraction_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.4）。"""
    try:
        return await coro
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ExtractionServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except StyleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except OutlineNameConflictError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LLMRequestError as err:
        raise HTTPException(status_code=500, detail="LLM 调用失败，请稍后重试") from err
    except (
        CharacterExtractionError,
        WorldExtractionError,
        OutlineGenerationError,
        ForeshadowingExtractionError,
        TimelineExtractionError,
    ) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except (RAGUnavailableError, VectorStoreError, ExtractionRunError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class ReindexBody(BaseModel):
    """全量重建索引请求体 — entity_types 缺省 = 全部 5 种（spec §3.3）。"""

    entity_types: list[EntityType] | None = None


class RetrieveBody(BaseModel):
    """语义检索请求体（spec §3.3）— top_k/min_score 边界校验（§9 API 测试）。"""

    query: str
    entity_types: list[EntityType] | None = None
    top_k: int = 10
    min_score: float = 0.0

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        """验证查询文本：去空白后非空且不超过 500 字符。"""
        stripped = v.strip()
        if not stripped:
            raise ValueError("查询文本不能为空")
        if len(stripped) > 500:
            raise ValueError("查询文本不能超过 500 个字符")
        return stripped

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, v: int) -> int:
        """验证返回结果上限：1-50 闭区间。"""
        if not 1 <= v <= 50:
            raise ValueError("top_k 必须在 1-50 之间")
        return v

    @field_validator("min_score")
    @classmethod
    def validate_min_score(cls, v: float) -> float:
        """验证相关度阈值：0.0-1.0 闭区间。"""
        if not 0.0 <= v <= 1.0:
            raise ValueError("min_score 必须在 0-1 之间")
        return v


# ── 统一提取（扁平路径）────────────────────────────────────


@router.post("/extract")
async def extract(
    request: ExtractionRequest,
    db: AsyncSession = Depends(get_db),
):
    """统一提取（spec §3.2）— 6 种类型分发 + 增量判定 + 可选 RAG 索引。

    请求体即 ExtractionRequest（DTO 自带校验: text/chapter_ids 互斥、超限、
    非法 UUID/type → Pydantic 422）；业务校验（类型不匹配、章节不存在/跨项目、
    风格输入约束）由服务层抛错误子类 → 422。
    """
    svc = _get_svc(db)
    result = await _run_service(svc.extract(request))
    return result.model_dump(mode="json")


# ── runs 查询 / 向量动作（嵌套项目路径）────────────────────


@router.get("/projects/{project_id}/extractions/runs")
async def list_extraction_runs(
    project_id: str,
    type: ExtractionType | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """增量状态列表（spec §3.3）— 分页 + 可选类型过滤，按 run_at DESC。"""
    pid = _parse_id(project_id)
    svc = _get_svc(db)
    items, total = await _run_service(svc.list_runs(pid, type=type, offset=offset, limit=limit))
    return {
        "items": [r.model_dump(mode="json") for r in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/projects/{project_id}/vector/reindex")
async def reindex_project(
    project_id: str,
    data: ReindexBody | None = None,
    db: AsyncSession = Depends(get_db),
):
    """全量重建索引（spec §3.3）— entity_types 缺省 = 全部 5 种（幂等 upsert）。"""
    pid = _parse_id(project_id)
    svc = _get_svc(db)
    result = await _run_service(svc.reindex(pid, entity_types=data.entity_types if data else None))
    return result.model_dump(mode="json")


@router.post("/projects/{project_id}/vector/retrieve")
async def retrieve_entities(
    project_id: str,
    data: RetrieveBody,
    db: AsyncSession = Depends(get_db),
):
    """语义检索（spec §3.3）— 参数透传 vector_store + {items} 信封。"""
    pid = _parse_id(project_id)
    svc = _get_svc(db)
    items = await _run_service(
        svc.retrieve(
            data.query,
            project_id=pid,
            entity_types=data.entity_types,
            top_k=data.top_k,
            min_score=data.min_score,
        )
    )
    return {"items": [dataclasses.asdict(item) for item in items]}
