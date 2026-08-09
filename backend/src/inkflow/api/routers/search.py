"""F22 全文搜索 REST API — GET /api/v1/search + POST /api/v1/search/rebuild。

端点总览（spec §3.1-§3.3）:
- GET  /api/v1/search          — 全文搜索（q / project_id|project_ids /
  types / mode / limit / offset）
- POST /api/v1/search/rebuild  — 手动全量重建索引（project_id 可选，
  缺省 = 全部项目）

模块契约（tests/api/test_search_api.py 锁定）:
- `router = APIRouter(prefix="/api/v1/search", tags=["Search"])`——GET 端点
  路径为空串 ""，POST rebuild 路径为 "/rebuild"
- `_get_svc() -> SearchService`：零参模块级工厂（镜像 settings.py
  `_get_key_manager()` 模式）——测试经
  `patch("inkflow.api.routers.search._get_svc")` 注入 mock service；
  生产路径经 deps.get_search_service 装配（vector_store=None 懒装配：
  semantic 空结果、keyword 不受 embedding 配置影响，spec §5.8）
- 端点经 `Depends(get_db)` 注入 session 后再调用 `_get_svc()` 获取服务

错误映射（spec §3.3 异常映射表）:
- 任一 project_id 不存在（ProjectNotFoundError，F9 character_errors）→
  404，消息即 detail（如 "Project not found: <id>"）
- q / types / mode / limit 校验失败 → 422 Pydantic 校验错误（detail 为 list）
- project_id 与 project_ids 同时缺省 → 422 精确 detail
  "project_id or project_ids required"（v1.1 Q3）
- 其余异常（DB 异常等）→ 500 通用 detail "Internal server error"
  （内部异常消息不得泄漏，ADR-012/016）

依据: specs/f22-search-service/spec.md §3/§9/§13。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_search_service
from inkflow.core.database import async_session_factory
from inkflow.domain.models.search import SearchQuery, SearchResponse
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.services.search_service import SearchService

router = APIRouter(prefix="/api/v1/search", tags=["Search"])


def _get_svc() -> SearchService:
    """获取 SearchService 实例（F22 全文搜索，spec §8.1）.

    零参模块级工厂（镜像 settings.py `_get_key_manager()` 模式）：测试经
    `patch("inkflow.api.routers.search._get_svc")` 注入 mock service；
    生产路径经 deps.get_search_service 装配（自建会话，与端点
    `Depends(get_db)` 同源 async_session_factory）。
    """
    return get_search_service(async_session_factory())


def _resolve_project_ids(project_id: str | None, project_ids: str | None) -> list[str]:
    """project_id 单值 / project_ids 逗号分隔 → 原始字符串列表（spec §3.1 Q3）.

    同时缺省 → 422 精确 detail "project_id or project_ids required"
    （v1.1 Q3：必填其一；router 层显式校验，不触达 service）。UUID 格式
    校验交给 SearchQuery（Pydantic 422，detail 为 list）。
    """
    if project_id is None and project_ids is None:
        raise HTTPException(status_code=422, detail="project_id or project_ids required")
    raw = project_id if project_id is not None else project_ids
    return [part.strip() for part in raw.split(",") if part.strip()]


def _resolve_types(types: str | None) -> list[str] | None:
    """逗号分隔 SearchEntityType 原始值列表；空/缺省 → None（spec §2.2）.

    枚举值校验交给 SearchQuery（Pydantic 422，detail 为 list）。
    """
    if not types:
        return None
    return [part.strip() for part in types.split(",") if part.strip()]


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）.

    404: ProjectNotFoundError（消息即 detail，如 "Project not found: <id>"）。
    500: 其余异常 → 通用 detail "Internal server error"，内部消息不泄漏。
    """
    try:
        return await coro
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("")
async def search_endpoint(
    q: str = Query(..., min_length=1, max_length=100),
    project_id: str | None = None,
    project_ids: str | None = None,
    types: str | None = None,
    mode: str = "keyword",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """全文搜索（只读幂等，spec §3.1/§5）.

    组装 SearchQuery（q 原样 / project_ids 单值包装或逗号分隔解析 /
    types 空 → None / mode → SearchMode 枚举）后调用 service.search；
    响应 SearchResponse 直接返回（FastAPI 自动序列化）。
    """
    try:
        query = SearchQuery(
            q=q,
            project_ids=_resolve_project_ids(project_id, project_ids),
            types=_resolve_types(types),
            mode=mode,
            limit=limit,
            offset=offset,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_context=False)) from e
    svc = _get_svc()
    return await _run_service(svc.search(query))


@router.post("/rebuild")
async def rebuild_endpoint(
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动全量重建索引（v1.2 新增，承接 CLI --rebuild，spec §3.1/M13）.

    project_id 缺省 = 全部项目（service.rebuild(None)）；传 = 单项目
    （service.rebuild(<UUID>.int)，spec §8.2 project_ids 为 list[int] 口径）。
    返回 {"rebuilt_at": str, "project_id": str | None}。
    """
    pid = uuid.UUID(project_id).int if project_id else None
    svc = _get_svc()
    return await _run_service(svc.rebuild(pid))
