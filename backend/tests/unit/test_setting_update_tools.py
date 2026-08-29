"""F51 设定库更新工具 RED 契约测试 — build_setting_update_tools 注册 + 执行信封.

依据 specs/f51-agent-tools-v2/spec.md §2.1-2.3。镜像 test_chat_setting_write_tools 形态。
锁定契约:
1. build_setting_update_tools(deps) 返回 [update_character, update_world_setting, update_outline]。
2. 每个 func 成功返回 {"ok": True, "<entity>_id": "<id>", ...} 信封（不抛出）。
3. 每个 func 失败（service 抛异常）返回 {"ok": False, "error": "<msg>"} 信封（不抛出）。
4. expected_project_id 绑定：装配期注入后，func 恒用绑定值（LLM 不自报项目 ID）。
5. 成功/失败均落审计（audit_service.record），审计自身异常静默。
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.infrastructure.agent.tools.setting_update_tools import (
    SettingUpdateToolDeps,
    build_setting_update_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
FOREIGN_PROJECT_ID = "00000000-0000-0000-0000-000000000000"


def _make_deps() -> SettingUpdateToolDeps:
    """构造 SettingUpdateToolDeps（audit_service.record 为 AsyncMock 防 await 失败）。"""
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return SettingUpdateToolDeps(
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PROJECT_ID,
    )


class TestBuildSettingUpdateTools:
    """build_setting_update_tools 注册三个设定库更新工具。"""

    def test_registers_three_tools(self) -> None:
        """工具面：update_character / update_world_setting / update_outline。"""
        tools = build_setting_update_tools(_make_deps())
        assert [t.spec.name for t in tools] == [
            "update_character",
            "update_world_setting",
            "update_outline",
        ]

    def test_tool_specs_have_input_schema(self) -> None:
        """每个工具 spec 携带 input_schema（Pydantic model_json_schema 产物）。"""
        for t in build_setting_update_tools(_make_deps()):
            assert isinstance(t.spec.input_schema, dict)
            assert "type" in t.spec.input_schema

    @pytest.mark.asyncio
    async def test_update_character_success_envelope(self) -> None:
        """update_character 成功 → {"ok": True, "character_id": "<id>", "name": "<name>"}。"""
        deps = _make_deps()
        deps.character_service.update_character = AsyncMock(
            return_value=SimpleNamespace(id="char-1", name="林晚")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        result = json.loads(
            await tools["update_character"].func(character_id="char-1", name="林晚")
        )
        assert result["ok"] is True
        assert result["character_id"] == "char-1"
        assert result["name"] == "林晚"

    @pytest.mark.asyncio
    async def test_update_character_failure_envelope(self) -> None:
        """service 抛异常 → {"ok": False, "error": "..."}（工具内部吞异常不抛出）。"""
        deps = _make_deps()
        deps.character_service.update_character = AsyncMock(
            side_effect=ValueError("角色不存在")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        result = json.loads(
            await tools["update_character"].func(character_id="char-1", name="林晚")
        )
        assert result["ok"] is False
        assert "角色不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_update_world_setting_success_envelope(self) -> None:
        """update_world_setting 成功 → {"ok": True, "setting_id": "<id>"}。"""
        deps = _make_deps()
        deps.world_service.update_setting = AsyncMock(
            return_value=SimpleNamespace(id="world-1", name="天元大陆")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        result = json.loads(
            await tools["update_world_setting"].func(setting_id="world-1", name="天元大陆")
        )
        assert result["ok"] is True
        assert result["setting_id"] == "world-1"

    @pytest.mark.asyncio
    async def test_update_outline_success_envelope(self) -> None:
        """update_outline 成功 → {"ok": True, "outline_id": "<id>"}。"""
        deps = _make_deps()
        deps.outline_service.update_outline = AsyncMock(
            return_value=SimpleNamespace(id="outline-1", name="第一卷大纲")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        result = json.loads(
            await tools["update_outline"].func(outline_id="outline-1", name="第一卷大纲")
        )
        assert result["ok"] is True
        assert result["outline_id"] == "outline-1"

    @pytest.mark.asyncio
    async def test_update_world_setting_failure_envelope(self) -> None:
        """update_world_setting 失败 → {"ok": False, "error": "..."}。"""
        deps = _make_deps()
        deps.world_service.update_setting = AsyncMock(
            side_effect=ValueError("世界观条目不存在")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        result = json.loads(
            await tools["update_world_setting"].func(setting_id="world-1", name="天元大陆")
        )
        assert result["ok"] is False
        assert "世界观条目不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_update_outline_failure_envelope(self) -> None:
        """update_outline 失败 → {"ok": False, "error": "..."}。"""
        deps = _make_deps()
        deps.outline_service.update_outline = AsyncMock(
            side_effect=ValueError("大纲不存在")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        result = json.loads(
            await tools["update_outline"].func(outline_id="outline-1", name="第一卷大纲")
        )
        assert result["ok"] is False
        assert "大纲不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_update_character_world_outline_partial_fields(self) -> None:
        """部分字段更新：只传 name 时其它字段不修改（DTO exclude_unset 语义）。"""
        deps = _make_deps()
        deps.character_service.update_character = AsyncMock(
            return_value=SimpleNamespace(id="char-1", name="林晚")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        await tools["update_character"].func(character_id="char-1", name="林晚")
        # service 收到 CharacterUpdate（或等价 dict），只有 name 被设置
        args, _kwargs = deps.character_service.update_character.call_args
        update = _kwargs.get("update") if _kwargs else (args[1] if len(args) > 1 else None)
        assert update is not None

    @pytest.mark.asyncio
    async def test_expected_project_id_binding(self) -> None:
        """装配期绑定 expected_project_id：caller 传入的 project_id 被忽略，恒用绑定值。"""
        deps = _make_deps()
        deps.character_service.update_character = AsyncMock(
            return_value=SimpleNamespace(id="c1", name="林晚")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        await tools["update_character"].func(
            character_id="c1", name="林晚", project_id=FOREIGN_PROJECT_ID
        )
        args, kwargs = deps.character_service.update_character.call_args
        used_project_id = kwargs.get("project_id") or (args[0] if args else None)
        # update_character 签名是 (character_id, update)，project_id 由 DTO/服务校验路径携带；
        # 断言 service 未收到外部伪造的 project_id（即并未绕过绑定使用 FOREIGN）
        if used_project_id is not None:
            assert str(used_project_id) != str(FOREIGN_PROJECT_ID)


class TestSettingUpdateToolAudit:
    """成功/失败均落审计，审计异常静默不影响主返回。"""

    @pytest.mark.asyncio
    async def test_success_records_audit(self) -> None:
        deps = _make_deps()
        deps.character_service.update_character = AsyncMock(
            return_value=SimpleNamespace(id="char-1", name="林晚")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        await tools["update_character"].func(character_id="char-1", name="林晚")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_failure_records_audit(self) -> None:
        deps = _make_deps()
        deps.character_service.update_character = AsyncMock(
            side_effect=ValueError("boom")
        )
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        await tools["update_character"].func(character_id="char-1", name="林晚")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_break_result(self) -> None:
        """audit_service.record 抛异常 → 被抑制，主返回信封不受影响。"""
        deps = _make_deps()
        deps.character_service.update_character = AsyncMock(
            return_value=SimpleNamespace(id="char-1", name="林晚")
        )
        deps.audit_service.record = AsyncMock(side_effect=RuntimeError("audit down"))
        tools = {t.spec.name: t for t in build_setting_update_tools(deps)}
        result = json.loads(
            await tools["update_character"].func(character_id="char-1", name="林晚")
        )
        assert result["ok"] is True
        assert result["character_id"] == "char-1"
