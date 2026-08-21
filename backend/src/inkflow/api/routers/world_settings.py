"""F10 世界观管理 REST API — 14 个端点：条目 CRUD + 类别汇总 + 分类 CRUD（v1.2）+ AI 提取。

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

from inkflow.api.deps import get_copy_service, get_db, get_world_service
from inkflow.domain.models.copy import WorldCopyRequest
from inkflow.domain.models.world import (
    WorldExtractRequest,
    WorldUpdate,
    _validate_category,
    _validate_category_name,
    _validate_content,
    _validate_name,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.world_errors import (
    CopyRootNotFoundError,
    CopySourceNotFoundError,
    ProjectNotFoundError,
    WorldExtractionError,
    WorldNotFoundError,
    WorldServiceError,
)
from inkflow.domain.services.copy_service import WorldCopyService
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


def _get_copy_svc(db: AsyncSession) -> WorldCopyService:
    """获取 WorldCopyService 实例（方便 mock）。"""
    return get_copy_service(db)


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
    except CopySourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CopyRootNotFoundError as e:
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
    parent_id: uuid.UUID | None = None  # ← F35 新增（None = 顶层）

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


class WorldCategoryCreateBody(BaseModel):
    """创建世界观分类请求体（spec §3.1，v1.2）."""

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证分类名：去空白后非空且不超过 50 字符."""
        return _validate_category_name(v)


class WorldCategoryUpdateBody(BaseModel):
    """重命名世界观分类请求体（spec §3.1，v1.2）."""

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证分类名：去空白后非空且不超过 50 字符."""
        return _validate_category_name(v)


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


@router.post("/projects/{target_project_id}/world-settings/copy")
async def copy_world_settings(
    target_project_id: str,
    request: WorldCopyRequest,
    db: AsyncSession = Depends(get_db),
):
    """跨书复制源项目世界观到目标项目（spec §3.1；Q2=A 缺省整棵 / Q3=B 全局图）。"""
    tpid = _parse_id(target_project_id, detail="项目不存在")
    if request.self_only and request.root_setting_id is None:
        raise HTTPException(status_code=422, detail="仅本体复制必须指定复制起点")
    svc = _get_copy_svc(db)
    result = await _run_service(
        svc.copy(
            request.source_project_id,
            tpid,
            request.root_setting_id,
            self_only=request.self_only,
        )
    )
    return result.model_dump(mode="json")


# ── WorldSetting ───────────────────────────────────────────────


@router.post("/projects/{project_id}/world-settings", status_code=201)
async def create_world_setting(
    project_id: str,
    data: WorldSettingCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建世界观条目（spec §3.2；#567 根条目单例：一个项目一个根）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    # F35: parent_id 缺省不传键（既有测试契约）；提供时按关键字透传
    if data.parent_id is None:
        # #567 单例校验：parent_id 为空（根条目）时该项目已有根 → 422
        if await svc.has_root_setting(pid):
            raise HTTPException(status_code=422, detail="该项目已存在世界观根条目")
        setting = await _run_service(
            svc.create_setting(pid, data.name, data.category, data.content)
        )
    else:
        setting = await _run_service(
            svc.create_setting(
                pid, data.name, data.category, data.content, parent_id=data.parent_id
            )
        )
    return setting.model_dump(mode="json")


@router.get("/projects/{project_id}/world-settings")
async def list_world_settings(
    project_id: str,
    search: str | None = Query(None),
    category: str | None = Query(None),
    parent_id: str | None = Query(None),
    sort_by: str = Query("updated_at"),
    sort_desc: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取项目内条目列表（搜索 + 类别过滤 + F35 parent_id 过滤 + 分页，spec §3.1/§6.2）。"""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    # F35 Q3=A: ?parent_id=none → 顶层过滤；?parent_id=<uuid> → 直接子级；缺省 → 全量。
    # 参数形状按测试契约精确传递（缺省不含 parent_id/top_level_only 键）。
    list_kwargs: dict[str, Any] = {
        "search": search,
        "category": category,
        "sort_by": sort_by,
        "sort_desc": sort_desc,
        "offset": offset,
        "limit": limit,
    }
    if parent_id is not None:
        if parent_id.lower() == "none":
            list_kwargs["parent_id"] = None
            list_kwargs["top_level_only"] = True
        else:
            list_kwargs["parent_id"] = _parse_id(parent_id, detail="世界观条目不存在")
    items, total = await _run_service(svc.list_settings(pid, **list_kwargs))
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


