"""ProviderConfig 注册表 REST API — 5 个端点：列表/新建/详情/更新/删除.

端点风格沿用既有扁平路由（spec §8.3）：前缀 /api/v1/provider-configs。
各端点通过 Depends(get_db) 注入数据库 session，再调用模块级 _get_svc(db)
获取 ProviderConfigService。

错误映射（spec §8.3 契约）:
- id 缺失/非法格式（非整数）→ 404「Provider 不存在」（镜像 foreshadowings
  _parse_id 404 语义，非法格式不 422）
- ProviderConfigServiceError 子类（同名冲突）→ 422（消息即 detail）
- ProviderConfigNotFoundError → 404
- 内置 seed（openai/deepseek/zhipu/ollama）不可删除 → 409「内置 Provider 不可删除」
- key_saved 经 _get_key_manager().list_providers() 计算（镜像 settings.py
  工厂模式；仅此一处读取已存 key，禁止直接读 key 文件）
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_provider_config_service
from inkflow.core.config import config
from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
)
from inkflow.domain.ports.provider_config_errors import (
    ProviderConfigNotFoundError,
    ProviderConfigServiceError,
)
from inkflow.domain.services.provider_config_service import ProviderConfigService
from inkflow.infrastructure.llm.key_manager import APIKeyManager

router = APIRouter(prefix="/api/v1/provider-configs", tags=["ProviderConfigs"])

BUILTIN_NAMES = ("openai", "deepseek", "zhipu", "ollama")
"""内置 seed provider 名单（spec §8.2，2026-08-06 源码核实 _BUILTIN_PROVIDERS）—
DELETE 保护名单."""


def _parse_id(id_str: str, detail: str = "Provider 不存在") -> int:
    """安全解析 ID 字符串，仅接受整数格式；非法 → 404（镜像 foreshadowings 语义）."""
    try:
        return int(id_str)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=detail) from err


def _get_key_manager() -> APIKeyManager:
    """构造 APIKeyManager（镜像 api/routers/settings.py 工厂模式，key_saved 计算入口）."""
    return APIKeyManager(
        secret_key=config.secret_key,
        storage_dir=config.data_dir / "keys",
    )


def _get_svc(db: AsyncSession) -> ProviderConfigService:
    """获取 ProviderConfigService 实例（方便 mock）."""
    return get_provider_config_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码."""
    try:
        return await coro
    except ProviderConfigServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ProviderConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _to_response(pc: ProviderConfig, key_manager: APIKeyManager) -> dict:
    """实体 → 响应字典：契约 8 键 + max_retries/timeout + key_saved 标记."""
    data = pc.model_dump(mode="json")
    data["key_saved"] = pc.name in key_manager.list_providers()
    return data


@router.get("")
async def list_provider_configs(
    db: AsyncSession = Depends(get_db),
):
    """注册表列表（spec §8.3）— {items, total} 信封，每项含 key_saved + models."""
    svc = _get_svc(db)
    items = await _run_service(svc.list())
    key_manager = _get_key_manager()
    return {
        "items": [_to_response(pc, key_manager) for pc in items],
        "total": len(items),
    }


@router.post("", status_code=201)
async def create_provider_config(
    data: ProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """新建 Provider — 201 + 完整响应结构（含 key_saved）."""
    svc = _get_svc(db)
    pc = await _run_service(svc.create(data))
    return _to_response(pc, _get_key_manager())


@router.get("/{provider_config_id}")
async def get_provider_config(
    provider_config_id: str,
    db: AsyncSession = Depends(get_db),
):
    """详情（含 models + key_saved）；不存在/非法 id → 404."""
    pid = _parse_id(provider_config_id)
    svc = _get_svc(db)
    pc = await _run_service(svc.get(pid))
    return _to_response(pc, _get_key_manager())


@router.patch("/{provider_config_id}")
async def update_provider_config(
    provider_config_id: str,
    data: ProviderConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新（exclude_unset 浅合并；models 整体替换）；不存在 → 404."""
    pid = _parse_id(provider_config_id)
    svc = _get_svc(db)
    pc = await _run_service(svc.update(pid, data))
    return _to_response(pc, _get_key_manager())


@router.delete("/{provider_config_id}", status_code=204)
async def delete_provider_config(
    provider_config_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 Provider — 204 空响应；不存在 → 404；内置 seed → 409 保护."""
    pid = _parse_id(provider_config_id)
    svc = _get_svc(db)
    pc = await _run_service(svc.get(pid))
    if pc.name in BUILTIN_NAMES:
        raise HTTPException(status_code=409, detail="内置 Provider 不可删除")
    await _run_service(svc.delete(pid))
