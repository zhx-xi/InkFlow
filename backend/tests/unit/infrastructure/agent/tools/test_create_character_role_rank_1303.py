"""#1303 create_character 工具 role_rank 必填 RED 契约测试。

背景（#1303 实锤）: setting_write_tools.py 的 schema 与实现签名不一致:

    # CreateCharacterParams: role_rank 无默认值（必填）
    # _create_character: role_rank: str = "major"   ← 🔴 有默认值 → 静默兜底

LLM 省略该参数时角色被静默标为 major，用户不可见、无提示（错误等级比缺失等级更难发现）。

本文件锁定契约:
1. 不传 role_rank → 工具返回明确错误信封 {ok: False}（不静默落 major）；
2. 传 role_rank="minor" → 落库 extra["role_rank"] == "minor"（透传生效）；
3. schema 侧 role_rank 存在于 required（schema 是 LLM 可见契约，必须仍为必填）。

依据: issue #1303 + specs/f43-setting-library-gui/spec.md §2.1（#833 五档必填）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.infrastructure.agent.tools.setting_write_tools import (
    CREATE_CHARACTER_SPEC,
    SettingWriteToolDeps,
    build_setting_write_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


def _make_deps() -> SettingWriteToolDeps:
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    character_service = MagicMock()
    character_service.create_character = AsyncMock(return_value=SimpleNamespace(id="char-1"))
    return SettingWriteToolDeps(
        character_service=character_service,
        world_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PROJECT_ID,
    )


def _tools(deps: SettingWriteToolDeps):
    return {t.spec.name: t for t in build_setting_write_tools(deps)}


class TestCreateCharacterRoleRankRequired:
    """签名必填: 不传 role_rank 必须显式报错，不静默兜底 major."""

    def test_schema_declares_role_rank_required(self) -> None:
        """schema 侧 role_rank 在 required（LLM 可见契约保持必填）。"""
        schema = CREATE_CHARACTER_SPEC.input_schema
        assert "role_rank" in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_missing_role_rank_returns_error_envelope(self) -> None:
        """不传 role_rank → {ok: False} 信封（明确报错，不落 major）。"""
        deps = _make_deps()
        result = json.loads(await _tools(deps)["create_character"].func(name="林晚"))
        assert result["ok"] is False
        assert "role_rank" in result["error"]
        assert deps.character_service.create_character.await_count == 0

    @pytest.mark.asyncio
    async def test_explicit_role_rank_persisted(self) -> None:
        """传 role_rank="minor" → 透传 extra["role_rank"] == "minor"。"""
        deps = _make_deps()
        result = json.loads(
            await _tools(deps)["create_character"].func(name="林晚", role_rank="minor")
        )
        assert result["ok"] is True
        assert deps.character_service.create_character.await_args.kwargs["extra"] == {
            "role_rank": "minor"
        }

    @pytest.mark.asyncio
    async def test_illegal_role_rank_not_silently_accepted(self) -> None:
        """非法等级值 → {ok: False} 信封（service 层 #833 校验兜底，不静默）。"""
        deps = _make_deps()
        deps.character_service.create_character = AsyncMock(side_effect=ValueError("角色等级非法"))
        result = json.loads(
            await _tools(deps)["create_character"].func(name="林晚", role_rank="boss")
        )
        assert result["ok"] is False
        assert "角色等级非法" in result["error"]
