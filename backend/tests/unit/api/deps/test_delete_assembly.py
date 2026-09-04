"""#766 阶段② 装配守卫 RED 契约测试 — get_chat_agent_service 按 conversation 授权注入删除工具.

依据 specs/f26-agent-tools/spec.md §6.2/§6.5 + ADR-043 §2-§3。锁定契约:
1. get_chat_agent_service 读 conversation.delete_permission——经
   deps_module（inkflow.api.deps）get_conversation_service(db).get(conversation_id)；
   会话 id 取自 data.conversation_id（ChatStreamRequest 阶段② 新增字段，API 契约；
   本测试以 SimpleNamespace 注入，不锁定具体 schema）。
2. manual（默认）: 不注入删除工具（tools 列表无 delete_* / memory_remove）。
3. ask_once: 注入删除工具；装配产物的 func 内部调用 interrupt()（HITL）。
4. auto: 注入删除工具；func 直接执行（不 interrupt）。
5. build_delete_tools 走真实实现（其 service 依赖复用各 getter mock），其余工具
   工厂全部 mock；interrupt 注入点为 delete_tools.interrupt（模块级
   from langgraph.types import interrupt，镜像 book_agentic_pipeline.py）。

RED 形态（当前 deps_chat_agent.py）:
- 不读 conversation（get_conversation_service 未被调用）→ manual 测试的
  conv_get.assert_awaited_once 失败；
- 不注入删除工具 → ask_once/auto 测试断言 delete 工具在 tools 列表失败。
（patch 目标 get_conversation_service 不存在亦使测试先行 ERROR——两种均 RED。）
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.api.deps import get_chat_agent_service
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
CONVERSATION_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

DELETE_TOOL_NAMES = [
    "delete_character",
    "delete_world_setting",
    "delete_outline",
    "delete_map",
    "delete_timeline_event",
    "delete_foreshadowing",
    "memory_remove",
]


def _fake_tool(name: str) -> Tool:
    """构造最小 Tool（spec.name 可断言，func 不被执行）。"""
    return Tool(
        spec=ToolSpec(name=name, description="", input_schema={}),
        func=MagicMock(),
    )


def _provider_config() -> LLMProviderConfig:
    """deepseek provider 配置（避免真实 provider 注册表/网络）。"""
    return LLMProviderConfig(
        provider="deepseek",
        api_key="test-api-key",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek/deepseek-v4-flash",
        models=["deepseek-v4-flash"],
    )


def _service_mock() -> MagicMock:
    """删除工具依赖的 service mock：delete 方法全部 AsyncMock（返回 True）。"""
    svc = MagicMock()
    svc.delete_character = AsyncMock(return_value=True)
    svc.delete_setting = AsyncMock(return_value=True)
    svc.delete_outline = AsyncMock(return_value=True)
    svc.delete_map = AsyncMock(return_value=True)
    svc.delete_event = AsyncMock(return_value=True)
    svc.delete = AsyncMock(return_value=True)
    svc.remove_preference = AsyncMock(return_value=True)
    return svc


async def _assemble_chat_agent(data: SimpleNamespace, *, delete_permission: str):
    """mock 装配 get_chat_agent_service；返回 (svc, tools, conv_get_mock)。

    - get_chat_agent_service 阶段② 变更为 async def（conversation 读取需异步 DB
      访问；FastAPI 依赖原生支持 async——chat_stream.py 的 Depends 无需改动；
      既有 test_deps_chat_agent_model_resolution.py 同步直调需同步加 await）；
    - 全部 service getter / 工具工厂（除 build_delete_tools）/ 模型解析均 mock；
    - build_delete_tools 走真实实现（验证装配产物），service 依赖复用 getter mock；
    - tools 取自 build_deep_agent 调用实参（m_da.call_args.kwargs["tools"]）。
    """
    conv = SimpleNamespace(delete_permission=delete_permission)
    conv_svc = MagicMock()
    conv_svc.get = AsyncMock(return_value=conv)

    with ExitStack() as stack:
        m_da = stack.enter_context(patch("inkflow.api.deps.build_deep_agent"))
        stack.enter_context(patch("inkflow.api.deps.build_reader_tools", return_value=[]))
        stack.enter_context(
            patch(
                "inkflow.api.deps.build_save_draft_tool",
                return_value=_fake_tool("save_draft"),
            )
        )
        stack.enter_context(patch("inkflow.api.deps.build_setting_write_tools", return_value=[]))
        stack.enter_context(patch("inkflow.api.deps.build_setting_update_tools", return_value=[]))
        stack.enter_context(patch("inkflow.api.deps.build_world_rw_tools", return_value=[]))
        stack.enter_context(patch("inkflow.api.deps.build_memory_tools", return_value=[]))
        stack.enter_context(patch("inkflow.api.deps.build_writing_tools", return_value=[]))
        stack.enter_context(
            patch("inkflow.api.deps.get_conversation_service", return_value=conv_svc)
        )
        for getter in [
            "get_character_service",
            "get_foreshadowing_service",
            "get_summary_service",
            "get_chapter_audit_service",
            "get_draft_service",
            "get_audit_service",
            "get_world_service",
            "get_outline_service",
            "get_map_service",
            "get_timeline_service",
            "get_memory_service",
            "get_writing_service",
        ]:
            stack.enter_context(patch(f"inkflow.api.deps.{getter}", return_value=_service_mock()))
        stack.enter_context(
            patch(
                "inkflow.domain.services.model_resolution.resolve_model",
                return_value="deepseek/deepseek-v4-flash",
            )
        )
        stack.enter_context(
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                return_value=_provider_config(),
            )
        )
        svc = await get_chat_agent_service(data=data, db=MagicMock())
        tools = m_da.call_args.kwargs.get("tools") or m_da.call_args.args[2]
        return svc, tools, conv_svc.get


def _chat_data() -> SimpleNamespace:
    """chat 请求数据：project_id/chapter_id/conversation_id（schema 变更见模块 docstring）。"""
    return SimpleNamespace(
        project_id=PROJECT_ID,
        chapter_id=None,
        conversation_id=CONVERSATION_ID,
    )


class TestManualModeGuard:
    """manual（默认）：不注入删除工具，但装配仍读取 conversation 授权。"""

    @pytest.mark.asyncio
    async def test_manual_no_delete_tools(self) -> None:
        _svc, tools, conv_get = await _assemble_chat_agent(_chat_data(), delete_permission="manual")
        names = [t.spec.name for t in tools]
        assert not any(name in DELETE_TOOL_NAMES for name in names)
        # 契约：授权状态必须真实读取（防「默认不读 conversation」假绿）
        conv_get.assert_awaited_once()
        assert str(conv_get.await_args.args[0]) == str(CONVERSATION_ID)


class TestAskOnceModeGuard:
    """ask_once：注入删除工具，装配产物 func 触发 HITL interrupt。"""

    @pytest.mark.asyncio
    @patch(
        "inkflow.infrastructure.agent.tools.delete_tools.interrupt",
        return_value={"approved": True},
    )
    async def test_ask_once_injects_delete_tools_and_interrupts(self, m_interrupt) -> None:
        _svc, tools, _conv_get = await _assemble_chat_agent(
            _chat_data(), delete_permission="ask_once"
        )
        names = [t.spec.name for t in tools]
        for name in DELETE_TOOL_NAMES:
            assert name in names
        # 装配产物的删除工具 func 走 HITL（interrupt 被调用）
        delete_char = next(t for t in tools if t.spec.name == "delete_character")
        result = json.loads(
            await delete_char.func(character_id="550e8400-e29b-41d4-a716-44665544000c")
        )
        assert result["ok"] is True
        m_interrupt.assert_called_once()


class TestAutoModeGuard:
    """auto：注入删除工具，装配产物 func 直接执行（不 interrupt）。"""

    @pytest.mark.asyncio
    @patch("inkflow.infrastructure.agent.tools.delete_tools.interrupt")
    async def test_auto_injects_delete_tools_direct(self, m_interrupt) -> None:
        _svc, tools, _conv_get = await _assemble_chat_agent(_chat_data(), delete_permission="auto")
        names = [t.spec.name for t in tools]
        for name in DELETE_TOOL_NAMES:
            assert name in names
        delete_char = next(t for t in tools if t.spec.name == "delete_character")
        result = json.loads(
            await delete_char.func(character_id="550e8400-e29b-41d4-a716-44665544000c")
        )
        assert result["ok"] is True
        m_interrupt.assert_not_called()
