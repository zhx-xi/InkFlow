"""#659 检索索引重建异步端点：POST /api/v1/index/rebuild + GET /api/v1/index/rebuild/status.

端点契约（tests/api/test_index_rebuild_api.py 锁定）：
- POST /api/v1/index/rebuild — body {project_ids: list[str] | null, scope: fulltext|vector|both}
  → 202 {task_id, status: 'running'}；scope 非法枚举 → 422（Pydantic）；未配 embedding →
  422；重建进行中 → 409；project 不存在 → 404；其余异常 → 500。
- GET /api/v1/index/rebuild/status?task_id=<id> → 200 进度 DTO；task_id 未注册 → 404。

模块级零参工厂 `_get_svc` 镜像 search.py 模式（测试经 patch 注入 mock service）。
"""

from __future__ import annotations

import uuid
from typing import Literal, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inkflow.api.deps import get_index_rebuild_service
from inkflow.core.database import (
    async_session_factory,  # noqa: F401  # 保留：API 测试 patch 此模块属性
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.services.index_rebuild_service import IndexRebuildService

router = APIRouter(prefix="/api/v1/index", tags=["Index"])


class RebuildRequest(BaseModel):
    """索引重建请求体：project_ids 为空/缺省 → 全部项目；scope 三选一."""

    project_ids: list[str] | None = None
    scope: Literal["fulltext", "vector", "both"] = "both"


async def _get_svc() -> IndexRebuildService:
    """获取 IndexRebuildService 实例（零参模块级工厂，镜像 search.py `_get_svc` 模式）.

    生产路径经 deps.get_index_rebuild_service 装配（自建会话，与端点同源
    async_session_factory）；测试经 `patch("inkflow.api.routers.index._get_svc")` 注入 mock。
    """
    return await get_index_rebuild_service()


def _resolve_project_ids(raw: list[str] | None) -> list[uuid.UUID] | None:
    """UUID 字符串列表 → uuid.UUID 列表；None → None（全部项目）."""
    if raw is None:
        return None
    return [uuid.UUID(s) for s in raw]


@router.post("/rebuild", status_code=202)
async def rebuild_endpoint(body: RebuildRequest) -> dict:
    """启动统一异步索引重建（202 异步语义）：预校验失败立即 404/409/422.

    project_ids 缺省/None → 全部项目（service 层逐项目校验）；scope 缺省 → 'both'。
    返回 202 + {task_id, status: 'running'}（后台任务 fire-and-forget，进度经
    GET /rebuild/status 轮询）。
    """
    try:
        result = await (await _get_svc()).start_rebuild(
            project_ids=_resolve_project_ids(body.project_ids),
            scope=body.scope,
        )
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        if str(e) == "未配置 embedding 模型":
            raise HTTPException(status_code=422, detail=str(e)) from e
        if str(e) == "索引重建进行中":
            raise HTTPException(status_code=409, detail=str(e)) from e
        raise HTTPException(status_code=500, detail="Internal server error") from e
    return cast(dict, result)


@router.get("/rebuild/status")
async def status_endpoint(task_id: str) -> dict:
    """查询索引重建任务进度（200 DTO）；task_id 未注册 → 404."""
    status = await (await _get_svc()).get_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="task not found")
    return cast(dict, status)
