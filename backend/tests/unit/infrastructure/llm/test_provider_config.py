"""Provider 配置单元测试 — Issue #86 修复契约 2/3（audit 路由 + zhipu 注册）。"""

from __future__ import annotations

import pytest

from inkflow.core.config import config
from inkflow.infrastructure.llm.provider_config import (
    _BUILTIN_PROVIDERS,
    LLMProviderConfig,
    get_provider_config,
    parse_model_string,
)


class TestModelRoutingAuditFix:
    """契约 2（P2-1）：audit 路由不再指向已移除的 anthropic provider。"""

    def test_audit_routing_points_to_deepseek(self):
        """audit 任务应精确路由到 deepseek/deepseek-chat。"""
        assert config.model_routing["audit"] == "deepseek/deepseek-chat"

    def test_audit_routing_provider_is_registered(self):
        """audit 路由的 provider 前缀必须存在于内建注册表（ADR-005v2）。"""
        provider, _ = parse_model_string(config.model_routing["audit"])
        assert provider in _BUILTIN_PROVIDERS
        # 显式传 api_key 验证该 provider 可解析出完整配置（不依赖环境变量）
        cfg = get_provider_config(provider, api_key="test-key")
        assert isinstance(cfg, LLMProviderConfig)
        assert cfg.provider == provider


class TestZhipuProviderRegistration:
    """契约 3（P2-2）：智谱（zhipu）Provider 注册。"""

    def test_config_has_zhipu_api_key_field(self):
        """config 应包含 zhipu_api_key 字段（默认空字符串）。"""
        assert hasattr(config, "zhipu_api_key")
        assert config.zhipu_api_key == ""

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

    def test_zhipu_without_api_key_raises(self):
        """未配置 zhipu API Key 时应抛 ValueError（契约钉住，修复前后均成立）。"""
        with pytest.raises(ValueError, match="zhipu"):
            get_provider_config("zhipu")
