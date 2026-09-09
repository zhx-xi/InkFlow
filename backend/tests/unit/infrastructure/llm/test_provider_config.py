"""Provider 配置单元测试 — Issue #86 修复契约 2/3（audit 路由 + zhipu 注册）。

⚠️ 环境隔离契约（#951）：任何裸调 get_provider_config(provider) 且期望
「无 key → ValueError」的用例，必须确定性隔离全部 3 级 key 来源：
① env：monkeypatch.delenv("INKFLOW_<PROVIDER>_API_KEY", raising=False)；
② _BUILTIN_PROVIDERS import 快照：monkeypatch.setitem(_BUILTIN_PROVIDERS,
   "<provider>", None)（进程启动前 env 已设时快照会冻结进 key，delenv 救不了）；
③ 真实 keys 目录：monkeypatch.setattr(provider_config, "_load_stored_key",
   lambda p: None)（或将 provider_config.config.data_dir 指向空 tmp 目录）。
缺一即可能在「存过 key 的开发机」上假阳性（#951）。
"""

from __future__ import annotations

import pytest

from inkflow.core.config import config
from inkflow.infrastructure.llm import provider_config
from inkflow.infrastructure.llm.provider_config import (
    _BUILTIN_PROVIDERS,
    LLMProviderConfig,
    get_provider_config,
)


class TestModelRoutingAuditFix:
    """契约 2（P2-1）迁移（#929）：audit task 键废止 → provider 键值对象。

    原「audit 指向 deepseek/deepseek-chat」由 provider 级 deepseek 默认承接；
    anthropic 不注册语义保留（deepseek/zhipu/openai 键在、anthropic 不在）。
    """

    def test_deepseek_routing_points_to_registered_chat_model(self):
        """deepseek provider 内置默认 = v4-flash（chat 型，#415 值保留）。"""
        entry = config.model_routing["deepseek"]
        assert entry.model == "deepseek-v4-flash"
        assert entry.type == "chat"

    def test_routing_provider_is_registered(self):
        """路由键必须是内建 provider（ADR-005v2；anthropic 不在——P2-1 语义保留）。"""
        assert "anthropic" not in config.model_routing
        assert "anthropic" not in _BUILTIN_PROVIDERS
        for provider in config.model_routing:
            assert provider in _BUILTIN_PROVIDERS
            # 显式传 api_key 验证该 provider 可解析出完整配置（不依赖环境变量）
            cfg = get_provider_config(provider, api_key="test-key")
            assert isinstance(cfg, LLMProviderConfig)
            assert cfg.provider == provider


class TestZhipuProviderRegistration:
    """契约 3（P2-2）：智谱（zhipu）Provider 注册。"""

    def test_config_has_zhipu_api_key_field(self):
        """config 应包含 zhipu_api_key 字段（默认为空字符串契约）。

        字段存在 + 默认为空是契约；活值可被 env/instance.env/config.json 注入，
        不做断言（#951）。
        """
        assert hasattr(config, "zhipu_api_key")
        assert type(config).model_fields["zhipu_api_key"].default == ""

    def test_zhipu_in_builtin_providers(self):
        """zhipu 应注册进 _BUILTIN_PROVIDERS。"""
        assert "zhipu" in _BUILTIN_PROVIDERS

    def test_zhipu_provider_config_with_explicit_api_key(self):
        """显式传 api_key 时应返回完整配置，且 base_url 非空、https 开头。"""
        cfg = get_provider_config("zhipu", api_key="test-key")
        assert isinstance(cfg, LLMProviderConfig)
        assert cfg.provider == "zhipu"
        assert cfg.base_url
        assert cfg.base_url.startswith("https://")

    def test_zhipu_without_api_key_raises(self, monkeypatch):
        """未配置 zhipu API Key 时应抛 ValueError（全链 3 级确定性隔离，#951）。"""
        monkeypatch.delenv("INKFLOW_ZHIPU_API_KEY", raising=False)
        monkeypatch.setitem(_BUILTIN_PROVIDERS, "zhipu", None)
        monkeypatch.setattr(provider_config, "_load_stored_key", lambda p: None)
        with pytest.raises(ValueError, match="zhipu"):
            get_provider_config("zhipu")

    def test_zhipu_raises_with_isolated_empty_keys_dir(self, monkeypatch, tmp_path):
        """隔离守护（#951）：data_dir 指向空 tmp 目录，真实第 3 级读取无 key → 仍必抛。

        与上一用例互补：不 patch _load_stored_key，证明按 data_dir 隔离同样确定性；
        若有人在真实 data_dir 存过 zhipu.key，本用例不受影响。
        """
        monkeypatch.setattr(provider_config.config, "data_dir", tmp_path)
        monkeypatch.delenv("INKFLOW_ZHIPU_API_KEY", raising=False)
        monkeypatch.setitem(_BUILTIN_PROVIDERS, "zhipu", None)
        with pytest.raises(ValueError, match="zhipu"):
            get_provider_config("zhipu")
