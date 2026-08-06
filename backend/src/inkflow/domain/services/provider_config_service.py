"""ProviderConfig 业务服务 — Provider 注册表 CRUD + 内置 seed 委托.

职责（spec §8.2/§8.5）:
- Provider CRUD 编排：委托 ProviderConfigRepositoryProtocol
- 同名唯一性校验（422）: create 前 / update 改名时经 repo.get_by_name 检查，
  命中 → ProviderConfigNameConflictError
- 资源不存在（404 语义）: get/update/delete 目标缺失 → ProviderConfigNotFoundError
- update 为 exclude_unset 浅合并（同 F1/F13）: None 值 = 不修改，予以剔除；
  仅 name 变更时查重；updated_at 刷新为 now(UTC)，created_at 保留
- seed_builtin_providers 委托 repo（幂等由 repo 保证，返回插入数）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）。
"""

from __future__ import annotations

import builtins
import logging
from datetime import UTC, datetime

from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
)
from inkflow.domain.ports.provider_config_errors import (
    ProviderConfigNameConflictError,
    ProviderConfigNotFoundError,
)
from inkflow.domain.ports.provider_config_repository import ProviderConfigRepositoryProtocol

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


class ProviderConfigService:
    """Provider 注册表业务服务 — CRUD + 内置 seed.

    Args:
        repository: Provider 注册表仓储端口.
    """

    def __init__(self, *, repository: ProviderConfigRepositoryProtocol) -> None:
        self._repo = repository

    async def create(self, data: ProviderConfigCreate) -> ProviderConfig:
        """创建 Provider（同名冲突 → 422；时间戳由服务层填充）."""
        existing = await self._repo.get_by_name(data.name)
        if existing is not None:
            raise ProviderConfigNameConflictError()
        now = _utcnow()
        pc = ProviderConfig(
            id=None,
            name=data.name,
            base_url=data.base_url,
            default_model=data.default_model,
            models=data.models,
            max_retries=data.max_retries,
            timeout=data.timeout,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建 Provider: name=%s", data.name)
        return await self._repo.add(pc)

    async def get(self, provider_config_id: int) -> ProviderConfig:
        """按主键获取 Provider；不存在 → ProviderConfigNotFoundError（404）."""
        pc = await self._repo.get(provider_config_id)
        if pc is None:
            raise ProviderConfigNotFoundError()
        return pc

    async def get_by_name(self, name: str) -> ProviderConfig | None:
        """按名称查询 Provider（同名唯一检查用）；不存在返回 None."""
        return await self._repo.get_by_name(name)

    async def list(self) -> builtins.list[ProviderConfig]:
        """列出全部 Provider（按 name 升序，委托 repo）."""
        return await self._repo.list()

    async def update(self, provider_config_id: int, data: ProviderConfigUpdate) -> ProviderConfig:
        """部分更新 Provider（exclude_unset 浅合并，同 F1/F13）.

        None 值 = 不修改（与未传入等价，合并前剔除）；name 变更时查重
        （命中其他 id → 422）；updated_at 刷新，created_at 保留。
        """
        existing = await self._repo.get(provider_config_id)
        if existing is None:
            raise ProviderConfigNotFoundError()
        # 直接取已校验的字段值（避免 model_dump 将嵌套 ProviderModel 摊平为 dict）
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "name" in updates and updates["name"] != existing.name:
            dup = await self._repo.get_by_name(updates["name"])
            if dup is not None and dup.id != existing.id:
                raise ProviderConfigNameConflictError()
        merged = existing.model_copy(update=updates)
        merged.updated_at = _utcnow()
        logger.info("更新 Provider: provider_config_id=%s", provider_config_id)
        return await self._repo.update(merged)

    async def delete(self, provider_config_id: int) -> None:
        """删除 Provider；不存在 → ProviderConfigNotFoundError（404）."""
        if not await self._repo.delete(provider_config_id):
            raise ProviderConfigNotFoundError()

    async def seed_builtin_providers(self) -> int:
        """幂等插入内置 4 provider（幂等由 repo 保证，返回插入数）."""
        return await self._repo.seed_builtin_providers()
