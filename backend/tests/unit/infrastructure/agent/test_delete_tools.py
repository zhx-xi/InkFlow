"""#766 阶段② 删除工具 RED 契约测试 — build_delete_tools 注册 + 执行信封.

#955 迁移（RED-B）: 删除表 +delete_plot_point 行（`outline_service.delete_point`，
实体 id = plot_point_id），工具数 7→8。core 标记（is_core=True）由本批 registry
测试与 test_outline_grant_migration.py 覆盖。

依据 specs/f26-agent-tools/spec.md §6.1/§6.2 + ADR-043 §2-§3。镜像 test_writing_tools 形态。
锁定契约:
1. build_delete_tools(deps) 返回 8 个删除工具（顺序固定）:
   delete_character / delete_world_setting / delete_outline / delete_plot_point /
   delete_map / delete_timeline_event / delete_foreshadowing / memory_remove。
2. 成功 {"ok": True, "<entity>_id": "<id>"}；失败 {"ok": False, "error": "..."}。
3. 成功/失败均落审计（audit_service.record，actor="agent:chat"），审计异常静默。
4. service 返回 False（记录不存在）→ 失败信封（防假成功）。
5. project_id 不出现在 schema（deps.expected_project_id 仅供审计绑定；删除服务
   方法只按实体 id 删除——源码核实 2026-08-30）。
6. 删除授权：deps.auth（ToolAuth）决定行为；本文件一律 auto（直接执行，
   interrupt 分支见 test_delete_hitl.py）。

源码核实（spec §6.1 表列的 hard_delete/delete_preference 为简写，实际方法名 2026-08-30）:
- character_service.delete_character(character_id)
- world_service.delete_setting(setting_id)
- outline_service.delete_outline(outline_id)
- outline_service.delete_point(plot_point_id)   # #955 新
- map_service.delete_map(map_id)
- timeline_service.delete_event(event_id)
- foreshadowing_service.delete(foreshadowing_id)
- memory_service.remove_preference(preference_id)

RED 形态: delete_plot_point 未注册/`_DELETE_TOOL_TABLE` 缺该行 → 计数 7≠8 FAILED。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent_tools import ToolAuth
from inkflow.infrastructure.agent.tools.delete_tools import (
    DeleteToolDeps,
    build_delete_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")

# (工具名, deps 服务字段, service 方法名, 实体 id 参数名)
# #955 迁移: delete_outline 行后插 delete_plot_point 行（并行 `_DELETE_TOOL_TABLE` 位置）
DELETE_TOOL_CASES = [
    ("delete_character", "character_service", "delete_character", "character_id"),
    ("delete_world_setting", "world_service", "delete_setting", "setting_id"),
    ("delete_outline", "outline_service", "delete_outline", "outline_id"),
    ("delete_plot_point", "outline_service", "delete_point", "plot_point_id"),  # #955 新
    ("delete_map", "map_service", "delete_map", "map_id"),
    ("delete_timeline_event", "timeline_service", "delete_event", "event_id"),
    ("delete_foreshadowing", "foreshadowing_service", "delete", "foreshadowing_id"),
    ("memory_remove", "memory_service", "remove_preference", "preference_id"),
]

EXPECTED_NAMES = [case[0] for case in DELETE_TOOL_CASES]


def _make_deps() -> DeleteToolDeps:
    """构造删除工具依赖：全部 service 用 MagicMock，auth=auto（直接执行）。"""
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
        auth=ToolAuth(delete_permission="auto"),
        expected_project_id=PROJECT_ID,
    )


def _mock_service(deps: DeleteToolDeps, tool_name: str, return_value: object = True) -> AsyncMock:
    """按 DELETE_TOOL_CASES 给对应 service 方法挂 AsyncMock（默认返回 True）。"""
    _tool_name, svc_field, method_name, _entity_key = next(
        c for c in DELETE_TOOL_CASES if c[0] == tool_name
    )
    method = AsyncMock(return_value=return_value)
    setattr(getattr(deps, svc_field), method_name, method)
    return method


class TestBuildDeleteTools:
    """build_delete_tools 注册 8 个删除工具（顺序固定，#955 迁移 7→8）。"""

    def test_registers_eight_tools(self) -> None:
        tools = build_delete_tools(_make_deps())
        assert [t.spec.name for t in tools] == EXPECTED_NAMES

    def test_tool_specs_have_input_schema(self) -> None:
        for t in build_delete_tools(_make_deps()):
            assert isinstance(t.spec.input_schema, dict)
            assert "type" in t.spec.input_schema

    def test_schema_excludes_project_id(self) -> None:
        """project_id 由装配期绑定（deps.expected_project_id），不出现在 schema。"""
        for t in build_delete_tools(_make_deps()):
            assert "project_id" not in t.spec.input_schema.get("properties", {})


