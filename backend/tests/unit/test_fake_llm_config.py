"""config/provider_config fake 分支契约测试（S0，ADR-047，契约⑤）。

INKFLOW_LLM_BASE_URL 注入 → config.llm_base_url → get_provider_config("fake")
→ LangChainLLMClient 走 fake base_url。

RED：config 无 llm_base_url / e2e_llm_mode 字段（AttributeError）、get_provider_config
无 fake 分支（ValueError）。GREEN 后全部通过。本文件位于 tests/unit/，
其覆盖计入 coverage-backend（fake 分支新行必须被覆盖，否则门禁掉线）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from inkflow.core.config import InkFlowConfig
from inkflow.infrastructure.llm import langchain_client as lc
from inkflow.infrastructure.llm import provider_config as pc
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig


class TestConfigFakeFields:
    """config 应暴露 llm_base_url / e2e_llm_mode 字段（env_prefix INKFLOW_）。"""

    def test_config_has_llm_base_url_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INKFLOW_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
        cfg = InkFlowConfig(_env_file=None)
        assert cfg.llm_base_url == "http://127.0.0.1:9999/v1"

    def test_config_has_e2e_llm_mode_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INKFLOW_E2E_LLM_MODE", "real")
        cfg = InkFlowConfig(_env_file=None)
        assert cfg.e2e_llm_mode == "real"

    def test_e2e_llm_mode_default_is_fake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INKFLOW_E2E_LLM_MODE", raising=False)
        cfg = InkFlowConfig(_env_file=None)
        assert cfg.e2e_llm_mode == "fake"

    def test_llm_base_url_default_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INKFLOW_LLM_BASE_URL", raising=False)
        cfg = InkFlowConfig(_env_file=None)
        assert cfg.llm_base_url == ""


class TestProviderConfigFakeBranch:
    """get_provider_config("fake") 应短接并回放 config.llm_base_url + 占位 key。"""

    def test_fake_not_seeded_as_builtin(self) -> None:
        """fake 不应进 _BUILTIN_PROVIDERS（seed_builtin_providers 遍历它会把
        fake 当 GUI 内建 provider 持久化）；fake 解析走 get_provider_config 短接。"""
        assert "fake" not in pc._BUILTIN_PROVIDERS

    def test_fake_provider_uses_llm_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pc.config, "llm_base_url", "http://127.0.0.1:9999/v1")
        # 真实 get_provider_config 短接（RED：无 fake 分支 → ValueError → FAIL）
        cfg = pc.get_provider_config("fake")
        assert isinstance(cfg, LLMProviderConfig)
        assert cfg.provider == "fake"
        assert cfg.base_url == "http://127.0.0.1:9999/v1"
        assert cfg.api_key  # 占位 key 非空（fake 无真实 key，避免 ChatOpenAI 拿到空串）
        assert cfg.default_model  # 默认模型非空，避免 parse 失败

    def test_fake_without_base_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未配置 INKFLOW_LLM_BASE_URL 时 fake provider 应抛 ValueError（无 key）。"""
        monkeypatch.setattr(pc.config, "llm_base_url", "")
        with pytest.raises(ValueError):
            pc.get_provider_config("fake")


class TestLangChainClientFakeBaseUrl:
    """LangChainLLMClient 经 fake provider 应把 openai_api_base 指向 fake server。"""

    def test_client_uses_fake_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pc.config, "llm_base_url", "http://127.0.0.1:9999/v1")
        # 真实装配路径：get_provider_config("fake") → provider_cfg.base_url → ChatOpenAI
        provider_cfg = pc.get_provider_config("fake")
        with patch.object(lc, "ChatOpenAI") as mock_chat:
            LangChainLLMClient()._get_chat_model(provider_cfg, model_name="fake-model")
        kwargs = mock_chat.call_args[1]
        assert kwargs["openai_api_base"] == "http://127.0.0.1:9999/v1"
        assert kwargs["openai_api_key"]  # 占位 key 传递到 ChatOpenAI

    def test_chat_async_uses_fake_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """chat()（async）走 fake provider → ChatOpenAI openai_api_base 指向 fake。"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from inkflow.domain.ports.llm_client import ChatMessage

        monkeypatch.setattr(pc.config, "llm_base_url", "http://127.0.0.1:9999/v1")
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = MagicMock(content="ok", response_metadata={})
        with patch.object(lc, "ChatOpenAI") as mock_chat:
            mock_chat.return_value = mock_model
            client = LangChainLLMClient()
            asyncio.run(
                client.chat([ChatMessage(role="user", content="hi")], model="fake/fake-model")
            )
        kwargs = mock_chat.call_args[1]
        assert kwargs["openai_api_base"] == "http://127.0.0.1:9999/v1"
        assert kwargs["openai_api_key"]
