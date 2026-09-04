"""#833 角色等级（role_rank）必填 + 枚举校验 + AI 工具传参 — RED 契约测试.

新契约（用户拍板，勿再问）：
- role_rank 存 `extra.role_rank`（零加列），五档枚举 protagonist/major/minor/scene/walkon.
- 创建/修改角色必须传 role_rank；非法值（非五档）→ 拒绝.
- AI 工具 `create_character` 必须补 role_rank 必填参数并透传 `extra['role_rank']`.

【RED 预期】旧实现：
- CharacterCreate/Update 不校验 role_rank → 缺失/非法不抛错（测试 FAIL）.
- CharacterCreateBody（API）不校验 role_rank → POST 缺 role_rank 仍 201（测试 FAIL）.
- character_service.create_character 对 extra 零校验 → 缺 role_rank 仍成功（测试 FAIL）.
- AI 工具 create_character 硬编码 extra=None → 不透传 role_rank（测试 FAIL）.

依据: specs/f43-setting-library-gui/spec.md §2.1（角色等级表 #833）+ §13 M10。
"""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from inkflow.api.app import app
from inkflow.domain.models.character import Character, CharacterCreate, CharacterUpdate
from inkflow.domain.ports.character_errors import CharacterServiceError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.services.character_service import CharacterService
from inkflow.infrastructure.agent.tools.setting_write_tools import (
    CreateCharacterParams,
    SettingWriteToolDeps,
    build_setting_write_tools,
)

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")

VALID_ROLE_RANKS = ["protagonist", "major", "minor", "scene", "walkon"]


def _make_service() -> CharacterService:
    """构造 CharacterService（全 Mock 依赖注入，仅测角色创建路径）。

    仅 repository 需要；extractor/project_repo 在 create_character 路径不被调用。
    """
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda c: c)
    return CharacterService(
        repository=repo,
        extractor=MagicMock(),
        project_repo=MagicMock(),
    )


def _make_tool_deps() -> SettingWriteToolDeps:
    """构造 AI 工具依赖（expected_project_id 绑定，create_character mock 返回 SimpleNamespace）。"""
    deps = SettingWriteToolDeps(
        character_service=AsyncMock(),
        world_service=AsyncMock(),
        outline_service=AsyncMock(),
        audit_service=AsyncMock(),
        expected_project_id=PID,
    )
    deps.character_service.create_character = AsyncMock(return_value=SimpleNamespace(id="char-1"))
    return deps


# ─── 1. CharacterCreate 模型：创建必须带合法 role_rank（T1/T2） ────────


class TestCharacterCreateRoleRank:
    """CharacterCreate 创建角色：缺 role_rank → 校验错误；非法值 → 校验错误；五档合法 → 成功."""

    def test_create_missing_role_rank_raises(self) -> None:
        """创建角色缺 role_rank → ValidationError（当前 FAIL：旧实现不校验 → 会成功）."""
        with pytest.raises(ValidationError):
            CharacterCreate(project_id=PID, name="林尘")

    def test_create_invalid_role_rank_raises(self) -> None:
        """role_rank 非法值（hacker，非五档）→ ValidationError，消息为「角色等级非法」而非「必填」.

        #859 回归：已提供但非法的值不应复用「必填」文案。当前 FAIL：旧实现报「角色等级必填」.
        """
        with pytest.raises(ValidationError) as exc_info:
            CharacterCreate(project_id=PID, name="林尘", extra={"role_rank": "hacker"})
        msgs = [e["msg"] for e in exc_info.value.errors()]
        assert any("角色等级非法" in m for m in msgs), f"应报「角色等级非法」，实际 {msgs}"

    def test_create_extra_without_role_rank_raises(self) -> None:
        """extra 存在但缺 role_rank 键 → ValidationError（当前 FAIL）."""
        with pytest.raises(ValidationError):
            CharacterCreate(project_id=PID, name="林尘", extra={"groups": ["主角团"]})

    def test_create_valid_role_ranks_succeed(self) -> None:
        """五档合法值 → 成功（happy-path 对照；旧实现已可存任意串，本契约锁定五档白名单）."""
        for value in VALID_ROLE_RANKS:
            created = CharacterCreate(project_id=PID, name="林尘", extra={"role_rank": value})
            assert created.extra["role_rank"] == value


# ─── 2. CharacterUpdate 模型：修改角色等级必须合法（T4） ────────────────


class TestCharacterUpdateRoleRank:
    """CharacterUpdate 修改角色等级：带非法值 → 校验错误；带合法值 → 允许并回读一致."""

    def test_update_invalid_role_rank_raises(self) -> None:
        """修改角色等级为非法值（hacker）→ ValidationError，消息为「角色等级非法」."""
        with pytest.raises(ValidationError) as exc_info:
            CharacterUpdate(extra={"role_rank": "hacker"})
        msgs = [e["msg"] for e in exc_info.value.errors()]
        assert any("角色等级非法" in m for m in msgs), f"应报「角色等级非法」，实际 {msgs}"

    def test_update_valid_role_rank_allowed_and_roundtrip(self) -> None:
        """修改角色等级为合法值 → 允许且回读一致（happy-path 对照）."""
        updated = CharacterUpdate(extra={"role_rank": "major"})
        assert updated.extra["role_rank"] == "major"


