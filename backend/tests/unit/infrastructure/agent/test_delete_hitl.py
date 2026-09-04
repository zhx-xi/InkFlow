"""#766 阶段② 删除 HITL 中断 RED 契约测试 — ask_once interrupt → approve/reject；auto 直执行.

依据 specs/f26-agent-tools/spec.md §6.2/§6.3 + ADR-043 §2（复用 F44 interrupt() 模式，
见 book_agentic_pipeline.py:37/338-355）。锁定契约:
1. ask_once: 删除工具 func 内部调用 interrupt(payload)；payload 含 tool / entity_id；
   decision["approved"]=True → 执行删除（ok=True）；False →
   {"ok": False, "error": "用户拒绝删除"} 且不执行删除（service 不被调用）。
2. auto: 直接执行删除，不调用 interrupt。
3. manual: 删除工具不注册（装配守卫，见 test_delete_assembly.py）——本文件不测。
4. interrupt 注入点: delete_tools 模块级 `from langgraph.types import interrupt`
   （镜像 book_agentic_pipeline.py），mock 目标为
   inkflow.infrastructure.agent.tools.delete_tools.interrupt。
5. 批准只放行本次删除，不升级为 auto（每次 ask_once 调用都走 interrupt）。

RED 形态: delete_tools.py / ToolAuth 不存在 → 收集期 ModuleNotFoundError/ImportError。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.domain.models.agent_tools import ToolAuth
from inkflow.infrastructure.agent.tools.delete_tools import (
    DeleteToolDeps,
    build_delete_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")

# (工具名, deps 服务字段, service 方法名, 实体 id 参数名) —— 与 test_delete_tools 同源
DELETE_TOOL_CASES = [
    ("delete_character", "character_service", "delete_character", "character_id"),
    ("delete_world_setting", "world_service", "delete_setting", "setting_id"),
    ("delete_outline", "outline_service", "delete_outline", "outline_id"),
    ("delete_map", "map_service", "delete_map", "map_id"),
    ("delete_timeline_event", "timeline_service", "delete_event", "event_id"),
    ("delete_foreshadowing", "foreshadowing_service", "delete", "foreshadowing_id"),
    ("memory_remove", "memory_service", "remove_preference", "preference_id"),
]


def _make_deps(delete_permission: str) -> DeleteToolDeps:
    """构造删除工具依赖：按 delete_permission 建 ToolAuth。"""
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return DeleteToolDeps(
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        map_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_service=MagicMock(),
        memory_service=MagicMock(),
        audit_service=audit,
        auth=ToolAuth(delete_permission=delete_permission),
        expected_project_id=PROJECT_ID,
    )


def _mock_service(deps: DeleteToolDeps, tool_name: str) -> AsyncMock:
    """按 DELETE_TOOL_CASES 给对应 service 方法挂 AsyncMock（返回 True）。"""
    _tool_name, svc_field, method_name, _entity_key = next(
        c for c in DELETE_TOOL_CASES if c[0] == tool_name
    )
    method = AsyncMock(return_value=True)
    setattr(getattr(deps, svc_field), method_name, method)
    return method


class TestAskOnceInterrupt:
    """ask_once 模式：interrupt 决策驱动删除执行 / 拒绝。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,svc_field,method_name,entity_key", DELETE_TOOL_CASES)
    @patch(
        "inkflow.infrastructure.agent.tools.delete_tools.interrupt",
        return_value={"approved": True},
    )
    async def test_approved_executes_delete(
        self, m_interrupt, tool_name, svc_field, method_name, entity_key
    ) -> None:
        """用户批准 → 本次删除执行（ok=True），HITL payload 含 tool/entity_id。"""
        deps = _make_deps("ask_once")
        method = _mock_service(deps, tool_name)
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        entity_id = "550e8400-e29b-41d4-a716-44665544000b"
        result = json.loads(await tools[tool_name].func(**{entity_key: entity_id}))
        assert result["ok"] is True
        method.assert_awaited_once()
        # HITL payload 契约（§6.3）：tool + entity_id
        payload = m_interrupt.call_args.args[0]
        assert payload["tool"] == tool_name
        assert str(payload["entity_id"]) == entity_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,svc_field,method_name,entity_key", DELETE_TOOL_CASES)
    @patch(
        "inkflow.infrastructure.agent.tools.delete_tools.interrupt",
        return_value={"approved": False},
    )
    async def test_rejected_skips_delete(
        self, m_interrupt, tool_name, svc_field, method_name, entity_key
    ) -> None:
        """用户拒绝 → 返回"用户拒绝删除"，不执行删除（service 不被调用）。"""
        deps = _make_deps("ask_once")
        method = _mock_service(deps, tool_name)
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        result = json.loads(await tools[tool_name].func(**{entity_key: "x"}))
        assert result["ok"] is False
        assert result["error"] == "用户拒绝删除"
        method.assert_not_awaited()


class TestAutoModeDirect:
    """auto 模式：直接执行删除，不触发 interrupt。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,svc_field,method_name,entity_key", DELETE_TOOL_CASES)
    @patch("inkflow.infrastructure.agent.tools.delete_tools.interrupt")
    async def test_executes_without_interrupt(
        self, m_interrupt, tool_name, svc_field, method_name, entity_key
    ) -> None:
        deps = _make_deps("auto")
        method = _mock_service(deps, tool_name)
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        result = json.loads(await tools[tool_name].func(**{entity_key: "x"}))
        assert result["ok"] is True
        method.assert_awaited_once()
        m_interrupt.assert_not_called()
