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
    """#929 迁移（契约族反转留痕）：原「回退弧」覆盖用例 3 个全部改判 fail-fast。

    旧契约（#738 D3=A）：named provider 无 key → 静默继续 / 空默认 → 扫描回退。
    #929 拍板②：删除最终 fallback——上述任一形态 → HTTPException(422) + 诊断日志。
    """

    @pytest.mark.asyncio
    async def test_model_parse_value_error_raises_422(self) -> None:
        """#929 迁移（原「except pass 空 key 继续」废止）：named provider 无 key → 422。

        旧行为（空 key 透传 → 500 Missing credentials）正是 #821/#929 双缺陷的通道；
        新契约 fail-fast——绝不带空 key 装配 agent。
        """
        from fastapi import HTTPException

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
                patch(
                    "inkflow.infrastructure.llm.provider_config.get_provider_config",
                    side_effect=ValueError("no key for provider"),
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                await _get_chat_agent_service()(
                    data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                    db=MagicMock(),
                )

            assert exc_info.value.status_code == 422
            call = _mock(mocks, "build_deep_agent").call_args
            assert call is None, "#929: 422 后不得装配 agent（空 key 透传路径已删除）"
        finally:
            _stop_patches(patchers)

    @pytest.mark.asyncio
    async def test_empty_default_never_picks_provider_models_first(self) -> None:
        """#929 反转锚（原契约锁 models[0] 拾取 = 缺陷本体）：空默认 → 422，零扫描。

        旧用例锁定「openai models[0]=gpt-4o-mini 被静默装配」——同形态在 rc2 把
        zhipu embedding-3 装成 chat 模型（400 1213，issue #929）。回退删除后该弧
        不复存在：resolve_llm_credentials 零 provider 扫描 + 422。
        """
        from fastapi import HTTPException

        mocks, patchers = _patch_deps()
        try:
            config_mock = _mock(mocks, "config")
            config_mock.llm_default_model = ""
            config_mock.model_routing = {}
            with (
                patch(
                    "inkflow.domain.services.model_resolution.resolve_model",
                    return_value="",
                ),
                patch(
                    "inkflow.infrastructure.llm.provider_config.get_provider_config",
                    side_effect=AssertionError("must not scan providers after #929"),
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                await _get_chat_agent_service()(
                    data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                    db=MagicMock(),
                )

            assert exc_info.value.status_code == 422
        finally:
            _stop_patches(patchers)

    @pytest.mark.asyncio
    async def test_empty_default_with_modeless_provider_raises_422(self) -> None:
        """#929 迁移（原「provider 无模型 → 循环继续」弧废止）：空默认 → 422。

        旧契约测回退循环的 continue 弧（openai 无模型 → deepseek 命中）；回退删除
        后循环不存在——fail-fast 直接 422。
        """
        from fastapi import HTTPException

        mocks, patchers = _patch_deps()
        try:
            config_mock = _mock(mocks, "config")
            config_mock.llm_default_model = ""
            config_mock.model_routing = {}
            with (
                patch(
                    "inkflow.domain.services.model_resolution.resolve_model",
                    return_value="",
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                await _get_chat_agent_service()(
                    data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                    db=MagicMock(),
                )

            assert exc_info.value.status_code == 422
        finally:
            _stop_patches(patchers)