class TestDeleteToolSuccessEnvelope:
    """8 工具正例：service 删除成功 → ok=True 信封 + 审计。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,svc_field,method_name,entity_key", DELETE_TOOL_CASES)
    async def test_success_envelope(self, tool_name, svc_field, method_name, entity_key) -> None:
        deps = _make_deps()
        method = _mock_service(deps, tool_name)
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        entity_id = "550e8400-e29b-41d4-a716-44665544000a"
        result = json.loads(await tools[tool_name].func(**{entity_key: entity_id}))
        assert result["ok"] is True
        assert str(result[entity_key]) == entity_id
        # 删除方法被调用一次（以实体 id 删除）
        method.assert_awaited_once()
        # 成功落审计（写类工具统一约定）
        assert deps.audit_service.record.await_count >= 1


class TestDeleteToolFailureEnvelope:
    """8 工具反例：service 抛异常 → ok=False 错误信封。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,svc_field,method_name,entity_key", DELETE_TOOL_CASES)
    async def test_service_raises(self, tool_name, svc_field, method_name, entity_key) -> None:
        deps = _make_deps()
        _mock_service(deps, tool_name, return_value=None)
        method = getattr(getattr(deps, svc_field), method_name)
        method.side_effect = ValueError("记录不存在")
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        result = json.loads(await tools[tool_name].func(**{entity_key: "x"}))
        assert result["ok"] is False
        assert "记录不存在" in result["error"]


class TestDeleteToolNotFound:
    """service 返回 False（记录不存在）→ 失败信封，防假成功。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,svc_field,method_name,entity_key", DELETE_TOOL_CASES)
    async def test_service_returns_false(
        self, tool_name, svc_field, method_name, entity_key
    ) -> None:
        deps = _make_deps()
        _mock_service(deps, tool_name, return_value=False)
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        result = json.loads(await tools[tool_name].func(**{entity_key: "x"}))
        assert result["ok"] is False
        assert result["error"]


class TestDeleteToolAudit:
    """成功/失败均落审计；审计异常静默不影响主返回。"""

    @pytest.mark.asyncio
    async def test_audit_uses_bound_project_id(self) -> None:
        deps = _make_deps()
        _mock_service(deps, "delete_character")
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        await tools["delete_character"].func(character_id="550e8400-e29b-41d4-a716-44665544000a")
        call = deps.audit_service.record.await_args
        assert call.kwargs["actor"] == "agent:chat"
        assert str(call.kwargs["project_id"]) == str(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_failure_records_audit(self) -> None:
        deps = _make_deps()
        _mock_service(deps, "delete_character")
        method = deps.character_service.delete_character
        method.side_effect = ValueError("boom")
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        await tools["delete_character"].func(character_id="x")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_audit_exception_silent(self) -> None:
        deps = _make_deps()
        _mock_service(deps, "delete_character")
        deps.audit_service.record = AsyncMock(side_effect=RuntimeError("audit down"))
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        result = json.loads(await tools["delete_character"].func(character_id="x"))
        assert result["ok"] is True  # 审计异常不影响主返回


class TestDeleteCoerceUuid:
    """delete_tools._coerce_uuid 规范化 uuid.UUID（str 解析 / UUID 直传双路径）。"""

    def test_coerce_uuid_uuid_passthrough(self) -> None:
        """uuid.UUID 实例直传 → 原实例原样返回（模块私有 helper 分支补测）。"""
        from inkflow.infrastructure.agent.tools.delete_tools import _coerce_uuid

        assert _coerce_uuid(PROJECT_ID) is PROJECT_ID

    def test_coerce_uuid_str_parsed(self) -> None:
        """str 输入 → 解析为 uuid.UUID（与 agent_chain_tools 同源 #275 语义）。"""
        from inkflow.infrastructure.agent.tools.delete_tools import _coerce_uuid

        assert _coerce_uuid(str(PROJECT_ID)) == PROJECT_ID


class TestDeleteToolUuidEntityId:
    """entity_id 为 uuid.UUID 实例（非 str 形态）→ 原值透传删除服务。"""

    @pytest.mark.asyncio
    async def test_uuid_entity_id_passthrough(self) -> None:
        deps = _make_deps()
        method = _mock_service(deps, "delete_character")
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        entity_uuid = uuid.UUID("550e8400-e29b-41d4-a716-44665544000d")
        result = json.loads(await tools["delete_character"].func(character_id=entity_uuid))
        assert result["ok"] is True
        method.assert_awaited_once()
        assert method.await_args.args[0] is entity_uuid

    @pytest.mark.asyncio
    async def test_unbound_project_id_skips_uuid_resolution(self) -> None:
        """expected_project_id 与 func project_id 均缺省 → 跳过绑定项目 UUID 解析（None 分支）。"""
        deps = _make_deps()
        deps.expected_project_id = None
        method = _mock_service(deps, "delete_character")
        tools = {t.spec.name: t for t in build_delete_tools(deps)}
        result = json.loads(await tools["delete_character"].func(character_id="x"))
        assert result["ok"] is True
        method.assert_awaited_once()
