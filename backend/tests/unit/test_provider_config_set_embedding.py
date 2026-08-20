"""#525/#526 RED 契约 — ProviderConfigService.set_embedding_model 服务层语义。

方法尚未实现（GREEN 批新增）→ RED 形态: AttributeError（方法不存在）。

契约（唯一激活语义，Issue #525）:
- 目标 provider 的 model_id 条目 type → "embedding"（原 chat 时 id/roles 保留）
- 其余所有 provider（含同 provider 其他模型）type=="embedding" → "chat"
- provider 名不存在 → ProviderConfigNotFoundError（404 语义）
- model_id 不在该 provider models → ProviderConfigNotFoundError
- 返回更新后的目标 ProviderConfig（含 embedding type）

Mock 策略（镜像 test_provider_config_service.py）: MagicMock(spec=Protocol)
repo 注入；list() 返回固定 ProviderConfig 集合、update() 记录调用、
get_by_name 模拟目标 provider 查询。

依据: Issue #525 向量模型选择器；任务书 s8a red-backend-task.md 文件 2。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
from inkflow.domain.ports.provider_config_errors import ProviderConfigNotFoundError
from inkflow.domain.ports.provider_config_repository import (
    ProviderConfigRepositoryProtocol,
)
from inkflow.domain.services.provider_config_service import ProviderConfigService


def _provider(provider_id: int, name: str, models: list[ProviderModel]) -> ProviderConfig:
    """构造测试用 ProviderConfig 实体（id 固定便于区分 provider）。"""
    return ProviderConfig(id=provider_id, name=name, models=models)


def _updated(repo: MagicMock, name: str) -> ProviderConfig:
    """从 repo.update 调用记录取指定 provider 的更新实体（未命中 → 断言失败）。"""
    for call in repo.update.await_args_list:
        pc = call.args[0]
        if pc.name == name:
            return pc
    raise AssertionError(f"repo.update 未收到 name={name} 的 ProviderConfig")


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock ProviderConfigRepositoryProtocol — list/update/get_by_name 可覆盖。"""
    repo = MagicMock(spec=ProviderConfigRepositoryProtocol)
    repo.list = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda pc: pc)
    repo.get_by_name = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def service(mock_repo: MagicMock) -> ProviderConfigService:
    """被测服务实例（Mock repo 注入，ADR-015）。"""
    return ProviderConfigService(repository=mock_repo)


class TestSetEmbeddingModel:
    """set_embedding_model — 唯一激活语义 / 错误路径 / 返回值。"""

    async def test_set_target_model_to_embedding(self, service, mock_repo):
        """目标模型原 type=chat → 更新后 type=embedding（id/roles 保留）。"""
        zhipu = _provider(
            1,
            "zhipu",
            [ProviderModel(id="embedding-3", type="chat", roles=["writing"])],
        )
        openai = _provider(2, "openai", [ProviderModel(id="text-embedding-3", type="chat")])
        mock_repo.list.return_value = [zhipu, openai]
        mock_repo.get_by_name.return_value = zhipu

        await service.set_embedding_model("zhipu", "embedding-3")

        updated = _updated(mock_repo, "zhipu")
        target = next(m for m in updated.models if m.id == "embedding-3")
        assert target.type == "embedding"
        assert target.roles == ["writing"]  # 原字段保留

    async def test_demote_other_embedding_models(self, service, mock_repo):
        """其他 provider 的 embedding 模型 → chat（唯一激活）。"""
        zhipu = _provider(1, "zhipu", [ProviderModel(id="embedding-3", type="chat")])
        openai = _provider(2, "openai", [ProviderModel(id="text-embedding-3", type="embedding")])
        mock_repo.list.return_value = [zhipu, openai]
        mock_repo.get_by_name.return_value = zhipu

        await service.set_embedding_model("zhipu", "embedding-3")

        updated_openai = _updated(mock_repo, "openai")
        demoted = next(m for m in updated_openai.models if m.id == "text-embedding-3")
        assert demoted.type == "chat"

    async def test_same_provider_other_embedding_demoted(self, service, mock_repo):
        """同 provider 内其他 embedding 模型 → chat。"""
        zhipu = _provider(
            1,
            "zhipu",
            [
                ProviderModel(id="embedding-3", type="chat"),
                ProviderModel(id="embedding-2", type="embedding"),
            ],
        )
        mock_repo.list.return_value = [zhipu]
        mock_repo.get_by_name.return_value = zhipu

        await service.set_embedding_model("zhipu", "embedding-3")

        updated = _updated(mock_repo, "zhipu")
        assert next(m for m in updated.models if m.id == "embedding-3").type == "embedding"
        assert next(m for m in updated.models if m.id == "embedding-2").type == "chat"

    async def test_idempotent_when_already_embedding(self, service, mock_repo):
        """目标已 embedding → 无异常、仍走 update，其他 embedding 仍被降级。"""
        zhipu = _provider(
            1,
            "zhipu",
            [
                ProviderModel(id="embedding-3", type="embedding"),
                ProviderModel(id="embedding-2", type="embedding"),
            ],
        )
        mock_repo.list.return_value = [zhipu]
        mock_repo.get_by_name.return_value = zhipu

        await service.set_embedding_model("zhipu", "embedding-3")

        updated = _updated(mock_repo, "zhipu")
        assert next(m for m in updated.models if m.id == "embedding-3").type == "embedding"
        assert next(m for m in updated.models if m.id == "embedding-2").type == "chat"

    async def test_provider_not_found(self, service, mock_repo):
        """list 中无该 provider → ProviderConfigNotFoundError，且不落库。"""
        mock_repo.list.return_value = [_provider(2, "openai", [])]
        mock_repo.get_by_name.return_value = None

        with pytest.raises(ProviderConfigNotFoundError, match="Provider 不存在"):
            await service.set_embedding_model("ghost", "embedding-3")
        mock_repo.update.assert_not_awaited()

    async def test_model_not_found(self, service, mock_repo):
        """provider 存在但 model_id 不在其 models → ProviderConfigNotFoundError。"""
        zhipu = _provider(1, "zhipu", [ProviderModel(id="glm-4", type="chat")])
        mock_repo.list.return_value = [zhipu]
        mock_repo.get_by_name.return_value = zhipu

        with pytest.raises(ProviderConfigNotFoundError):
            await service.set_embedding_model("zhipu", "embedding-3")
        mock_repo.update.assert_not_awaited()

    async def test_returns_updated_target(self, service, mock_repo):
        """返回更新后的目标 ProviderConfig（含 embedding type）。"""
        zhipu = _provider(1, "zhipu", [ProviderModel(id="embedding-3", type="chat")])
        mock_repo.list.return_value = [zhipu]
        mock_repo.get_by_name.return_value = zhipu

        result = await service.set_embedding_model("zhipu", "embedding-3")

        assert result.name == "zhipu"
        assert next(m for m in result.models if m.id == "embedding-3").type == "embedding"
