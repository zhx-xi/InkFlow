"""SQLite Provider 注册表仓储 — 实现 ProviderConfigRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm）按项目惯例放在本仓储层
（参照 foreshadowing_repo.py / timeline_repo.py）。

语义（spec §8.2/§8.5）:
- name 唯一（UNIQUE 约束）: 重复插入同名 → IntegrityError 冒泡，
  服务层先经 get_by_name 检查给出友好 422 文案
- models 列存 ``[ProviderModel.model_dump()]``（dict 列表，JSON 列）；
  读回 ``[ProviderModel.model_validate(m) for m in (orm.models or [])]``
- list 按 name 升序；search 对 name icontains 子串过滤
- update 按 id 全量更新（updated_at 刷新为 now(UTC)，created_at 保留）；
  不存在 → ValueError（镜像 F13 仓储惯例）
- delete 不存在 → False
- seed_builtin_providers 幂等插入内置 4 provider（openai/deepseek/zhipu/
  ollama），base_url 复用 infrastructure.llm.provider_config 的
  _PROVIDER_BASE_URLS（deepseek=https://api.deepseek.com/v1 等）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/provider_config_repository.py 一致）。
"""

from __future__ import annotations

import builtins
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
from inkflow.infrastructure.database.models.provider_config import ProviderConfigORM
from inkflow.infrastructure.llm.provider_config import (
    _BUILTIN_PROVIDERS,
    _PROVIDER_BASE_URLS,
)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _orm_to_domain(orm: ProviderConfigORM) -> ProviderConfig:
    """Provider ORM 行 → 领域实体（models dict 列表 → ProviderModel 列表）."""
    return ProviderConfig(
        id=orm.id,
        name=orm.name,
        builtin_key=orm.builtin_key,
        base_url=orm.base_url,
        default_model=orm.default_model,
        models=[ProviderModel.model_validate(m) for m in (orm.models or [])],
        max_retries=orm.max_retries,
        timeout=orm.timeout,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: ProviderConfig) -> ProviderConfigORM:
    """Provider 领域实体 → ORM 行（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
    return ProviderConfigORM(
        name=domain.name,
        builtin_key=domain.builtin_key,
        base_url=domain.base_url,
        default_model=domain.default_model,
        models=[m.model_dump() for m in domain.models],
        max_retries=domain.max_retries,
        timeout=domain.timeout,
    )


class SQLiteProviderConfigRepository:
    """SQLite Provider 注册表仓储 — 实现 ProviderConfigRepositoryProtocol."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, pc: ProviderConfig) -> ProviderConfig:
        """插入新 Provider（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
        orm = _domain_to_orm(pc)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, provider_config_id: int) -> ProviderConfig | None:
        """按主键查询 Provider."""
        stmt = select(ProviderConfigORM).where(ProviderConfigORM.id == provider_config_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_name(self, name: str) -> ProviderConfig | None:
        """按名称精确查询 Provider（同名唯一检查用）."""
        stmt = select(ProviderConfigORM).where(ProviderConfigORM.name == name)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_builtin_key(self, builtin_key: str) -> ProviderConfig | None:
        """按内置 key 精确查询 Provider（#126 A1：seed 判重 / 回填依据）."""
        stmt = select(ProviderConfigORM).where(ProviderConfigORM.builtin_key == builtin_key)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(self, search: str | None = None) -> builtins.list[ProviderConfig]:
        """列出全部 Provider，按 name 升序；search 对 name icontains 子串过滤."""
        stmt = select(ProviderConfigORM).order_by(ProviderConfigORM.name.asc())
        if search:
            stmt = stmt.where(ProviderConfigORM.name.icontains(search))
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def update(self, pc: ProviderConfig) -> ProviderConfig:
        """按 id 全量更新 Provider 字段（updated_at 刷新，created_at 保留）.

        不存在 → ValueError（镜像 F13 仓储惯例，router 层转 404）。
        """
        orm = await self._session.get(ProviderConfigORM, pc.id)
        if orm is None:
            raise ValueError(f"Provider config not found: {pc.id}")
        orm.name = pc.name
        orm.builtin_key = pc.builtin_key
        orm.base_url = pc.base_url
        orm.default_model = pc.default_model
        orm.models = [m.model_dump() for m in pc.models]
        orm.max_retries = pc.max_retries
        orm.timeout = pc.timeout
        orm.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def delete(self, provider_config_id: int) -> bool:
        """物理删除 Provider；不存在返回 False."""
        orm = await self._session.get(ProviderConfigORM, provider_config_id)
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def seed_builtin_providers(self) -> int:
        """幂等插入内置 4 provider（openai/deepseek/zhipu/ollama）.

        #126 A1：按 builtin_key 判重（key = name）；内置改名后重启不复活。
        按 key 未命中但按 name 命中内置名（旧库回填场景）→ 回填 builtin_key（更新非插入，
        不计入返回的插入数）。base_url 复用 _PROVIDER_BASE_URLS；models 初始为空。
        返回本次实际插入条数。
        """
        inserted = 0
        for name in _BUILTIN_PROVIDERS:
            key = name  # 内置 seed 的 builtin_key 恒等于 name
            if await self.get_by_builtin_key(key) is not None:
                continue
            legacy = await self.get_by_name(name)  # 旧库回填：builtin_key NULL 但 name 命中内置名
            if legacy is not None:
                legacy.builtin_key = key
                await self.update(legacy)  # 回填（更新非插入，inserted 不 +1）
                continue
            await self.add(
                ProviderConfig(
                    name=name,
                    base_url=_PROVIDER_BASE_URLS.get(name),
                    builtin_key=key,
                )
            )
            inserted += 1
        return inserted
