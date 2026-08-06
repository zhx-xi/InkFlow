"""ProviderConfig 仓储端口 — Provider 注册表持久化契约.

ProviderConfigRepositoryProtocol 定义 ProviderConfig 的 CRUD 操作与内置
seed 插入（seed_builtin_providers），基础设施层（SQLite / mock / memory）
实现此 Protocol。仓储层方法入参用 int（与 ORM 层一致）。

依据: specs/f19-gui/spec.md §8.2。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.provider_config import ProviderConfig


class ProviderConfigRepositoryProtocol(Protocol):
    """Provider 注册表仓储端口.

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10/F11/F12）。
    """

    async def add(self, pc: ProviderConfig) -> ProviderConfig:
        """插入新 Provider（id 由 DB 自增分配；name 唯一冲突 → IntegrityError 冒泡）."""
        ...

    async def get(self, provider_config_id: int) -> ProviderConfig | None:
        """按主键查询 Provider；不存在返回 None."""
        ...

    async def get_by_name(self, name: str) -> ProviderConfig | None:
        """按名称精确查询 Provider（同名唯一检查用）；不存在返回 None."""
        ...

    async def get_by_builtin_key(self, builtin_key: str) -> ProviderConfig | None:
        """按内置 key 精确查询 Provider（用户行 builtin_key=None 不命中）；不存在返回 None."""
        ...

    async def list(self, search: str | None = None) -> builtins.list[ProviderConfig]:
        """列出全部 Provider，按 name 升序；search 对 name icontains 子串过滤."""
        ...

    async def update(self, pc: ProviderConfig) -> ProviderConfig:
        """按 id 全量更新 Provider 字段（updated_at 刷新，created_at 保留）；不存在 → ValueError."""
        ...

    async def delete(self, provider_config_id: int) -> bool:
        """物理删除 Provider；不存在返回 False."""
        ...

    async def seed_builtin_providers(self) -> int:
        """幂等插入内置 4 provider（openai/deepseek/zhipu/ollama）；返回本次实际插入数."""
        ...