# ─── 3. 服务层 create_character：必填 + 枚举校验（brief 列为目标） ────────


class TestCharacterServiceRoleRank:
    """character_service.create_character：非法 role_rank → CharacterServiceError（422 语义）.

    注：服务层采用「validate-if-present」——对非法 role_rank 拒绝；缺失（extra 无该键）向后兼容
    （必填由 API body（CharacterCreateBody）+ 领域模型（CharacterCreate）保证）。
    """

    @pytest.mark.asyncio
    async def test_service_create_invalid_role_rank_raises(self) -> None:
        """创建角色服务入口 role_rank 非法值 → CharacterServiceError（当前 FAIL：零校验）."""
        service = _make_service()
        with pytest.raises(CharacterServiceError):
            await service.create_character(
                project_id=PID, name="林尘", extra={"role_rank": "hacker"}
            )

    @pytest.mark.asyncio
    async def test_service_create_valid_role_rank_persists(self) -> None:
        """创建角色服务入口合法 role_rank → 落库 extra.role_rank（happy-path 对照）."""
        service = _make_service()
        created = await service.create_character(
            project_id=PID, name="林尘", extra={"role_rank": "major"}
        )
        assert isinstance(created, Character)
        assert created.extra["role_rank"] == "major"


# ─── 4. AI 工具 create_character：补 role_rank 必填参数并透传 extra['role_rank']（T5） ────────


class TestCharacterToolRoleRank:
    """AI 工具 create_character：schema 必填 role_rank；调用透传 extra（当前 FAIL：extra=None）."""

    def test_tool_schema_requires_role_rank(self) -> None:
        """CreateCharacterParams schema 必须含 role_rank 且列入 required（当前 FAIL：无该字段）."""
        schema = CreateCharacterParams.model_json_schema()
        assert "role_rank" in schema["properties"]
        assert "role_rank" in schema["required"]

    @pytest.mark.asyncio
    async def test_tool_passes_role_rank_in_extra(self) -> None:
        """工具调用 create_character → 服务收到 extra={'role_rank': …}（当前 FAIL：extra=None）."""
        deps = _make_tool_deps()
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(await tools["create_character"].func(name="林晚"))
        assert result["ok"] is True
        call_args = deps.character_service.create_character.call_args
        assert call_args.kwargs["extra"] == {"role_rank": "major"}


# ─── 5. API（CharacterCreateBody）：POST 创建缺 role_rank → 422（brief 列为目标） ────────


class TestCharacterApiRoleRank:
    """API POST /characters：body 缺/非法 extra.role_rank → 422；带合法 → 201."""

    @staticmethod
    def _char(name: str = "林尘") -> Character:
        """构造可序列化 Character 实体（供 service mock 返回 201 用）. """
        return Character(
            id=uuid.uuid4(),
            project_id=PID,
            name=name,
            created_at=datetime(2026, 8, 1, 10, 0, 0),
            updated_at=datetime(2026, 8, 1, 10, 0, 0),
        )

    def test_api_create_missing_role_rank_422(self) -> None:
        """POST body 缺 extra.role_rank → 422 «角色等级必填»（语义锁定：缺失 → 必填）. """
        with _patch_get_service():
            response = client.post(
                f"/api/v1/projects/{PID}/characters", json={"name": "林尘"}
            )
        assert response.status_code == 422
        msgs = [d["msg"] for d in response.json()["detail"]]
        assert any("角色等级必填" in m for m in msgs), f"缺失应报「必填」，实际 {msgs}"

    def test_api_create_invalid_role_rank_422(self) -> None:
        """POST body extra.role_rank 非法值 → 422 «角色等级非法» 而非「必填」.

        #859 回归：已提供但非法的值不应复用「必填」文案。当前 FAIL：旧实现报「角色等级必填」.
        """
        with _patch_get_service():
            response = client.post(
                f"/api/v1/projects/{PID}/characters",
                json={"name": "林尘", "extra": {"role_rank": "hacker"}},
            )
        assert response.status_code == 422
        msgs = [d["msg"] for d in response.json()["detail"]]
        assert any("角色等级非法" in m for m in msgs), f"非法应报「角色等级非法」，实际 {msgs}"

    def test_api_create_valid_role_rank_201(self) -> None:
        """POST body 带合法 extra.role_rank → 201（happy-path 对照）. """
        with _patch_get_service() as mock_get_svc:
            mock_get_svc.return_value.create_character = AsyncMock(
                return_value=self._char()
            )
            response = client.post(
                f"/api/v1/projects/{PID}/characters",
                json={"name": "林尘", "extra": {"role_rank": "major"}},
            )
        assert response.status_code == 201


@contextlib.contextmanager
def _patch_get_service():
    """patch get_character_service；默认 service.* 为 AsyncMock，返回 Character 兜底. """
    from unittest.mock import patch

    with patch("inkflow.api.routers.characters.get_character_service") as mock_get_svc:
        svc = mock_get_svc.return_value
        svc.create_character = AsyncMock(return_value=Character(
            id=uuid.uuid4(),
            project_id=PID,
            name="林尘",
            created_at=datetime(2026, 8, 1, 10, 0, 0),
            updated_at=datetime(2026, 8, 1, 10, 0, 0),
        ))
        yield mock_get_svc
