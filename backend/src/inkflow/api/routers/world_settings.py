"""F10 世界观管理 REST API — 8 个端点：条目 CRUD + 类别汇总 + AI 提取。

端点风格沿用 F2/F9（spec §3.1）：创建/列表/类别汇总嵌套项目路径
（/projects/{project_id}/world-settings...），详情/更新/删除扁平
（/world-settings/...）。AI 提取为 POST /world-settings/extract，
注册在 /world-settings/{setting_id} 之前避免路径歧义（同 F9 characters.py）。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 WorldService —— 单元测试通过
`@patch("inkflow.api.routers.world_settings.get_world_service")` 来
mock 服务层（同 F9 characters.py 模式）。

错误映射（spec §3.4 异常映射表）:
- 无效 UUID / 资源不存在（Service 返回 None）→ 404
- WorldServiceError 子类（同名条目）→ 422（消息即 detail）
- WorldNotFoundError / ProjectNotFoundError → 404
- WorldExtractionError → 500「世界观提取失败: LLM 输出无法解析，请重试」
- LLMRequestError → 500「LLM 调用失败，请稍后重试」

依据: specs/f10-world-service/spec.md §3/§5/§7。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_world_service
from inkflow.domain.models.world import (
    WorldExtractRequest,
    WorldUpdate,
    _validate_category,
    _validate_content,
    _validate_name,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.world_errors import (
    ProjectNotFoundError,
    WorldExtractionError,
    WorldNotFoundError,
    WorldServiceError,
)
from inkflow.domain.services.world_service import WorldService

router = APIRouter(prefix="/api/v1", tags=["世界观"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 F9 characters.py）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail=detail) from err


def _get_svc(db: AsyncSession) -> WorldService:
    """获取 WorldService 实例（方便 mock）。"""
    return get_world_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.4）。"""
    try:
        return await coro
    except WorldServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except WorldNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except WorldExtractionError as err:
        raise HTTPException(
            status_code=500, detail="世界观提取失败: LLM 输出无法解析，请重试"
        ) from err
    except LLMRequestError as err:
        raise HTTPException(status_code=500, detail="LLM 调用失败，请稍后重试") from err


class WorldSettingCreateBody(BaseModel):
    """创建世界观条目请求体 — project_id 取自路径参数，不在 body（spec §3.1）。"""

    name: str
    category: str = ""
    content: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证条目名：去空白后非空且不超过 50 字符."""
        return _validate_name(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """验证类别：去空白且不超过 50 字符（空串 = 未分类，允许）."""
        return _validate_category(v)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """验证内容：不超过 20000 字符."""
        return _validate_content(v)


# ── AI 提取（先于 /world-settings/{setting_id} 注册，避免路径歧义）──


@router.post("/world-settings/extract")
async def extract_world_settings(
    request: WorldExtractRequest,
    db: AsyncSession = Depends(get_db),
):
    """AI 提取世界观条目（spec §3.1/§5.1）。"""
    svc = _get_svc(db)
    result = await _run_service(svc.extract(request))
    return result.model_dump(mode="json")


# ── WorldSetting ───────────────────────────────────────────────


@router.post("/projects/{project_id}/world-settings", status_code=201)
async def create_world_setting(
    project_id: str,
    data: WorldSettingCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建世界观条目（spec §3.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    setting = await _run_service(svc.create_setting(pid, data.name, data.category, data.content))
    return setting.model_dump(mode="json")


@router.get("/projects/{project_id}/world-settings")
async def list_world_settings(
    project_id: str,
    search: str | None = Query(None),
    category: str | None = Query(None),
    sort_by: str = Query("updated_at"),
    sort_desc: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内条目列表（搜索 + 类别过滤 + 分页，spec §3.1/§6.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    items, total = await _run_service(
        svc.list_settings(
            pid,
            search=search,
            category=category,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )
    )
    return {
        "items": [s.model_dump(mode="json") for s in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/projects/{project_id}/world-settings/categories")
async def list_world_categories(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取项目内类别汇总（含条目数，spec §3.3/§6.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    categories = await _run_service(svc.list_categories(pid))
    items = [{"category": c, "count": n} for c, n in categories]
    return {"items": items, "total": len(items)}


@router.get("/world-settings/{setting_id}")
async def get_world_setting(
    setting_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取条目详情（spec §3.1）。"""
    sid = _parse_id(setting_id, detail="世界观条目不存在")
    svc = _get_svc(db)
    setting = await _run_service(svc.get_setting(sid))
    if setting is None:
        raise HTTPException(status_code=404, detail="世界观条目不存在")
    return setting.model_dump(mode="json")


@router.patch("/world-settings/{setting_id}")
async def update_world_setting(
    setting_id: str,
    data: WorldUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新条目（WorldUpdate 全可选，exclude_unset 语义）。"""
    sid = _parse_id(setting_id, detail="世界观条目不存在")
    svc = _get_svc(db)
    setting = await _run_service(svc.update_setting(sid, data))
    if setting is None:
        raise HTTPException(status_code=404, detail="世界观条目不存在")
    return setting.model_dump(mode="json")


@router.delete("/world-settings/{setting_id}", status_code=204)
async def delete_world_setting(
    setting_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除条目（默认软删除，?force=true 硬删除，spec §3.1/§7）。"""
    sid = _parse_id(setting_id, detail="世界观条目不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_setting(sid, force=force))
    if not ok:
        raise HTTPException(status_code=404, detail="世界观条目不存在")


@router.post("/world-settings/{setting_id}/restore")
async def restore_world_setting(
    setting_id: str,
    db: AsyncSession = Depends(get_db),
):
    """恢复软删除条目（spec §3.1/§7）。"""
    sid = _parse_id(setting_id, detail="世界观条目不存在")
    svc = _get_svc(db)
    setting = await _run_service(svc.restore_setting(sid))
    if setting is None:
        raise HTTPException(status_code=404, detail="世界观条目不存在")
    return setting.model_dump(mode="json")
