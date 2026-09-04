"""#735 D2 自动设置全局默认模型 — ProviderConfigService.create 契约测试（RED）。

D2（用户拍板）: 首个含 >=1 个 chat 模型的 provider 新增时，若全局默认为空 →
自动设为该模型（config.llm_default_model 落盘，镜像 config.py PATCH 逻辑）。

设计契约:
- ``ProviderConfigService.__init__(*, repository, config=...)`` 接受可写全局
  默认的 config 对象（生产 = inkflow.core.config 单例；测试注入替身以隔离）。
- ``create`` 落库后：若 ``config.llm_default_model`` 为空（""/None）且
  ``data.models`` 含 >=1 个 ``type=="chat"`` 模型 →
  写入 ``f"{data.name}/{首个chat模型.id}"`` 并调 ``save_config_json``。
- 全局默认已配置 / 无 chat 模型 → 不写入、不调 save_config_json。

RED 预期失败形态:
- ``ProviderConfigService(repository=..., config=...)`` → TypeError
  （当前构造仅 repository，无 config 参数）。
- create 后 config.llm_default_model 未被写入（功能缺失）→ AssertionError。

依据: references/model-resolution-and-context-sources.md（D2 分级）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from inkflow.domain.models.provider_config import ProviderConfigCreate, ProviderModel
from inkflow.domain.ports.provider_config_repository import ProviderConfigRepositoryProtocol
from inkflow.domain.services.provider_config_service import ProviderConfigService


class _FakeConfig:
    """可写全局默认的 config 替身（llm_default_model 可读可写；data_dir 供落盘）。"""

    def __init__(self, llm_default_model: str = "") -> None:
        self.llm_default_model = llm_default_model
        self.data_dir = Path(".")


def _mock_repo() -> MagicMock:
    """Mock ProviderConfigRepositoryProtocol — add 透传实体，get_by_name 未命中。"""
    repo = MagicMock(spec=ProviderConfigRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda pc: pc)
    repo.get_by_name = AsyncMock(return_value=None)
    return repo


def _make_service(mock_repo: MagicMock, config_obj: _FakeConfig) -> ProviderConfigService:
    """按新契约构造服务（config 注入；RED 期该 kwargs 不存在 → TypeError）。"""
    return ProviderConfigService(repository=mock_repo, config=config_obj)


class TestCreateAutoSetsGlobalDefault:
    """D2: 新增含 chat 模型 provider 且全局默认空 → 自动设为该模型。"""

    async def test_auto_sets_when_global_empty_and_has_chat_model(self) -> None:
        """含 chat 模型 + 全局默认空 → 写入 f"{provider}/{首个chat模型}" + 落盘。"""
        config_obj = _FakeConfig(llm_default_model="")
        svc = _make_service(_mock_repo(), config_obj)
        with patch(
            "inkflow.domain.services.provider_config_service.save_config_json"
        ) as mock_save:
            await svc.create(
                ProviderConfigCreate(
                    name="openai",
                    models=[
                        ProviderModel(id="gpt-4o", type="chat", roles=["writing"]),
                        ProviderModel(id="text-embedding-3", type="embedding"),
                    ],
                )
            )
        assert config_obj.llm_default_model == "openai/gpt-4o"
        mock_save.assert_called_once_with(
            config_obj.data_dir, {"llm_default_model": "openai/gpt-4o"}
        )

    async def test_no_auto_set_when_global_configured(self) -> None:
        """全局默认已配置 → 不覆盖，不调 save_config_json。"""
        config_obj = _FakeConfig(llm_default_model="deepseek/deepseek-v4-flash")
        svc = _make_service(_mock_repo(), config_obj)
        with patch(
            "inkflow.domain.services.provider_config_service.save_config_json"
        ) as mock_save:
            await svc.create(
                ProviderConfigCreate(
                    name="openai",
                    models=[ProviderModel(id="gpt-4o", type="chat")],
                )
            )
        assert config_obj.llm_default_model == "deepseek/deepseek-v4-flash"
        mock_save.assert_not_called()

    async def test_no_auto_set_when_no_chat_model(self) -> None:
        """仅 embedding 模型 → 不写入（需 >=1 个 chat 模型）。"""
        config_obj = _FakeConfig(llm_default_model="")
        svc = _make_service(_mock_repo(), config_obj)
        with patch(
            "inkflow.domain.services.provider_config_service.save_config_json"
        ) as mock_save:
            await svc.create(
                ProviderConfigCreate(
                    name="openai",
                    models=[ProviderModel(id="text-embedding-3", type="embedding")],
                )
            )
        assert config_obj.llm_default_model == ""
        mock_save.assert_not_called()
