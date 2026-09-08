"""F59-M2 RED (#963): chat agent 装配链思考档位解析（spec §2.2/§2.3/§3.1）。

契约（镜像 test_deps_chat_agent_model_resolution 的 mock 形态）:
1. ``get_chat_agent_service`` 装配时计算档位 = resolve_reasoning_effort(
   data.reasoning_effort > project.config.reasoning_effort > config.llm_reasoning_effort)，
   结果以 ``reasoning_effort=`` 关键字传给 ``build_deep_agent``（chat 面唯一入口，
   legacy /stream 不接入 §10）。
2. 项目查询失败/项目不存在 → 不阻断（软回退：跳过项目级，按全局解析）。
3. 全链未配置 → "default"；「不发 ChatLiteLLM 参数」的终局契约在
   test_capability_probe / test_litellm_migration 锁定（本文件只锁装配链传递）。

RED 预期失败形态:
- ChatStreamRequest 无 reasoning_effort 字段 → model_construct 不接受该键 →
  TypeError（extra 默认 ignore 时静默丢，断言仍翻红：build_deep_agent kwargs
  无 reasoning_effort → None != "low"）。
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.api.routers.chat_stream import ChatStreamRequest
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
GLOBAL_EFFORT = "medium"


def _fake_tool(name: str) -> Tool:
    return Tool(spec=ToolSpec(name=name, description="", input_schema={}), func=MagicMock())


def _project(reasoning_effort: str | None) -> Project:
    return Project.model_construct(
        id=uuid.UUID(PROJECT_ID),
        name="p",
        config=ProjectConfig.model_construct(reasoning_effort=reasoning_effort),
    )


def _provider_cfg() -> LLMProviderConfig:
    return LLMProviderConfig(
        provider="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-v4-flash",
        models=["deepseek-v4-flash"],
    )


async def _assemble(
    *,
    request_effort: str | None,
    project: Project | None,
    project_svc_error: bool = False,
    global_effort: str = GLOBAL_EFFORT,
) -> MagicMock:
    """以既有 mock 装配形态直调 get_chat_agent_service，返回 build_deep_agent mock。"""
    from inkflow.api.deps import get_chat_agent_service

    data = ChatStreamRequest.model_construct(
        project_id=PROJECT_ID,
        prompt="hi",
        chapter_id=None,
        chapter_context=None,
        conversation_id=None,
    )
    # RED 期字段不存在 → 显式 setattr 保证契约输入成立（不依赖字段存在）
    data.reasoning_effort = request_effort

    proj_svc = MagicMock()
    if project_svc_error:
        proj_svc.get = AsyncMock(side_effect=RuntimeError("db exploded"))
    else:
        proj_svc.get = AsyncMock(return_value=project)

    conv_svc = MagicMock()
    conv_svc.get = AsyncMock(return_value=None)

    stack = ExitStack()
    try:
        patches = {
            "inkflow.api.deps.build_deep_agent": MagicMock(),
            "inkflow.api.deps.build_save_draft_tool": MagicMock(
                return_value=_fake_tool("save_draft")
            ),
            "inkflow.api.deps.build_reader_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_setting_write_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_setting_update_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_outline_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_world_rw_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_memory_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_writing_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_delete_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.build_agent_chain_tools": MagicMock(return_value=[]),
            "inkflow.api.deps.get_chapter_audit_service": MagicMock(),
            "inkflow.api.deps.get_audit_service": MagicMock(),
            "inkflow.api.deps.get_draft_service": MagicMock(),
            "inkflow.api.deps.get_summary_service": MagicMock(),
            "inkflow.api.deps.get_foreshadowing_service": MagicMock(),
            "inkflow.api.deps.get_character_service": MagicMock(),
            "inkflow.api.deps.get_world_service": MagicMock(),
            "inkflow.api.deps.get_outline_service": MagicMock(),
            "inkflow.api.deps.get_chapter_service": MagicMock(),
            "inkflow.api.deps.get_map_service": MagicMock(),
            "inkflow.api.deps.get_timeline_service": MagicMock(),
            "inkflow.api.deps.get_memory_service": MagicMock(),
            "inkflow.api.deps.get_writing_service": MagicMock(),
            "inkflow.api.deps.get_agent_service": MagicMock(),
            "inkflow.api.deps.get_agent_entity_service": MagicMock(),
            "inkflow.api.deps.get_context_service": MagicMock(),
            "inkflow.api.deps.get_project_service": MagicMock(return_value=proj_svc),
            "inkflow.api.deps.get_conversation_service": MagicMock(return_value=conv_svc),
            "inkflow.infrastructure.llm.provider_config.get_provider_config": MagicMock(
                return_value=_provider_cfg()
            ),
            "inkflow.core.config.config": MagicMock(),
        }
        mocks: dict[str, MagicMock] = {}
        for target, obj in patches.items():
            mocks[target] = stack.enter_context(patch(target, obj))
        m_cfg = mocks["inkflow.core.config.config"]
        m_cfg.llm_default_model = "deepseek/deepseek-v4-flash"
        m_cfg.llm_reasoning_effort = global_effort
        m_cfg.model_routing = {}
        await get_chat_agent_service(data=data, db=MagicMock())
        return mocks["inkflow.api.deps.build_deep_agent"]
    finally:
        stack.close()


class TestChatAgentReasoningResolution:
    """装配链三级解析：调用 > 项目 > 全局 → build_deep_agent kwargs。"""

    @pytest.mark.asyncio
    async def test_request_level_wins(self) -> None:
        """请求级 low 覆盖项目 high 与全局 medium。"""
        m_da = await _assemble(request_effort="low", project=_project("high"))
        kwargs = m_da.call_args.kwargs
        assert kwargs.get("reasoning_effort") == "low", (
            f"chat 装配必须传请求级档位，实得 {kwargs.get('reasoning_effort')!r}"
        )

    @pytest.mark.asyncio
    async def test_project_level_when_request_none(self) -> None:
        m_da = await _assemble(request_effort=None, project=_project("high"))
        assert m_da.call_args.kwargs.get("reasoning_effort") == "high"

    @pytest.mark.asyncio
    async def test_global_level_when_request_and_project_none(self) -> None:
        m_da = await _assemble(request_effort=None, project=_project(None))
        assert m_da.call_args.kwargs.get("reasoning_effort") == GLOBAL_EFFORT

    @pytest.mark.asyncio
    async def test_default_when_all_unset(self) -> None:
        """全局显式 'default' → 装配传 'default'（构造点不发参数另有契约锁）。"""
        m_da = await _assemble(
            request_effort=None, project=_project(None), global_effort="default"
        )
        assert m_da.call_args.kwargs.get("reasoning_effort") == "default"

    @pytest.mark.asyncio
    async def test_explicit_default_at_request_overrides_project(self) -> None:
        """"default" 是显式档位：请求级 default 覆盖项目 high。"""
        m_da = await _assemble(request_effort="default", project=_project("high"))
        assert m_da.call_args.kwargs.get("reasoning_effort") == "default"

    @pytest.mark.asyncio
    async def test_project_fetch_failure_soft_falls_back(self) -> None:
        """项目查询抛异常 → 不阻断装配（软回退全局），绝不让 chat 500。"""
        m_da = await _assemble(request_effort=None, project=None, project_svc_error=True)
        assert m_da.call_count == 1, "项目查询失败不得阻断 agent 装配"
        assert m_da.call_args.kwargs.get("reasoning_effort") == GLOBAL_EFFORT
