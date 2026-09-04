"""#758 RED: agentic writer model resolution when global default is empty.

Contracts (mirror #738 chat-path decision D3=A full self-contained loop):
1. config.llm_default_model="" + a provider with a chat model and key exists
   -> get_agentic_writer_service returns an AgenticWriterService whose
      agent_factory, when invoked, calls build_agentic_writer with a NON-empty
      api_key (resolved from registry fallback).
2. config.llm_default_model="" + no provider with a chat model + key
   -> get_agentic_writer_service raises HTTPException(422) "未配置默认模型"
      (NOT a 500 Missing credentials).
3. resolve_model priority agent > project > global is preserved (consistency
   with the other services already using resolve_model).

RED expectation (current code):
- Current deps.py get_agentic_writer_service does NOT call resolve_model and
  does NOT fall back to the registry. When config.llm_default_model="", it goes
  through parse_model_string("") -> ValueError -> except: pass -> api_key=""
  -> build_agentic_writer(api_key="") -> ChatOpenAI -> Missing credentials -> 500.
- So: test 1 FAILS (api_key is empty, not non-empty).
- test 2 FAILS (no HTTPException raised; returns a service with empty api_key).
- test 3 FAILS (resolve_model not called).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from inkflow.api.deps import get_agentic_writer_service
from inkflow.domain.models.agent_run import AgenticWriteRequest

# Note: import the deps/service chain at module top so pipeline_templates
# module-level BUILTIN_TEMPLATES construction reads the REAL config singleton
# at import time. If imported lazily inside a test method, the
# @patch("inkflow.core.config.config") would turn config.llm_default_model into a
# MagicMock and break AgentRole(model=...) during pipeline_templates import
# (agentic_writer -> pipeline_templates).

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
CHAPTER_ID = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _kwarg_or_positional(call, name: str, index: int, default=None):
    """Tolerantly extract mock call arg: keyword first, then positional."""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _default_mocks(
    m_char,
    m_foresh,
    m_sum,
    m_draft,
    m_audit,
    m_audit_ch,
    m_chapter,
    m_memory,
):
    """Set default return values on all service/tool factory mocks."""
    m_char.return_value = MagicMock()
    m_foresh.return_value = MagicMock()
    m_sum.return_value = MagicMock()
    m_draft.return_value = MagicMock()
    m_audit.return_value = MagicMock()
    m_audit_ch.return_value = MagicMock()
    m_chapter.return_value = MagicMock()
    m_memory.return_value = MagicMock()


def _build_request() -> AgenticWriteRequest:
    return AgenticWriteRequest(
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        outline="本章大纲",
    )


class TestEmptyDefaultModelFallbackToRegistry:
    """#758: config.llm_default_model="" + provider with key -> resolve from registry."""

    @patch("inkflow.infrastructure.agent.agentic_writer.build_agentic_writer")
    @patch(
        "inkflow.infrastructure.agent.agentic_writer.build_writer_agent_system_prompt",
        return_value="prompt",
    )
    @patch("inkflow.api.deps.get_memory_service")
    @patch("inkflow.api.deps.get_chapter_service")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_empty_default_raises_422_without_registry_scan(
        self,
        m_config,
        m_get_provider,
        m_char,
        m_foresh,
        m_sum,
        m_draft,
        m_audit,
        m_audit_ch,
        m_chapter,
        m_memory,
        m_build_sysprompt,
        m_writer,
    ) -> None:
        """#929 迁移（原 #758 D3=A 回退契约废止）：空默认 → 422，零扫描回退。

        mock 一切 get_provider_config 调用抛 ValueError → 旧实现扫描全败 422 /
        新实现 fail-fast 422。#929 反转锚：调用计数 == 0（回退循环已删除）。
        """
        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_get_provider.side_effect = ValueError("API key not configured for provider")

        _default_mocks(m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_chapter, m_memory)

        with pytest.raises(HTTPException) as exc_info:
            get_agentic_writer_service(db=MagicMock())

        assert exc_info.value.status_code == 422
        assert "默认模型" in exc_info.value.detail or "model" in exc_info.value.detail.lower()
        assert m_get_provider.call_count == 0, (
            "#929: 空默认绝不再遍历注册表回退（embedding 误装配缺陷通道已删除）"
        )
        # build_agentic_writer must NOT be called with empty api_key (no 500 path)
        assert m_writer.call_count == 0

    @patch("inkflow.infrastructure.agent.agentic_writer.build_agentic_writer")
    @patch(
        "inkflow.infrastructure.agent.agentic_writer.build_writer_agent_system_prompt",
        return_value="prompt",
    )
    @patch("inkflow.api.deps.get_memory_service")
    @patch("inkflow.api.deps.get_chapter_service")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    @patch("inkflow.infrastructure.llm.provider_config._await_registry_entry")
    @patch(
        "inkflow.infrastructure.llm.provider_config.get_provider_config",
        side_effect=ValueError("API key not configured for provider"),
    )
    @patch("inkflow.core.config.config")
    def test_empty_default_no_provider_raises_422(
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
        m_chapter,
        m_memory,
        m_build_sysprompt,
        m_writer,
    ) -> None:
        """config.llm_default_model="" + no provider with key -> get_agentic_writer_service
        raises HTTPException(422), NOT a 500 Missing credentials."""
        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_await_registry.return_value = None
        _default_mocks(m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_chapter, m_memory)
        with (
            patch(
                "inkflow.infrastructure.llm.provider_config._BUILTIN_PROVIDERS",
                {"openai": None, "deepseek": None, "zhipu": None, "ollama": None},
            ),
            patch(
                "inkflow.infrastructure.llm.provider_config._load_stored_key",
                return_value=None,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            get_agentic_writer_service(db=MagicMock())

        assert exc_info.value.status_code == 422
        assert "默认模型" in exc_info.value.detail or "model" in exc_info.value.detail.lower()
        # build_agentic_writer must NOT be called with empty api_key (no 500 path)
        assert m_writer.call_count == 0


class TestResolveModelPriority:
    """#758: resolve_model is called by get_agentic_writer_service (consistency)."""

    @patch("inkflow.infrastructure.agent.agentic_writer.build_agentic_writer")
    @patch(
        "inkflow.infrastructure.agent.agentic_writer.build_writer_agent_system_prompt",
        return_value="prompt",
    )
    @patch("inkflow.api.deps.get_memory_service")
    @patch("inkflow.api.deps.get_chapter_service")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.domain.services.model_resolution.resolve_model")
    def test_resolve_model_is_called(
        self,
        m_resolve,
        m_get_provider,
        m_char,
        m_foresh,
        m_sum,
        m_draft,
        m_audit,
        m_audit_ch,
        m_chapter,
        m_memory,
        m_build_sysprompt,
        m_writer,
    ) -> None:
        """resolve_model must be called by get_agentic_writer_service (consistency
        with the other services that already use it).

        #929 迁移：resolver 不再吞 provider 错误，须 mock provider 装配使走通。
        """
        m_resolve.return_value = "deepseek/deepseek-v4-flash"
        m_resolve.side_effect = None
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        m_get_provider.return_value = LLMProviderConfig(
            provider="deepseek",
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek/deepseek-v4-flash",
            models=["deepseek-v4-flash"],
        )
        _default_mocks(m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_chapter, m_memory)

        svc = get_agentic_writer_service(db=MagicMock())
        # constructing the service must consult resolve_model
        assert m_resolve.call_count >= 1
        # #929 func-cov（#496 线程盲区）：lazy 工厂同线程直调，触达 _build_agent
        svc._agent_factory(_build_request())
        assert m_writer.called, "lazy 工厂被调后必须触达 build_agentic_writer（_build_agent 覆盖）"
