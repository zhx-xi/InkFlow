"""#106 ProviderConfigService 单元测试 — Mock Repository（RED 批，P1 实体）。

覆盖 spec §8.5「ProviderConfig CRUD + 内置 seed」服务层（镜像 F13
test_foreshadowing_service.py 的 Mock 注入模式，ADR-015）:
- create：默认字段落库编排（id=None 由 repo 分配；created_at/updated_at 填充）；
  同名 → ProviderConfigNameConflictError（422 语义）
- get / get_by_name / list 委托 repo
- get/update/delete 不存在 → ProviderConfigNotFoundError（404 语义）
- update：exclude_unset 部分合并；name 变更查重（命中其他 id → 422）；
  None 值字段不应用（None = 不修改，同 F13）；updated_at 刷新
- delete 成功返回 None；seed_builtin_providers 委托 repo（幂等由 repo 保证）

依据: specs/f19-gui/spec.md §8.2①（service 模块）+ §8.5 测试策略「后端单元」。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块与类（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:

1. ``inkflow.domain.services.provider_config_service.ProviderConfigService``:
   - ``__init__(self, *, repository: ProviderConfigRepositoryProtocol) -> None``
   - ``async create(self, data: ProviderConfigCreate) -> ProviderConfig``:
     先 ``repo.get_by_name(data.name)`` 查重，命中 → ProviderConfigNameConflictError；
     构造 ``ProviderConfig(id=None, ...)``（id 由 repo 分配），
     ``created_at = updated_at = datetime.now(UTC)``；委托 ``repo.add``
   - ``async get(self, provider_config_id: int) -> ProviderConfig``:
     委托 ``repo.get``；None → ProviderConfigNotFoundError（404 语义）
   - ``async get_by_name(self, name: str) -> ProviderConfig | None``: 委托 repo
   - ``async list(self) -> builtins.list[ProviderConfig]``: 委托 repo
   - ``async update(self, provider_config_id: int, data: ProviderConfigUpdate)
     -> ProviderConfig``:
     先 ``repo.get``，None → ProviderConfigNotFoundError；
     ``model_dump(exclude_unset=True)`` 且剔除 None 值（None = 不修改）后
     ``model_copy`` 合并；仅当 name 变更（!= existing.name）时 ``get_by_name``
     查重（命中且 id 不同 → ProviderConfigNameConflictError）；
     ``updated_at = datetime.now(UTC)`` 刷新；委托 ``repo.update(merged)``
   - ``async delete(self, provider_config_id: int) -> None``:
     委托 ``repo.delete``；返回 False（不存在）→ ProviderConfigNotFoundError；
     成功返回 None
   - ``async seed_builtin_providers(self) -> int``:
     委托 ``repo.seed_builtin_providers()``（幂等插入内置 4 provider），返回插入数

2. ``inkflow.domain.ports.provider_config_repository.ProviderConfigRepositoryProtocol``
   （Protocol，方法签名同 repo 测试文件 docstring）:
   add / get / get_by_name / list(search=None) / update / delete /
   seed_builtin_providers

3. ``inkflow.domain.ports.provider_config_errors`` 错误类归属:
   - ``ProviderConfigServiceError(Exception)`` — 业务校验基类（API 映射 422）
   - ``ProviderConfigNotFoundError(Exception)`` — 404；默认消息精确为
     **"Provider 不存在"**（``__init__(message="Provider 不存在")``）
   - ``ProviderConfigNameConflictError(ProviderConfigServiceError)`` — 422；
     默认消息精确为 **"同名 Provider 已存在（provider 名称必须唯一）"**

4. 时间戳契约: create/update 填充的 created_at/updated_at 为时区感知
   datetime（datetime.now(UTC)）；测试断言 tzinfo 非空 + created_at ==
   updated_at（create）/ created_at 保留（update）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderModel,
)
from inkflow.domain.ports.provider_config_errors import (
    ProviderConfigNameConflictError,
    ProviderConfigNotFoundError,
)
from inkflow.domain.ports.provider_config_repository import ProviderConfigRepositoryProtocol
from inkflow.domain.services.provider_config_service import ProviderConfigService

TS = datetime(2026, 8, 1, 10, 0, 0)


def _config(provider_config_id: int, name: str, **kw) -> ProviderConfig:
    """构造测试用 ProviderConfig 实体（固定时间戳，便于断言）。"""
    return ProviderConfig(
        id=provider_config_id,
        name=name,
        created_at=TS,
        updated_at=TS,
        **kw,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock ProviderConfigRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=ProviderConfigRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda pc: pc)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda pc: pc)
    repo.delete = AsyncMock(return_value=True)
    repo.seed_builtin_providers = AsyncMock(return_value=4)
    return repo


@pytest.fixture
def service(mock_repo: MagicMock) -> ProviderConfigService:
    """被测服务实例（Mock repo 注入，ADR-015）。"""
    return ProviderConfigService(repository=mock_repo)


class TestCreate:
    """Provider 创建 — 默认字段编排 / 同名冲突。"""

    async def test_create_builds_entity_and_delegates(self, service, mock_repo):
        """create：查重（未命中）→ 构造实体（id=None、时间戳填充）→ repo.add."""
        saved = await service.create(
            ProviderConfigCreate(
                name="custom",
                base_url="http://localhost:8080/v1",
                default_model="local/model",
                models=[ProviderModel(id="m1", type="chat", roles=["writing"])],
                max_retries=5,
                timeout=60,
            )
        )
        mock_repo.get_by_name.assert_awaited_once_with("custom")
        mock_repo.add.assert_awaited_once()
        pc = mock_repo.add.await_args.args[0]
        assert pc.id is None  # id 由 repo 分配
        assert pc.name == "custom"
        assert pc.base_url == "http://localhost:8080/v1"
        assert pc.default_model == "local/model"
        assert pc.models == [ProviderModel(id="m1", type="chat", roles=["writing"])]
        assert pc.max_retries == 5
        assert pc.timeout == 60
        assert pc.created_at == pc.updated_at
        assert pc.created_at.tzinfo is not None  # datetime.now(UTC) 时区感知
        assert saved is pc  # 直接返回 repo.add 结果

    async def test_create_name_conflict_raises(self, service, mock_repo):
        """同名已存在 → ProviderConfigNameConflictError（422），且不落库。"""
        mock_repo.get_by_name.return_value = _config(1, "openai")
        with pytest.raises(ProviderConfigNameConflictError, match="同名 Provider 已存在"):
            await service.create(ProviderConfigCreate(name="openai"))
        mock_repo.add.assert_not_called()


class TestGet:
    """get / get_by_name 委托与 404 语义。"""

    async def test_get_found(self, service, mock_repo):
        """get 命中返回实体."""
        entity = _config(1, "openai")
        mock_repo.get.return_value = entity
        assert await service.get(1) is entity
        mock_repo.get.assert_awaited_once_with(1)

    async def test_get_missing_raises_not_found(self, service, mock_repo):
        """get 不存在 → ProviderConfigNotFoundError（消息「Provider 不存在」）。"""
        mock_repo.get.return_value = None
        with pytest.raises(ProviderConfigNotFoundError, match="Provider 不存在"):
            await service.get(999)

    async def test_get_by_name_delegates(self, service, mock_repo):
        """get_by_name 直接委托 repo（None 透传，不抛错）。"""
        entity = _config(1, "openai")
        mock_repo.get_by_name.return_value = entity
        assert await service.get_by_name("openai") is entity
        mock_repo.get_by_name.return_value = None
        assert await service.get_by_name("ghost") is None


class TestList:
    """list 委托。"""

    async def test_list_delegates(self, service, mock_repo):
        """list 直接返回 repo.list 结果."""
        items = [_config(1, "openai"), _config(2, "deepseek")]
        mock_repo.list.return_value = items
        assert await service.list() == items
        mock_repo.list.assert_awaited_once()


class TestUpdate:
    """update — 404 / 部分合并 / 改名查重 / None 不应用。"""

    async def test_update_missing_raises_not_found(self, service, mock_repo):
        """update 目标不存在 → ProviderConfigNotFoundError."""
        mock_repo.get.return_value = None
        with pytest.raises(ProviderConfigNotFoundError, match="Provider 不存在"):
            await service.update(999, ProviderConfigUpdate(base_url="https://x"))

    async def test_update_partial_merge_and_refresh_updated_at(self, service, mock_repo):
        """部分更新：仅传入字段合并；created_at 保留；updated_at 刷新为 now(UTC)."""
        existing = _config(7, "old", base_url="https://old.example/v1", default_model="m1")
        mock_repo.get.return_value = existing
        merged = await service.update(7, ProviderConfigUpdate(base_url="https://new.example/v1"))

        mock_repo.get.assert_awaited_once_with(7)
        mock_repo.update.assert_awaited_once()
        updated = mock_repo.update.await_args.args[0]
        assert updated.id == 7
        assert updated.name == "old"  # 未传字段不变
        assert updated.base_url == "https://new.example/v1"
        assert updated.default_model == "m1"
        assert updated.created_at == TS  # created_at 保留
        assert updated.updated_at.tzinfo is not None  # 刷新为 now(UTC)
        mock_repo.get_by_name.assert_not_called()  # name 未变，不查重
        assert merged is updated

    async def test_update_explicit_none_means_no_change(self, service, mock_repo):
        """显式 None 字段不应用（None = 不修改，同 F13）."""
        existing = _config(7, "old", base_url="https://old.example/v1")
        mock_repo.get.return_value = existing
        await service.update(7, ProviderConfigUpdate(base_url=None))
        updated = mock_repo.update.await_args.args[0]
        assert updated.base_url == "https://old.example/v1"  # 未被置 None

    async def test_update_rename_conflict_raises(self, service, mock_repo):
        """改名命中其他 Provider → ProviderConfigNameConflictError，且不落库。"""
        existing = _config(7, "old")
        mock_repo.get.return_value = existing
        mock_repo.get_by_name.return_value = _config(8, "taken")  # 其他 id 已占用
        with pytest.raises(ProviderConfigNameConflictError, match="同名 Provider 已存在"):
            await service.update(7, ProviderConfigUpdate(name="taken"))
        mock_repo.update.assert_not_called()

    async def test_update_rename_to_own_name_no_conflict(self, service, mock_repo):
        """name 未变化（与现有值相同）→ 不查重、直接更新。"""
        existing = _config(7, "old")
        mock_repo.get.return_value = existing
        await service.update(7, ProviderConfigUpdate(name="old"))
        mock_repo.get_by_name.assert_not_called()
        mock_repo.update.assert_awaited_once()


class TestDelete:
    """delete — 404 语义 / 成功返回 None。"""

    async def test_delete_missing_raises_not_found(self, service, mock_repo):
        """repo.delete 返回 False（不存在）→ ProviderConfigNotFoundError."""
        mock_repo.delete.return_value = False
        with pytest.raises(ProviderConfigNotFoundError, match="Provider 不存在"):
            await service.delete(999)
        mock_repo.delete.assert_awaited_once_with(999)

    async def test_delete_success_returns_none(self, service, mock_repo):
        """删除成功返回 None."""
        mock_repo.delete.return_value = True
        assert await service.delete(1) is None


class TestSeed:
    """内置 seed 4 provider 初始化逻辑（§8.2①）委托 repo。"""

    async def test_seed_builtin_providers_delegates(self, service, mock_repo):
        """seed_builtin_providers 委托 repo 并透传插入数（4）."""
        assert await service.seed_builtin_providers() == 4
        mock_repo.seed_builtin_providers.assert_awaited_once()

    async def test_seed_idempotent_passthrough(self, service, mock_repo):
        """幂等性由 repo 保证：第二次调用返回 0，服务层透传。"""
        mock_repo.seed_builtin_providers.return_value = 0
        assert await service.seed_builtin_providers() == 0
