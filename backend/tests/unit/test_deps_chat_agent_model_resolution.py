"""#738 RED: chat agent model resolution when global default is empty.

Contracts (decision D3=A, full self-contained loop):
1. config.llm_default_model="" + a provider with a chat model and key exists
   -> get_chat_agent_service returns ChatAgentService whose build_deep_agent
      was called with a NON-empty api_key (resolved from registry fallback).
2. config.llm_default_model="" + no provider with a chat model + key
   -> get_chat_agent_service raises HTTPException(422) "未配置默认模型"
      (NOT a 500 Missing credentials).
3. resolve_model priority agent > project > global is preserved (consistency
   with the 8 services already using resolve_model).

RED expectation (current code):
- Current deps_chat_agent.py does NOT call resolve_model and does NOT
  fall back to registry. When config.llm_default_model="", it goes
  through parse_model_string("") -> ValueError -> except: pass -> api_key=""
  -> build_deep_agent(api_key="") -> ChatOpenAI -> Missing credentials -> 500.
- So: test 1 FAILS (api_key is empty, not non-empty).
- test 2 FAILS (no HTTPException raised; returns a service with empty api_key).
- test 3 FAILS (resolve_model not called).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from inkflow.api.routers.chat_stream import ChatStreamRequest
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import Tool

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
CHAPTER_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

EXPECTED_READER_NAMES = [
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
]


def _fake_tool(name: str) -> Tool:
    """Construct minimal Tool (spec.name assertable, func not executed)."""
    return Tool(
        spec=ToolSpec(name=name, description="", input_schema={}),
        func=MagicMock(),
    )


def _kwarg_or_positional(call, name: str, index: int, default=None):
    """Tolerantly extract mock call arg: keyword first, then positional."""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _get_chat_agent_service():
    """Lazily get get_chat_agent_service from deps."""
    from inkflow.api.deps import get_chat_agent_service

    return get_chat_agent_service


def _get_chat_agent_service_cls():
    """Lazily get ChatAgentService class."""
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

    return ChatAgentService


def _default_mocks(m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_rt, m_sd):
    """Set default return values on all service/tool factory mocks."""
    m_rt.return_value = [_fake_tool(name) for name in EXPECTED_READER_NAMES]
    m_sd.return_value = _fake_tool("save_draft")


class TestEmptyDefaultModelFallbackToRegistry:
    """#738: config.llm_default_model="" + provider with key -> resolve from registry."""

    @patch("inkflow.api.deps.build_deep_agent")
    @patch("inkflow.api.deps.build_save_draft_tool")
    @patch("inkflow.api.deps.build_reader_tools")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    @patch(
        "inkflow.infrastructure.llm.provider_config.get_provider_config"
    )
    @patch("inkflow.core.config.config")
    @pytest.mark.asyncio
    async def test_empty_default_falls_back_to_provider_with_key(
        self,
        m_config,
        m_get_provider,
        m_char,
        m_foresh,
        m_sum,
        m_draft,
        m_audit,
        m_audit_ch,
        m_rt,
        m_sd,
        m_da,
    ) -> None:
        """config.llm_default_model="" + provider "deepseek" has key ->
        build_deep_agent receives NON-empty api_key (resolved from registry).
        """
        m_config.llm_default_model = ""
        m_config.model_routing = {}

        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        m_get_provider.return_value = LLMProviderConfig(
            provider="deepseek",
            api_key="test-api-key-value",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek/deepseek-v4-flash",
            models=["deepseek-v4-flash"],
        )

        _default_mocks(m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_rt, m_sd)
        data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hello")

        svc = await _get_chat_agent_service()(data=data, db=MagicMock())

        chat_agent_cls = _get_chat_agent_service_cls()
        assert isinstance(svc, chat_agent_cls)
        # KEY assertion: api_key must be NON-empty (resolved from provider config)
        api_key = _kwarg_or_positional(m_da.call_args, "api_key", 1, None)
        assert api_key, "api_key must be non-empty when a provider with key exists"
        model = _kwarg_or_positional(m_da.call_args, "model", 0, None)
        assert model, "model must be non-empty when resolved from provider config"

    @patch("inkflow.api.deps.build_deep_agent")
    @patch("inkflow.api.deps.build_save_draft_tool")
    @patch("inkflow.api.deps.build_reader_tools")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    @patch(
        "inkflow.infrastructure.llm.provider_config._await_registry_entry"
    )
    @patch(
        "inkflow.infrastructure.llm.provider_config.get_provider_config",
        side_effect=ValueError("API key not configured for provider"),
    )
    @patch("inkflow.core.config.config")
    @pytest.mark.asyncio
    async def test_empty_default_no_provider_raises_422(
        self,
        m_config,
        m_get_provider,
        m_await_registry,
        m_char,
        m_foresh,
        m_sum,
        m_draft,
        m_audit,
        m_audit_ch,
        m_rt,
        m_sd,
        m_da,
    ) -> None:
        """config.llm_default_model="" + no provider with key -> get_chat_agent_service
        raises HTTPException(422), NOT a 500 Missing credentials."""
        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_await_registry.return_value = None
        data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hello")
        _default_mocks(
            m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_rt, m_sd
        )
        with patch(
            "inkflow.infrastructure.llm.provider_config._BUILTIN_PROVIDERS",
            {"openai": None, "deepseek": None, "zhipu": None, "ollama": None},
        ), patch(
            "inkflow.infrastructure.llm.provider_config._load_stored_key",
            return_value=None,
        ), pytest.raises(HTTPException) as exc_info:
            await _get_chat_agent_service()(data=data, db=MagicMock())

        assert exc_info.value.status_code == 422
        assert "默认模型" in exc_info.value.detail or "model" in exc_info.value.detail.lower()
        # build_deep_agent must NOT be called with empty api_key (no 500 path)
        assert m_da.call_count == 0


class TestResolveModelPriority:
    """#738: resolve_model(agent > project > global) is called by deps_chat_agent."""

    @patch("inkflow.api.deps.build_deep_agent")
    @patch("inkflow.api.deps.build_save_draft_tool")
    @patch("inkflow.api.deps.build_reader_tools")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    @patch(
        "inkflow.domain.services.model_resolution.resolve_model"
    )
    @pytest.mark.asyncio
    async def test_resolve_model_is_called(
        self,
        m_resolve,
        m_char,
        m_foresh,
        m_sum,
        m_draft,
        m_audit,
        m_audit_ch,
        m_rt,
        m_sd,
        m_da,
    ) -> None:
        """resolve_model must be called by get_chat_agent_service (consistency
        with 8 other services that already use it)."""
        m_resolve.return_value = "deepseek/deepseek-v4-flash"
        _default_mocks(
            m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_rt, m_sd
        )
        data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hello")

        await _get_chat_agent_service()(data=data, db=MagicMock())

        # resolve_model must have been called at least once
        assert m_resolve.call_count >= 1
