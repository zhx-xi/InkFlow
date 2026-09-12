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


class TestWorldRwToolOptionalFieldPassThrough:
    """#1137 覆盖补齐：id 规范化 + 可选字段透传（spec f26 §2.4-§2.6）."""

    @pytest.mark.asyncio
    async def test_list_maps_passes_uuid_root_location_through(self) -> None:
        """root_location_id 已是 uuid.UUID → 原样透传，不做二次解析。"""
        deps = _make_deps()
        deps.map_service.list_maps = AsyncMock(return_value=[])
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        root = uuid.uuid4()

        result = json.loads(await tools["list_maps"].func(root_location_id=root))

        assert result == {"ok": True, "data": []}
        call = deps.map_service.list_maps.await_args
        assert call.kwargs["root_location_id"] is root
        # 装配期绑定项目恒传 service（LLM 不自报项目，spec §2 统一约定）
        assert call.args[0] == PROJECT_ID

    @pytest.mark.asyncio
    async def test_list_maps_coerces_str_root_location_to_uuid(self) -> None:
        """root_location_id 为字符串 → 规范化为 uuid.UUID 后传 service。"""
        deps = _make_deps()
        deps.map_service.list_maps = AsyncMock(return_value=[])
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        root = uuid.uuid4()

        result = json.loads(await tools["list_maps"].func(root_location_id=str(root)))

        assert result == {"ok": True, "data": []}
        passed = deps.map_service.list_maps.await_args.kwargs["root_location_id"]
        assert passed == root
        assert isinstance(passed, uuid.UUID)

    @pytest.mark.asyncio
    async def test_list_maps_without_project_binding_passes_none(self) -> None:
        """装配期未绑定 + caller 未传 → 项目绑定值为 None（工具不编造项目 id）。"""
        deps = _make_deps()
        deps.expected_project_id = None
        deps.map_service.list_maps = AsyncMock(return_value=[])
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}

        result = json.loads(await tools["list_maps"].func())

        assert result == {"ok": True, "data": []}
        assert deps.map_service.list_maps.await_args.args[0] is None

    @pytest.mark.asyncio
    async def test_list_maps_service_error_returns_failure_envelope(self) -> None:
        """读类工具 service 异常 → {"ok": False, "error": ...}，不抛出（spec §2 约定）。"""
        deps = _make_deps()
        deps.map_service.list_maps = AsyncMock(side_effect=RuntimeError("map repo down"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}

        result = json.loads(await tools["list_maps"].func())

        assert result == {"ok": False, "error": "map repo down"}

    @pytest.mark.asyncio
    async def test_list_timeline_events_service_error_returns_failure_envelope(self) -> None:
        """时间线读取异常 → 失败信封；search 参数仍透传 service。"""
        deps = _make_deps()
        deps.timeline_service.list_events = AsyncMock(side_effect=RuntimeError("timeline down"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}

        result = json.loads(await tools["list_timeline_events"].func(search="开场"))

        assert result["ok"] is False
        assert "timeline down" in result["error"]
        assert deps.timeline_service.list_events.await_args.kwargs["search"] == "开场"

    @pytest.mark.asyncio
    async def test_update_map_forwards_description(self) -> None:
        """update_map 部分更新：description 传 service（spec §2.4），id 为 UUID 时直传。"""
        deps = _make_deps()
        deps.map_service.update_map = AsyncMock(return_value=SimpleNamespace(id="map-1"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        map_id = uuid.uuid4()

        result = json.loads(
            await tools["update_map"].func(map_id=map_id, name="大陆图", description="大陆图说明")
        )

        assert result == {"ok": True, "map_id": str(map_id)}
        call = deps.map_service.update_map.await_args
        assert call.args[0] == map_id
        assert call.args[1].name == "大陆图"
        assert call.args[1].description == "大陆图说明"

    @pytest.mark.asyncio
    async def test_update_map_missing_entity_returns_failure_envelope(self) -> None:
        """service 返回 None（实体不存在）→ 失败信封，不抛异常。"""
        deps = _make_deps()
        deps.map_service.update_map = AsyncMock(return_value=None)
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}

        result = json.loads(await tools["update_map"].func(map_id="map-1", name="大陆图"))

        assert result["ok"] is False
        assert "地图不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_update_map_skips_name_when_not_provided(self) -> None:
        """未传 name 的部分更新：name 字段不进入 DTO（spec §2.4 部分更新语义）。"""
        deps = _make_deps()
        deps.map_service.update_map = AsyncMock(return_value=SimpleNamespace(id="map-1"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}

        result = json.loads(
            await tools["update_map"].func(map_id="map-1", description="仅改说明")
        )

        assert result == {"ok": True, "map_id": "map-1"}
        update = deps.map_service.update_map.await_args.args[1]
        assert update.name is None
        assert update.description == "仅改说明"
        assert "name" not in update.model_fields_set

    @pytest.mark.asyncio
    async def test_update_timeline_event_forwards_optional_fields(self) -> None:
        """update_timeline_event 部分更新：description/time_value/narrative_position 透传。"""
        deps = _make_deps()
        deps.timeline_service.update_event = AsyncMock(return_value=SimpleNamespace(id="evt-1"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        event_id = uuid.uuid4()

        result = json.loads(
            await tools["update_timeline_event"].func(
                event_id=event_id,
                description="事件详述",
                time_value=12.5,
                narrative_position=3,
            )
        )

        assert result == {"ok": True, "event_id": str(event_id)}
        update = deps.timeline_service.update_event.await_args.args[1]
        assert update.description == "事件详述"
        assert update.time_value == 12.5
        assert update.narrative_position == 3

    @pytest.mark.asyncio
    async def test_create_foreshadowing_forwards_optional_fields(self) -> None:
        """create_foreshadowing：description/priority/location/event_id 透传（spec §2.6）。"""
        deps = _make_deps()
        deps.foreshadowing_service.create = AsyncMock(return_value=SimpleNamespace(id="fsh-1"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        event_id = uuid.uuid4()

        result = json.loads(
            await tools["create_foreshadowing"].func(
                title="玉佩",
                description="林晚的玉佩",
                priority=80,
                location="第 3 章",
                event_id=event_id,
            )
        )

        assert result == {"ok": True, "foreshadowing_id": "fsh-1"}
        created = deps.foreshadowing_service.create.await_args.args[0]
        assert created.project_id == PROJECT_ID
        assert created.description == "林晚的玉佩"
        assert created.priority == 80
        assert created.location == "第 3 章"
        assert created.event_id == event_id

    @pytest.mark.asyncio
    async def test_update_foreshadowing_forwards_optional_fields(self) -> None:
        """update_foreshadowing：description/priority/location/event_id 透传（spec §2.6）。"""
        deps = _make_deps()
        deps.foreshadowing_service.update = AsyncMock(return_value=SimpleNamespace(id="fsh-1"))
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        foreshadowing_id = uuid.uuid4()
        event_id = uuid.uuid4()

        result = json.loads(
            await tools["update_foreshadowing"].func(
                foreshadowing_id=foreshadowing_id,
                description="改详述",
                priority=20,
                location="第 5 章",
                event_id=event_id,
            )
        )

        assert result == {"ok": True, "foreshadowing_id": str(foreshadowing_id)}
        call = deps.foreshadowing_service.update.await_args
        assert call.args[0] == foreshadowing_id
        assert call.args[1].description == "改详述"
        assert call.args[1].priority == 20
        assert call.args[1].location == "第 5 章"
        assert call.args[1].event_id == event_id
