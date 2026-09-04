"""Coverage backfill: get_chat_agent_service 模型解析分支（f47 §14 + #738）。

公开接口：直接 ``await get_chat_agent_service(data, db)``（FastAPI 依赖装配函数）。
镜像 tests/unit/test_deps_chat_agent_model_resolution.py 的 mock 模式：
- model 非空但 parse_model_string 抛 ValueError → except pass（89-90）
- 默认模型为空 + provider.default_model 空但 models 非空 → 取 models[0]（99）
- provider 无模型 → 循环继续（100->92 弧）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from inkflow.api.routers.chat_stream import ChatStreamRequest
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import Tool

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _fake_tool(name: str) -> Tool:
    return Tool(
        spec=ToolSpec(name=name, description="", input_schema={}),
        func=MagicMock(),
    )


def _kwarg(call, name: str, index: int, default=None):
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _get_chat_agent_service():
    from inkflow.api.deps import get_chat_agent_service

    return get_chat_agent_service


def _patch_deps():
    """收集 deps 模块各装配依赖的 mock（服务 getter + 工具工厂）。"""
    patchers = [
        patch("inkflow.api.deps.build_deep_agent"),
        patch("inkflow.api.deps.build_save_draft_tool", return_value=_fake_tool("save_draft")),
        patch("inkflow.api.deps.build_reader_tools", return_value=[_fake_tool("search")]),
        patch("inkflow.api.deps.build_setting_write_tools", return_value=[]),
        patch("inkflow.api.deps.build_setting_update_tools", return_value=[]),
        patch("inkflow.api.deps.build_world_rw_tools", return_value=[]),
        patch("inkflow.api.deps.build_memory_tools", return_value=[]),
        patch("inkflow.api.deps.build_writing_tools", return_value=[]),
        patch("inkflow.api.deps.build_agent_chain_tools", return_value=[]),
        patch("inkflow.api.deps.get_character_service"),
        patch("inkflow.api.deps.get_foreshadowing_service"),
        patch("inkflow.api.deps.get_summary_service"),
        patch("inkflow.api.deps.get_chapter_audit_service"),
        patch("inkflow.api.deps.get_audit_service"),
        patch("inkflow.api.deps.get_draft_service"),
        patch("inkflow.api.deps.get_conversation_service"),
        patch("inkflow.api.deps.get_context_service"),
        patch("inkflow.api.deps.get_agent_service"),
        patch("inkflow.api.deps.get_agent_entity_service"),
        patch("inkflow.core.config.config"),
    ]
    named: list[tuple[str, MagicMock]] = []
    for p in patchers:
        named.append((p.attribute, p.start()))
    return named, patchers


def _mock(named: list[tuple[str, MagicMock]], name: str) -> MagicMock:
    """按 patch 目标末段名取 mock（如 config / build_deep_agent）。"""
    for key, mock in named:
        if key == name:
            return mock
    raise KeyError(name)


def _stop_patches(patchers) -> None:
    for p in patchers:
        p.stop()


class TestChatAgentModelParseFallback:
    @pytest.mark.asyncio
    async def test_model_parse_value_error_leaves_empty_key(self) -> None:
        """model 非空但 parse_model_string 抛 ValueError → except pass，api_key 保持空。"""
        mocks, patchers = _patch_deps()
        try:
            config_mock = _mock(mocks, "config")
            config_mock.llm_default_model = "garbage/model"
            config_mock.model_routing = {}
            with (
                patch(
                    "inkflow.domain.services.model_resolution.resolve_model",
                    return_value="garbage/model",
                ),
                patch(
                    "inkflow.infrastructure.llm.provider_config.parse_model_string",
                    side_effect=ValueError("unknown provider"),
                ),
            ):
                svc = await _get_chat_agent_service()(
                    data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                    db=MagicMock(),
                )

            assert svc is not None
            call = _mock(mocks, "build_deep_agent").call_args
            assert call is not None
            assert _kwarg(call, "api_key", 1) == ""
        finally:
            _stop_patches(patchers)

    @pytest.mark.asyncio
    async def test_empty_default_uses_provider_models_first_entry(self) -> None:
        """默认模型空 + provider.default_model 空但 models 非空 → 取 models[0]（99 行）。"""
        mocks, patchers = _patch_deps()
        try:
            config_mock = _mock(mocks, "config")
            config_mock.llm_default_model = ""
            config_mock.model_routing = {}
            from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

            def _provider_cfg(provider: str):
                if provider == "openai":
                    return LLMProviderConfig(
                        provider="openai",
                        api_key="key-openai",
                        base_url="",
                        default_model="",
                        models=["gpt-4o-mini"],
                    )
                raise ValueError(f"no key for {provider}")

            with (
                patch(
                    "inkflow.domain.services.model_resolution.resolve_model",
                    return_value="",
                ),
                patch(
                    "inkflow.infrastructure.llm.provider_config.get_provider_config",
                    side_effect=_provider_cfg,
                ),
            ):
                await _get_chat_agent_service()(
                    data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                    db=MagicMock(),
                )

            call = _mock(mocks, "build_deep_agent").call_args
            assert call is not None
            assert _kwarg(call, "model", 0) == "gpt-4o-mini"
            assert _kwarg(call, "api_key", 1) == "key-openai"
        finally:
            _stop_patches(patchers)

    @pytest.mark.asyncio
    async def test_empty_default_skips_modeless_provider(self) -> None:
        """provider 无模型 → 循环继续；下一个 provider 命中（100->92 弧）。"""
        mocks, patchers = _patch_deps()
        try:
            config_mock = _mock(mocks, "config")
            config_mock.llm_default_model = ""
            config_mock.model_routing = {}
            from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

            def _provider_cfg(provider: str):
                if provider == "openai":
                    return LLMProviderConfig(
                        provider="openai",
                        api_key="",
                        base_url="",
                        default_model="",
                        models=[],
                    )
                if provider == "deepseek":
                    return LLMProviderConfig(
                        provider="deepseek",
                        api_key="key-deepseek",
                        base_url="",
                        default_model="deepseek-v4-flash",
                        models=["deepseek-v4-flash"],
                    )
                raise ValueError(f"no key for {provider}")

            with (
                patch(
                    "inkflow.domain.services.model_resolution.resolve_model",
                    return_value="",
                ),
                patch(
                    "inkflow.infrastructure.llm.provider_config.get_provider_config",
                    side_effect=_provider_cfg,
                ),
            ):
                await _get_chat_agent_service()(
                    data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                    db=MagicMock(),
                )

            call = _mock(mocks, "build_deep_agent").call_args
            assert call is not None
            assert _kwarg(call, "model", 0) == "deepseek-v4-flash"
            assert _kwarg(call, "api_key", 1) == "key-deepseek"
        finally:
            _stop_patches(patchers)
