"""#821: resolve_llm_credentials 非空 key 契约 + 空 key 兜底契约 RED 测试.

打包版缺陷（#821）: named model 的 provider key 在 frozen 下 _load_stored_key 返回
None → get_provider_config 抛 ValueError → resolve_llm_credentials 静默返回
（model, "", ""）→ harness.py:113 `if api_key:` 为 False → ChatOpenAI 未注入
openai_api_key → "Missing credentials"。dev 各路径全对，打包版运行时差异。

本文件锁定契约（决策已拍板）:
1. key 已配置时返回非空 api_key（防回归锁定）。
2. named model 的 provider key 不可用时，必须回退到有 key 的 provider 或抛
   HTTPException(422)，绝不返回空 api_key 传进 ChatOpenAI。

patch 注入点: resolve_llm_credentials 在函数体内惰性
`from inkflow.domain.services.model_resolution import resolve_model` 和
`from inkflow.infrastructure.llm.provider_config import (... get_provider_config ...)`，
因此 patch 目标 = 源模块属性（import 时已绑定到模块，惰性 import 读模块属性）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

MODEL = "deepseek/deepseek-v4-flash"


def _keyed_config(provider: str, key: str, model: str) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider,
        api_key=key,
        base_url="https://example.test/v1",
        default_model=model,
        models=[model.split("/")[-1]],
    )


class TestResolveLLMCredentialsReturnsKey:
    """契约 1: named model provider key 已配置 → 返回非空 api_key（锁定防回归）。"""

    def test_key_configured_returns_nonempty_key(self):
        from inkflow.api._llm_resolver import resolve_llm_credentials

        def _side_effect(provider):
            assert provider == "deepseek"
            return _keyed_config("deepseek", "test-api-key-value", MODEL)

        with (
            patch("inkflow.domain.services.model_resolution.resolve_model", return_value=MODEL),
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                side_effect=_side_effect,
            ),
        ):
            model, api_key, base_url = resolve_llm_credentials(MODEL)

        assert model == MODEL
        assert api_key == "test-api-key-value"
        assert base_url == "https://example.test/v1"


class TestResolveLLMCredentialsFallsBackOnMissingKey:
    """契约 2: named model provider key 不可用 → 回退有 key 的 provider 或 422，绝不为空。"""

    def test_named_model_key_unavailable_falls_back_to_keyed_provider(self):
        """deepseek key 缺失（打包版路径）→ 回退到 ollama（有 key/provider）。"""
        from inkflow.api._llm_resolver import resolve_llm_credentials

        def _side_effect(provider):
            if provider == "ollama":
                return _keyed_config("ollama", "ollama", "ollama/llama3.1")
            raise ValueError(f"API key not configured for provider: {provider}")

        with (
            patch("inkflow.domain.services.model_resolution.resolve_model", return_value=MODEL),
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                side_effect=_side_effect,
            ),
        ):
            _, api_key, _ = resolve_llm_credentials(MODEL)

        # 绝不返回空 api_key：回退到 ollama 或抛错，不能静默空 key
        assert api_key, "resolve_llm_credentials must not return an empty api_key"

    def test_no_key_anywhere_raises_422(self):
        """全部 provider 无 key → 必须抛 422，绝不返回空 api_key 传进 ChatOpenAI。"""
        from inkflow.api._llm_resolver import resolve_llm_credentials

        def _side_effect(provider):
            raise ValueError(f"API key not configured for provider: {provider}")

        with (
            patch("inkflow.domain.services.model_resolution.resolve_model", return_value=MODEL),
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                side_effect=_side_effect,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            resolve_llm_credentials(MODEL)

        assert exc_info.value.status_code == 422
