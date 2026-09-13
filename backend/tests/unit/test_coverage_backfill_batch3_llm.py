"""Batch 3 coverage backfill: LLM provider, prompts, and redaction."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent_run import AgentStep, AgentToolCall
from inkflow.domain.ports.llm_errors import TemplateNotFoundError, TemplateRenderError
from inkflow.domain.ports.prompt_template import PromptTemplate
from inkflow.infrastructure.llm import prompt_manager as prompt_manager_mod
from inkflow.infrastructure.llm import provider_config as provider_config_mod
from inkflow.infrastructure.llm import redact as redact_mod
from inkflow.infrastructure.llm.key_manager import APIKeyManager
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager


def _registry_miss(monkeypatch) -> None:
    service = MagicMock()
    service.get_by_name = AsyncMock(return_value=None)
    monkeypatch.setattr(
        provider_config_mod,
        "ProviderConfigService",
        lambda repository=None: service,
    )


def test_provider_config_plaintext_key_fallback(tmp_path: Path, monkeypatch) -> None:
    """Public provider resolution falls back to a plaintext provider key file."""
    monkeypatch.setattr(provider_config_mod.config, "data_dir", tmp_path)
    monkeypatch.setattr(provider_config_mod.config, "secret_key", "")
    monkeypatch.delenv("INKFLOW_CUSTOM_API_KEY", raising=False)
    monkeypatch.setattr(APIKeyManager, "get_key", lambda self, provider: None)
    _registry_miss(monkeypatch)
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    (keys_dir / "custom.key").write_text("plaintext-key", encoding="utf-8")

    cfg = provider_config_mod.get_provider_config("custom")

    assert cfg.api_key == "plaintext-key"


def test_provider_config_encrypted_json_fallback(tmp_path: Path, monkeypatch) -> None:
    """Public provider resolution falls back to explicit encrypted JSON decrypt."""
    monkeypatch.setattr(provider_config_mod.config, "data_dir", tmp_path)
    monkeypatch.setattr(provider_config_mod.config, "secret_key", "")
    monkeypatch.delenv("INKFLOW_CUSTOM_API_KEY", raising=False)
    monkeypatch.setattr(APIKeyManager, "get_key", lambda self, provider: None)
    _registry_miss(monkeypatch)
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    (keys_dir / "custom.key").write_text("", encoding="utf-8")
    encrypted = APIKeyManager("", keys_dir).encrypt("custom", "json-key")
    (keys_dir / "custom.json").write_text(json.dumps(encrypted), encoding="utf-8")

    cfg = provider_config_mod.get_provider_config("custom")

    assert cfg.api_key == "json-key"

    (keys_dir / "custom.json").write_text(
        json.dumps(APIKeyManager("", keys_dir).encrypt("custom", "")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="API key not configured"):
        provider_config_mod.get_provider_config("custom")


def test_provider_config_key_manager_exception_is_ignored(tmp_path: Path, monkeypatch) -> None:
    """Public provider resolution ignores APIKeyManager construction/read failures."""
    monkeypatch.setattr(provider_config_mod.config, "data_dir", tmp_path)
    monkeypatch.delenv("INKFLOW_CUSTOM_API_KEY", raising=False)

    def _raise(self, provider: str) -> str | None:
        raise RuntimeError("key manager down")

    monkeypatch.setattr(APIKeyManager, "get_key", _raise)

    with pytest.raises(ValueError, match="API key not configured"):
        provider_config_mod.get_provider_config("custom")


def test_prompt_manager_reports_invalid_yaml(tmp_path: Path) -> None:
    """Public load wraps YAML parser failures in TemplateRenderError."""
    (tmp_path / "broken.yaml").write_text("name: [unterminated\n", encoding="utf-8")
    manager = LangChainPromptManager(templates_dir=tmp_path)

    with pytest.raises(TemplateRenderError, match="broken"):
        manager.load("broken")


def test_prompt_manager_empty_listing_and_zh_fallback(tmp_path: Path, monkeypatch) -> None:
    """Public prompt manager returns [] for a missing locale and falls back to zh."""
    monkeypatch.setattr(prompt_manager_mod, "resolve_locale", lambda locale: "missing")
    manager = LangChainPromptManager()

    assert manager.list_templates() == []
    template = manager.load("outline_generate")
    assert template.name


def test_prompt_manager_loads_existing_zh_without_fallback() -> None:
    """Public prompt loading returns directly for an existing zh template."""
    manager = LangChainPromptManager()

    template = manager.load("outline_generate", locale="zh")

    assert template.name


def test_prompt_manager_missing_fallback_still_reports_not_found(
    tmp_path: Path, monkeypatch
) -> None:
    """Public prompt loading reports not-found when neither locale has the template."""
    monkeypatch.setattr(prompt_manager_mod, "resolve_locale", lambda locale: "missing")
    manager = LangChainPromptManager()

    with pytest.raises(TemplateNotFoundError):
        manager.load("definitely_missing_template")


def test_prompt_render_without_system_prompt(tmp_path: Path) -> None:
    """Public rendering emits only the human message when system prompt is empty."""
    manager = LangChainPromptManager(templates_dir=tmp_path)
    template = PromptTemplate(
        name="human-only",
        description="",
        system_prompt="",
        human_prompt="Hello {name}",
        variables=["name"],
    )

    rendered = manager.render(template, {"name": "Ada"})

    assert rendered.messages == [{"role": "user", "content": "Hello Ada"}]


def test_redact_step_scrubs_known_keys_in_nested_lists(monkeypatch) -> None:
    """Public redact_step replaces known keys inside nested list arguments."""
    monkeypatch.setattr(redact_mod, "load_known_keys", lambda: ["known-secret"])
    step = AgentStep(
        index=0,
        message_content="known-secret",
        tool_calls=[
            AgentToolCall(
                step_index=0,
                tool_name="tool",
                arguments={"nested": ["known-secret", {"again": "known-secret"}], "number": 7},
                result="known-secret",
            )
        ],
    )

    redacted = redact_mod.redact_step(step)

    assert "known-secret" not in redacted.message_content
    assert "known-secret" not in str(redacted.tool_calls[0].arguments)
    assert "known-secret" not in redacted.tool_calls[0].result
    assert "****" in redacted.message_content


@pytest.mark.asyncio
async def test_provider_registry_running_loop_returns_result(monkeypatch) -> None:
    """Public resolution in an active event loop completes the registry bridge."""
    import importlib

    database_mod = importlib.import_module("inkflow.core.database")
    entry = SimpleNamespace(base_url="http://registry", default_model="registry-model", models=[])
    service = MagicMock()
    service.get_by_name = AsyncMock(return_value=entry)
    monkeypatch.setattr(
        provider_config_mod,
        "ProviderConfigService",
        lambda repository=None: service,
    )

    class _SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args) -> None:
            return None

    monkeypatch.setattr(database_mod, "async_session_factory", lambda: _SessionContext())

    cfg = provider_config_mod.get_provider_config("deepseek", api_key="explicit")

    assert cfg.base_url == "http://registry"
    assert cfg.default_model == "registry-model"


@pytest.mark.asyncio
async def test_provider_registry_running_loop_error_falls_back(monkeypatch) -> None:
    """Public resolution falls back when the registry bridge thread fails."""
    import importlib

    database_mod = importlib.import_module("inkflow.core.database")

    def _boom_factory():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(database_mod, "async_session_factory", _boom_factory)

    cfg = provider_config_mod.get_provider_config("deepseek", api_key="explicit")

    assert cfg.api_key == "explicit"
    assert cfg.base_url == "https://api.deepseek.com/v1"
