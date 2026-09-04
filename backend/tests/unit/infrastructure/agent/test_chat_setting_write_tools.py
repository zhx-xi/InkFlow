"""#748 设定库写入工具 RED 契约测试 — build_setting_write_tools 注册 + 执行信封.

背景（#748 实锤）: chat agent 只注册 [readers, save_draft]，AI 调用 create_character /
create_world_setting / create_outline 等设定库写入工具时工具不存在 → 卡 running。
本文件锁定契约:
1. build_setting_write_tools(deps) 返回 [create_character, create_world_setting, create_outline]。
2. 每个 func 执行成功返回 {"ok": True, "<entity>_id": "<id>", ...} 信封（不抛出）。
3. 每个 func 执行失败（service 抛异常）返回 {"ok": False, "error": "<msg>"} 信封（不抛出）。
4. expected_project_id 绑定：装配期注入后，func 总是使用绑定值（LLM 不自报项目 ID）。
5. 成功/失败均落审计（audit_service.record），审计自身异常静默。
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.infrastructure.agent.tools.setting_write_tools import (
    SettingWriteToolDeps,
    build_setting_write_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
FOREIGN_PROJECT_ID = "00000000-0000-0000-0000-000000000000"


def _make_deps() -> SettingWriteToolDeps:
    """构造 SettingWriteToolDeps（audit_service.record 为 AsyncMock 防 await 失败）。"""
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return SettingWriteToolDeps(
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PROJECT_ID,
    )


class TestBuildSettingWriteTools:
    """build_setting_write_tools 注册三个设定库写入工具。"""

    def test_registers_three_tools(self) -> None:
        """工具面：create_character / create_world_setting / create_outline。"""
        tools = build_setting_write_tools(_make_deps())
        assert [t.spec.name for t in tools] == [
            "create_character",
            "create_world_setting",
            "create_outline",
        ]

    @pytest.mark.asyncio
    async def test_create_character_success_envelope(self) -> None:
        """create_character 成功 → {"ok": True, "character_id": "<id>"}。"""
        deps = _make_deps()
        deps.character_service.create_character = AsyncMock(
            return_value=SimpleNamespace(id="char-1")
        )
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(await tools["create_character"].func(name="林晚"))
        assert result["ok"] is True
        assert result["character_id"] == "char-1"

    @pytest.mark.asyncio
    async def test_create_character_failure_envelope(self) -> None:
        """service 抛异常 → {"ok": False, "error": "..."}（工具内部吞异常不抛出）。"""
        deps = _make_deps()
        deps.character_service.create_character = AsyncMock(
            side_effect=ValueError("同名角色已存在")
        )
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(await tools["create_character"].func(name="林晚"))
        assert result["ok"] is False
        assert "同名角色已存在" in result["error"]

    @pytest.mark.asyncio
    async def test_create_world_setting_success_envelope(self) -> None:
        """create_world_setting 成功 → {"ok": True, "setting_id": "<id>"}。"""
        deps = _make_deps()
        deps.world_service.create_setting = AsyncMock(
            return_value=SimpleNamespace(id="world-1")
        )
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(await tools["create_world_setting"].func(name="天元大陆"))
        assert result["ok"] is True
        assert result["setting_id"] == "world-1"

    @pytest.mark.asyncio
    async def test_create_outline_success_envelope(self) -> None:
        """create_outline 成功 → {"ok": True, "outline_id": "<id>"}。"""
        deps = _make_deps()
        deps.outline_service.create_outline = AsyncMock(
            return_value=SimpleNamespace(id="outline-1")
        )
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(await tools["create_outline"].func(name="第一卷大纲"))
        assert result["ok"] is True
        assert result["outline_id"] == "outline-1"

    @pytest.mark.asyncio
    async def test_expected_project_id_binding(self) -> None:
        """装配期绑定 expected_project_id：caller 传入的 project_id 被忽略，恒用绑定值。"""
        deps = _make_deps()
        deps.character_service.create_character = AsyncMock(
            return_value=SimpleNamespace(id="c1")
        )
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        await tools["create_character"].func(
            name="林晚", project_id=FOREIGN_PROJECT_ID
        )
        args, kwargs = deps.character_service.create_character.call_args
        used_project_id = kwargs.get("project_id") or (args[0] if args else None)
        assert str(used_project_id) == str(PROJECT_ID)


class TestSettingWriteToolAudit:
    """成功/失败均落审计（约束③），审计异常静默不影响主返回。"""

    @pytest.mark.asyncio
    async def test_success_records_audit(self) -> None:
        deps = _make_deps()
        deps.character_service.create_character = AsyncMock(
            return_value=SimpleNamespace(id="char-1")
        )
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        await tools["create_character"].func(name="林晚")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_failure_records_audit(self) -> None:
        deps = _make_deps()
        deps.character_service.create_character = AsyncMock(
            side_effect=ValueError("boom")
        )
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        await tools["create_character"].func(name="林晚")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_break_result(self) -> None:
        """audit_service.record 抛异常 → 被抑制，主返回信封不受影响。"""
        deps = _make_deps()
        deps.character_service.create_character = AsyncMock(
            return_value=SimpleNamespace(id="char-1")
        )
        deps.audit_service.record = AsyncMock(side_effect=RuntimeError("audit down"))
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(await tools["create_character"].func(name="林晚"))
        assert result["ok"] is True
        assert result["character_id"] == "char-1"
