"""F51 世界读+写工具 RED 契约测试 — build_world_rw_tools 注册 + 执行信封.

依据 specs/f26-agent-tools/spec.md §2.4-2.6。镜像 test_chat_setting_write_tools 形态。
锁定契约:
1. build_world_rw_tools(deps) 返回 [list_maps, create_map, update_map,
   list_timeline_events, create_timeline_event, update_timeline_event,
   create_foreshadowing, update_foreshadowing]。
2. 每个 func 成功返回 {"ok": True, ...}，失败返回 {"ok": False, "error": "..."}（不抛出）。
3. expected_project_id 绑定。
4. 成功/失败均落审计（audit_service.record），审计异常静默。
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.infrastructure.agent.tools.world_readwrite_tools import (
    WorldRwToolDeps,
    build_world_rw_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


def _make_deps() -> WorldRwToolDeps:
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return WorldRwToolDeps(
        map_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PROJECT_ID,
    )


class TestBuildWorldRwTools:
    """build_world_rw_tools 注册 8 个世界读+写工具（地图/时间线/伏笔）。"""

    def test_registers_eight_tools(self) -> None:
        tools = build_world_rw_tools(_make_deps())
        assert sorted(t.spec.name for t in tools) == sorted([
            "list_maps",
            "create_map",
            "update_map",
            "list_timeline_events",
            "create_timeline_event",
            "update_timeline_event",
            "create_foreshadowing",
            "update_foreshadowing",
        ])

    def test_tool_specs_have_input_schema(self) -> None:
        for t in build_world_rw_tools(_make_deps()):
            assert isinstance(t.spec.input_schema, dict)
            assert "type" in t.spec.input_schema

    @pytest.mark.asyncio
    async def test_list_maps_success_envelope(self) -> None:
        deps = _make_deps()
        deps.map_service.list_maps = AsyncMock(return_value=[])
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["list_maps"].func())
        assert result["ok"] is True
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_create_map_success_envelope(self) -> None:
        deps = _make_deps()
        deps.map_service.create_map = AsyncMock(
            return_value=SimpleNamespace(id="map-1", name="大陆图")
        )
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["create_map"].func(name="大陆图"))
        assert result["ok"] is True
        assert result["map_id"] == "map-1"
        assert result["name"] == "大陆图"

    @pytest.mark.asyncio
    async def test_create_map_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.map_service.create_map = AsyncMock(side_effect=ValueError("同名地图已存在"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["create_map"].func(name="大陆图"))
        assert result["ok"] is False
        assert "同名地图已存在" in result["error"]

    @pytest.mark.asyncio
    async def test_update_map_success_envelope(self) -> None:
        deps = _make_deps()
        deps.map_service.update_map = AsyncMock(
            return_value=SimpleNamespace(id="map-1", name="大陆图")
        )
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["update_map"].func(map_id="map-1", name="大陆图"))
        assert result["ok"] is True
        assert result["map_id"] == "map-1"

    @pytest.mark.asyncio
    async def test_list_timeline_events_success_envelope(self) -> None:
        deps = _make_deps()
        deps.timeline_service.list_events = AsyncMock(return_value=[])
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["list_timeline_events"].func())
        assert result["ok"] is True
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_create_timeline_event_success_envelope(self) -> None:
        deps = _make_deps()
        deps.timeline_service.create_event = AsyncMock(
            return_value=SimpleNamespace(id="evt-1", title="开篇")
        )
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["create_timeline_event"].func(title="开篇"))
        assert result["ok"] is True
        assert result["event_id"] == "evt-1"
        assert result["title"] == "开篇"

    @pytest.mark.asyncio
    async def test_update_timeline_event_success_envelope(self) -> None:
        deps = _make_deps()
        deps.timeline_service.update_event = AsyncMock(
            return_value=SimpleNamespace(id="evt-1", title="开篇")
        )
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(
            await tools["update_timeline_event"].func(event_id="evt-1", title="开篇")
        )
        assert result["ok"] is True
        assert result["event_id"] == "evt-1"

    @pytest.mark.asyncio
    async def test_create_foreshadowing_success_envelope(self) -> None:
        deps = _make_deps()
        deps.foreshadowing_service.create = AsyncMock(
            return_value=SimpleNamespace(id="fsh-1")
        )
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["create_foreshadowing"].func(title="玉佩"))
        assert result["ok"] is True
        assert result["foreshadowing_id"] == "fsh-1"

    @pytest.mark.asyncio
    async def test_update_foreshadowing_success_envelope(self) -> None:
        deps = _make_deps()
        deps.foreshadowing_service.update = AsyncMock(
            return_value=SimpleNamespace(id="fsh-1")
        )
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(
            await tools["update_foreshadowing"].func(foreshadowing_id="fsh-1", title="新标题")
        )
        assert result["ok"] is True
        assert result["foreshadowing_id"] == "fsh-1"


    @pytest.mark.asyncio
    async def test_update_map_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.map_service.update_map = AsyncMock(side_effect=ValueError("地图不存在"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["update_map"].func(map_id="map-1", name="大陆图"))
        assert result["ok"] is False
        assert "地图不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_create_timeline_event_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.timeline_service.create_event = AsyncMock(side_effect=ValueError("标题不能为空"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["create_timeline_event"].func(title=""))
        assert result["ok"] is False
        assert "标题不能为空" in result["error"]

    @pytest.mark.asyncio
    async def test_update_timeline_event_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.timeline_service.update_event = AsyncMock(side_effect=ValueError("事件不存在"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(
            await tools["update_timeline_event"].func(event_id="evt-1", title="开篇")
        )
        assert result["ok"] is False
        assert "事件不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_create_foreshadowing_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.foreshadowing_service.create = AsyncMock(side_effect=ValueError("标题不能为空"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(await tools["create_foreshadowing"].func(title=""))
        assert result["ok"] is False
        assert "伏笔名不能为空" in result["error"]

    @pytest.mark.asyncio
    async def test_update_foreshadowing_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.foreshadowing_service.update = AsyncMock(side_effect=ValueError("伏笔不存在"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        result = json.loads(
            await tools["update_foreshadowing"].func(foreshadowing_id="fsh-1", title="新标题")
        )
        assert result["ok"] is False
        assert "伏笔不存在" in result["error"]


class TestWorldRwToolAudit:
    """写类工具成功/失败均落审计，审计异常静默。"""

    @pytest.mark.asyncio
    async def test_success_records_audit(self) -> None:
        deps = _make_deps()
        deps.map_service.create_map = AsyncMock(
            return_value=SimpleNamespace(id="map-1", name="大陆图")
        )
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        await tools["create_map"].func(name="大陆图")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_failure_records_audit(self) -> None:
        deps = _make_deps()
        deps.map_service.create_map = AsyncMock(side_effect=ValueError("boom"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        await tools["create_map"].func(name="大陆图")
        assert deps.audit_service.record.await_count >= 1
