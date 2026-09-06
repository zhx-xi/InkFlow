"""#850 AI 工具 create_world_setting category strip RED 契约测试.

锁定契约（当前实现工具路径未 strip category → 守卫按 strip 后命名校验但落库
原始值（含空白）→ 幽灵分类）:
1. 工具传 "设定 " → 透传给 world_service.create_setting 的 category 为 "设定"（strip）
2. 工具路径 root-conflict → {ok:False} 信封含根错误文案（`WorldRootConflictError`）

依据: issue #850 + specs/f10-world-settings/spec.md §7（工具路径与 router 层一致）.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.world_errors import WorldRootConflictError
from inkflow.infrastructure.agent.tools.setting_write_tools import (
    SettingWriteToolDeps,
    build_setting_write_tools,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _make_tool_deps() -> SettingWriteToolDeps:
    """构造工具依赖（world_service.create_setting 默认成功返回实体）. """
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return SettingWriteToolDeps(
        character_service=MagicMock(),
        world_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PID,
    )


@pytest.mark.asyncio
async def test_create_world_setting_tool_strips_category() -> None:
    """工具传 "设定 " → 透传给 create_setting 的 category 为 "设定"（strip）.

    当前实现 FAIL：工具直接透传原始 category（含尾部空白）→ 守卫按 strip 后名校验、
    落库「设定 」幽灵分类.
    """
    deps = _make_tool_deps()
    setting = WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name="宗门等级体系",
        category="设定",
        content="",
        parent_id=None,
        created_at=TS,
        updated_at=TS,
    )
    deps.world_service.create_setting = AsyncMock(return_value=setting)
    tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
    result = json.loads(
        await tools["create_world_setting"].func(name="宗门等级体系", category="设定 ")
    )
    assert result["ok"] is True
    assert result["name"] == "宗门等级体系"
    # 落库 category 必须是 strip 后值（无尾部空白）
    deps.world_service.create_setting.assert_awaited_once_with(
        project_id=PID,
        name="宗门等级体系",
        category="设定",
        content="",
        parent_id=None,
    )


@pytest.mark.asyncio
async def test_create_world_setting_tool_root_conflict_returns_ok_false() -> None:
    """工具路径 root-conflict → {ok:False} 信封含根错误文案.

    当前实现 PASS：工具 catch Exception 返回 {ok:False, error: str(exc)}；契约确认.
    """
    deps = _make_tool_deps()
    deps.world_service.create_setting = AsyncMock(side_effect=WorldRootConflictError())
    tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
    result = json.loads(await tools["create_world_setting"].func(name="灵气复苏"))
    assert result["ok"] is False
    assert "根" in result["error"]
