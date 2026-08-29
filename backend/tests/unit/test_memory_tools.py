"""F51 记忆工具 RED 契约测试 — build_memory_tools 注册 + 执行信封.

依据 specs/f51-agent-tools-v2/spec.md §2.7。镜像 test_chat_setting_write_tools 形态。
锁定契约:
1. build_memory_tools(deps) 返回 [memory_list, memory_add, memory_update]。
2. 成功 {"ok": True, ...} / 失败 {"ok": False, "error": "..."}（不抛出）。
3. expected_project_id 绑定。
4. 写类成功/失败均落审计（audit_service.record），审计异常静默。
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.infrastructure.agent.tools.memory_tools import (
    MemoryToolDeps,
    build_memory_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


def _make_deps() -> MemoryToolDeps:
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return MemoryToolDeps(
        memory_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PROJECT_ID,
    )


class TestBuildMemoryTools:
    """build_memory_tools 注册 3 个记忆工具。"""

    def test_registers_three_tools(self) -> None:
        tools = build_memory_tools(_make_deps())
        assert [t.spec.name for t in tools] == [
            "memory_list",
            "memory_add",
            "memory_update",
        ]

    def test_tool_specs_have_input_schema(self) -> None:
        for t in build_memory_tools(_make_deps()):
            assert isinstance(t.spec.input_schema, dict)
            assert "type" in t.spec.input_schema

    @pytest.mark.asyncio
    async def test_memory_list_success_envelope(self) -> None:
        deps = _make_deps()
        deps.memory_service.list_preferences = AsyncMock(return_value=([], 0))
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        result = json.loads(await tools["memory_list"].func())
        assert result["ok"] is True
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_memory_add_success_envelope(self) -> None:
        deps = _make_deps()
        deps.memory_service.create_preference = AsyncMock(
            return_value=SimpleNamespace(id="pref-1")
        )
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        result = json.loads(await tools["memory_add"].func(category="style", pattern="短句"))
        assert result["ok"] is True
        assert result["preference_id"] == "pref-1"

    @pytest.mark.asyncio
    async def test_memory_add_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.memory_service.create_preference = AsyncMock(
            side_effect=ValueError("分类非法")
        )
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        result = json.loads(await tools["memory_add"].func(category="style", pattern="短句"))
        assert result["ok"] is False
        assert "分类非法" in result["error"]

    @pytest.mark.asyncio
    async def test_memory_update_success_envelope(self) -> None:
        deps = _make_deps()
        deps.memory_service.update_preference = AsyncMock(
            return_value=SimpleNamespace(id="pref-1")
        )
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        result = json.loads(
            await tools["memory_update"].func(preference_id="pref-1", pattern="长句")
        )
        assert result["ok"] is True
        assert result["preference_id"] == "pref-1"

    @pytest.mark.asyncio
    async def test_expected_project_id_binding(self) -> None:
        """memory_add 恒用绑定 project_id（LLM 不自报）。"""
        deps = _make_deps()
        deps.memory_service.create_preference = AsyncMock(
            return_value=SimpleNamespace(id="pref-1")
        )
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        await tools["memory_add"].func(
            category="style", pattern="短句", project_id="00000000-0000-0000-0000-000000000000"
        )
        args, kwargs = deps.memory_service.create_preference.call_args
        used_project_id = kwargs.get("project_id") or (args[0] if args else None)
        assert str(used_project_id) == str(PROJECT_ID)


    @pytest.mark.asyncio
    async def test_memory_update_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.memory_service.update_preference = AsyncMock(
            side_effect=ValueError("偏好不存在")
        )
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        result = json.loads(
            await tools["memory_update"].func(preference_id="pref-1", pattern="长句")
        )
        assert result["ok"] is False
        assert "偏好不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_memory_list_with_data(self) -> None:
        deps = _make_deps()
        item = SimpleNamespace(id="pref-1", pattern="短句")
        item.model_dump = lambda *a, **k: {"id": "pref-1", "pattern": "短句"}
        deps.memory_service.list_preferences = AsyncMock(return_value=([item], 1))
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        result = json.loads(await tools["memory_list"].func())
        assert result["ok"] is True
        assert len(result["data"]) == 1


class TestMemoryToolAudit:
    """写类成功/失败均落审计，审计异常静默。"""

    @pytest.mark.asyncio
    async def test_success_records_audit(self) -> None:
        deps = _make_deps()
        deps.memory_service.create_preference = AsyncMock(
            return_value=SimpleNamespace(id="pref-1")
        )
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        await tools["memory_add"].func(category="style", pattern="短句")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_failure_records_audit(self) -> None:
        deps = _make_deps()
        deps.memory_service.create_preference = AsyncMock(
            side_effect=ValueError("boom")
        )
        tools = {t.spec.name: t for t in build_memory_tools(deps)}
        await tools["memory_add"].func(category="style", pattern="短句")
        assert deps.audit_service.record.await_count >= 1
