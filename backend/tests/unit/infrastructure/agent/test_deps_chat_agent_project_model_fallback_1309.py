"""#1309 RED: chat 轨模型解析回退项目 config.model（#1298 同族第 3 处）.

根因：`api/deps_chat_agent.py` 的 `resolve_llm_credentials(config.llm_default_model)`
单参调用 → 项目 `config.model` 有值、全局 `llm_default_model` 为空时仍 fail-fast 422。
消费面：`chat_stream` 端点（`routers/chat_stream.py` `/agent/stream`）+
`chat_resume` 端点（`routers/chat_resume.py`，直接函数调用同依赖链）。

契约（与 book 轨 `books.py:375-378` / agentic 轨 #1298 同源，拒绝同族分叉）：
1. 项目 config.model 有值 + 全局空 → 装配成功，`build_deep_agent(model=<项目模型>)`
2. 项目 config.model 空 + 全局有值 → 全局档位生效（原语义保持）
3. 两者皆空 → 仍 HTTPException(422)（不静默放行）
4. 项目查询抛异常（project 不可达）→ 软回退全局，不阻断装配（镜像 reasoning_effort 语义）
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from inkflow.api.routers.chat_stream import ChatStreamRequest
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"

PROJECT_MODEL = "zhipu/glm-4.5"
GLOBAL_MODEL = "deepseek/deepseek-v4-flash"

_FAKE_TOOL = Tool(
    spec=ToolSpec(name="search_characters", description="", input_schema={}),
    func=MagicMock(),
)

# 装配栈里需要桩掉的 service getter / 工具工厂（真实装配会触达全部）
_STUBBED_NAMES = (
    "get_memory_service",
    "get_chapter_service",
    "get_chapter_audit_service",
    "get_audit_service",
    "get_draft_service",
    "get_summary_service",
    "get_foreshadowing_service",
    "get_character_service",
    "get_world_service",
    "get_conversation_service",
    "get_outline_service",
    "get_map_service",
    "get_timeline_service",
    "get_writing_service",
    "get_agent_service",
    "get_agent_entity_service",
)

_EMPTY_LIST_NAMES = (
    "build_setting_write_tools",
    "build_setting_update_tools",
    "build_outline_tools",
    "build_world_rw_tools",
    "build_memory_tools",
    "build_writing_tools",
    "build_agent_chain_tools",
)


def _provider_cfg(model: str) -> LLMProviderConfig:
    provider, model_name = model.split("/", 1)
    return LLMProviderConfig(
        provider=provider,
        api_key="test-key",
        base_url="https://example.invalid/v1",
        default_model=model,
        models=[model_name],
    )


def _fake_build_agent() -> MagicMock:
    """build_deep_agent 桩：返回 agent 实例，调用方读 `call_args.kwargs`.

    必须手工 `new=MagicMock()`（不可用自动 spec）：async 用例下 `patch` 的自动
    spec 会造 AsyncMock，按内部名 `_mock_name` 记账，`call_args.kwargs` 读不到
    传入的 `model`（KeyError）。
    """
    return MagicMock(return_value=MagicMock())


def _assembly_patchers(m_build: MagicMock) -> list:
    """装配栈桩：service getter + 工具工厂 + build_deep_agent（返回全部 patcher）.

    不 mock `resolve_llm_credentials` 本身——本 issue 的被测点正是「解析出的模型
    进了 build_deep_agent」，mock 掉就失去信号。
    """
    patchers = [
        patch(f"inkflow.api.deps.{name}", new=MagicMock(return_value=MagicMock()))
        for name in _STUBBED_NAMES
    ]
    patchers += [
        patch("inkflow.api.deps.build_reader_tools", new=MagicMock(return_value=[_FAKE_TOOL])),
        patch("inkflow.api.deps.build_save_draft_tool", new=MagicMock(return_value=_FAKE_TOOL)),
    ]
    patchers += [
        patch(f"inkflow.api.deps.{name}", new=MagicMock(return_value=[]))
        for name in _EMPTY_LIST_NAMES
    ]
    patchers.append(patch("inkflow.api.deps.build_deep_agent", new=m_build))
    return patchers


def _fake_project(model: str | None) -> MagicMock:
    cfg = MagicMock()
    cfg.model = model
    cfg.reasoning_effort = None
    project = MagicMock()
    project.config = cfg
    return project


async def _assemble(project, *, project_raises: bool = False, ctx_svc=None):
    """走真实 get_chat_agent_service 装配，返回 (service, build_deep_agent mock)."""
    from inkflow.api.deps import get_chat_agent_service

    project_svc = MagicMock()
    if project_raises:
        project_svc.get = AsyncMock(side_effect=RuntimeError("db down"))
    else:
        project_svc.get = AsyncMock(return_value=project)

    m_build = _fake_build_agent()
    patchers = [
        *_assembly_patchers(m_build),
        patch("inkflow.api.deps.get_project_service", new=MagicMock(return_value=project_svc)),
    ]
    if ctx_svc is not None:
        patchers.append(
            patch("inkflow.api.deps.get_context_service", new=MagicMock(return_value=ctx_svc))
        )

    # 单个 ExitStack 进出（勿用 p.start()/p.stop() 手配对：会在用例边界泄漏 patch，
    # 实测反噬 tests/unit/infrastructure/context 等后续用例）
    with ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)
        svc = await get_chat_agent_service(
            data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hello"),
            db=MagicMock(),
        )
    return svc, m_build


class TestProjectModelFallback:
    """契约 1：项目 config.model 有值 + 全局空 → 项目模型生效（#1309 主锚）。"""

    @pytest.mark.asyncio
    @patch("inkflow.core.config.config")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    async def test_project_model_used_when_global_empty(self, m_get_provider, m_config) -> None:
        m_config.llm_default_model = ""
        m_config.llm_reasoning_effort = None
        m_config.model_routing = {}
        m_get_provider.return_value = _provider_cfg(PROJECT_MODEL)

        _svc, m_build = await _assemble(_fake_project(PROJECT_MODEL))

        assert m_build.called, "装配成功应触达 build_deep_agent"
        assert m_build.call_args.kwargs["model"] == PROJECT_MODEL
        assert m_build.call_args.kwargs["api_key"] == "test-key"

    @pytest.mark.asyncio
    @patch("inkflow.core.config.config")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    async def test_project_model_absent_uses_global(self, m_get_provider, m_config) -> None:
        """契约 2：项目模型空 + 全局有值 → 全局档位（原语义保持）。"""
        m_config.llm_default_model = GLOBAL_MODEL
        m_config.llm_reasoning_effort = None
        m_config.model_routing = {}
        m_get_provider.return_value = _provider_cfg(GLOBAL_MODEL)

        _svc, m_build = await _assemble(_fake_project(None))

        assert m_build.call_args.kwargs["model"] == GLOBAL_MODEL

    @pytest.mark.asyncio
    @patch("inkflow.core.config.config")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    async def test_both_empty_still_422(self, m_get_provider, m_config) -> None:
        """契约 3：两者皆空 → 422（不静默放行，零注册表扫描）。"""
        m_config.llm_default_model = ""
        m_config.llm_reasoning_effort = None
        m_config.model_routing = {}
        m_get_provider.side_effect = ValueError("API key not configured for provider")

        with pytest.raises(HTTPException) as exc_info:
            await _assemble(_fake_project(None))

        assert exc_info.value.status_code == 422
        assert m_get_provider.call_count == 0, "#929: 空默认绝不遍历注册表回退"

    @pytest.mark.asyncio
    @patch("inkflow.core.config.config")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    async def test_project_lookup_failure_falls_back_to_global(
        self, m_get_provider, m_config
    ) -> None:
        """契约 4：项目不可达 → 软回退全局，不阻断装配。"""
        m_config.llm_default_model = GLOBAL_MODEL
        m_config.llm_reasoning_effort = None
        m_config.model_routing = {}
        m_get_provider.return_value = _provider_cfg(GLOBAL_MODEL)

        _svc, m_build = await _assemble(None, project_raises=True)

        assert m_build.call_args.kwargs["model"] == GLOBAL_MODEL

    @pytest.mark.asyncio
    @patch("inkflow.core.config.config")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    async def test_project_lookup_failure_global_empty_still_422(
        self, m_get_provider, m_config
    ) -> None:
        """契约 4b：项目不可达 + 全局空 → 仍 422（软回退不等于放行）。"""
        m_config.llm_default_model = ""
        m_config.llm_reasoning_effort = None
        m_config.model_routing = {}
        m_get_provider.side_effect = ValueError("API key not configured for provider")

        with pytest.raises(HTTPException) as exc_info:
            await _assemble(None, project_raises=True)

        assert exc_info.value.status_code == 422


class TestProjectContextInjected:
    """契约 1b：项目模型同样进 context_service.build_context（同一变量，非第二份解析）。"""

    @pytest.mark.asyncio
    @patch("inkflow.core.config.config")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    async def test_context_request_gets_project_model(self, m_get_provider, m_config) -> None:
        m_config.llm_default_model = ""
        m_config.llm_reasoning_effort = None
        m_config.model_routing = {}
        m_get_provider.return_value = _provider_cfg(PROJECT_MODEL)

        ctx_svc = MagicMock()
        ctx_svc.build_context = AsyncMock(return_value=MagicMock())
        ctx_svc.render_system_prompt = MagicMock(return_value="ctx")

        svc, _m_build = await _assemble(_fake_project(PROJECT_MODEL), ctx_svc=ctx_svc)
        await svc._project_context_getter("q", PROJECT_ID)

        assert ctx_svc.build_context.call_args.args[0].model == PROJECT_MODEL