@router.get("/world-settings/{setting_id}/ancestors")
async def get_world_setting_ancestors(
    setting_id: str,
    db: AsyncSession = Depends(get_db),
):
    """祖先链（含自身，自身在前；面包屑，spec §3.1）。"""
    sid = _parse_id(setting_id, detail="世界观条目不存在")
    svc = _get_svc(db)
    chain = await _run_service(svc.list_ancestors(sid))
    if chain is None:
        raise HTTPException(status_code=404, detail="世界观条目不存在")
    return {"items": [s.model_dump(mode="json") for s in chain], "total": len(chain)}


@router.get("/world-settings/{setting_id}/descendants")
async def get_world_setting_descendants(
    setting_id: str,
    db: AsyncSession = Depends(get_db),
):
    """子树（含自身，层序；复制/级联删除用，spec §3.1）。"""
    sid = _parse_id(setting_id, detail="世界观条目不存在")
    svc = _get_svc(db)
    subtree = await _run_service(svc.list_descendants(sid))
    if subtree is None:
        raise HTTPException(status_code=404, detail="世界观条目不存在")
    return {"items": [s.model_dump(mode="json") for s in subtree], "total": len(subtree)}


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
    cascade: bool = Query(False),
    reparent_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """删除条目（v1.1 默认真删，无 force 参数；F35: ?cascade=true 级联真删 |
    ?reparent_to=<id> 子改挂，spec §5.5）。"""
    sid = _parse_id(setting_id, detail="世界观条目不存在")
    svc = _get_svc(db)
    reparent_uuid: uuid.UUID | None = None
    if reparent_to is not None:
        reparent_uuid = _parse_id(reparent_to, detail="世界观条目不存在")
    # F35: 参数形状按测试契约精确传递（缺省不含 cascade/reparent_to 键）
    if cascade:
        ok = await _run_service(svc.delete_setting(sid, cascade=True, reparent_to=None))
    elif reparent_uuid is not None:
        ok = await _run_service(svc.delete_setting(sid, cascade=False, reparent_to=reparent_uuid))
    else:
        ok = await _run_service(svc.delete_setting(sid))
    if not ok:
        raise HTTPException(status_code=404, detail="世界观条目不存在")


# ── WorldCategory（v1.2，issue #389）────────────────────────────


@router.post("/projects/{project_id}/world-categories", status_code=201)
async def create_world_category(
    project_id: str,
    data: WorldCategoryCreateBody,
    db: AsyncSession = Depends(get_db),
):
    """创建世界观分类（spec §3.1，v1.2；同名 → 422）."""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    category = await _run_service(svc.create_category(pid, data.name))
    return category.model_dump(mode="json")


@router.get("/projects/{project_id}/world-categories")
async def list_project_world_categories(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取项目内分类列表（含条目数，spec §3.1/§6.1，v1.2）."""
    pid = _parse_id(project_id, detail="项目不存在")
    svc = _get_svc(db)
    categories = await _run_service(svc.list_world_categories(pid))
    items = [{"id": str(c.id), "name": c.name, "count": n} for c, n in categories]
    return {"items": items, "total": len(items)}


@router.patch("/world-categories/{category_id}")
async def rename_world_category(
    category_id: str,
    data: WorldCategoryUpdateBody,
    db: AsyncSession = Depends(get_db),
):
    """重命名分类（反向同步条目 category，spec §6.1 D2=A，v1.2）."""
    cid = _parse_id(category_id, detail="世界观分类不存在")
    svc = _get_svc(db)
    category = await _run_service(svc.rename_category(cid, data.name))
    if category is None:
        raise HTTPException(status_code=404, detail="世界观分类不存在")
    return category.model_dump(mode="json")


@router.delete("/world-categories/{category_id}", status_code=204)
async def delete_world_category(
    category_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除分类（反向清空条目 category，spec §6.1 D2=A，v1.2）."""
    cid = _parse_id(category_id, detail="世界观分类不存在")
    svc = _get_svc(db)
    ok = await _run_service(svc.delete_category(cid))
    if not ok:
        raise HTTPException(status_code=404, detail="世界观分类不存在")
