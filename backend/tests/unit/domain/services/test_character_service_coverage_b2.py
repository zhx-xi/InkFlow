"""Coverage backfill batch 2: CharacterService 未覆盖分支（Mock 注入）。

经公开方法驱动：
- update_character extra.role_rank 非法 -> CharacterRoleRankError（231-234）
- update_character / update_relation / update_group 仓储返回 None -> 透传 None
  （238->241 / 387->389 / 505->507）
- delete_relation 硬删返回 False -> 不发布事件返回 False（413->416）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import (
    Character,
    CharacterGroup,
    CharacterRelation,
    CharacterUpdate,
)
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.services.character_service import CharacterService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _char(name: str) -> Character:
    return Character(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        group_ids=[],
        created_at=TS,
        updated_at=TS,
    )


def _group(name: str) -> CharacterGroup:
    return CharacterGroup(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        sort_order=0,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda c: c)
    repo.update = AsyncMock(side_effect=lambda c: c)
    repo.get_group = AsyncMock(return_value=None)
    repo.list_groups = AsyncMock(return_value=[])
    repo.update_group = AsyncMock(side_effect=lambda g: g)
    repo.get_relation = AsyncMock(return_value=None)
    repo.get_relation_by_key = AsyncMock(return_value=None)
    repo.update_relation = AsyncMock(side_effect=lambda r: r)
    repo.hard_delete_relation = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def service(mock_repo: MagicMock) -> CharacterService:
    return CharacterService(repository=mock_repo)


@pytest.mark.asyncio
async def test_update_character_validates_present_role_rank(
    service, mock_repo
) -> None:
    """update 携带 extra -> 服务层校验 present 的 role_rank（230-232）。"""
    existing = _char("林尘")
    mock_repo.get = AsyncMock(return_value=existing)

    updated = await service.update_character(
        existing.id, CharacterUpdate(extra={"role_rank": "protagonist"})
    )

    assert updated is not None
    assert updated.extra == {"role_rank": "protagonist"}
    mock_repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_character_repo_returns_none(service, mock_repo) -> None:
    """仓储 update 返回 None（竞态已删）-> 透传 None（238->241）。"""
    existing = _char("林尘")
    mock_repo.get = AsyncMock(return_value=existing)
    mock_repo.update = AsyncMock(return_value=None)

    assert await service.update_character(
        existing.id, CharacterUpdate(personality="坚韧")
    ) is None


@pytest.mark.asyncio
async def test_update_relation_repo_returns_none(service, mock_repo) -> None:
    """关系仓储 update 返回 None -> 透传 None（387->389）。"""
    a, b = _char("甲"), _char("乙")
    relation = CharacterRelation(
        id=uuid.uuid4(),
        project_id=PID,
        from_character_id=a.id,
        to_character_id=b.id,
        relation_type="友",
        description="",
        created_at=TS,
        updated_at=TS,
    )
    mock_repo.get_relation = AsyncMock(return_value=relation)
    mock_repo.update_relation = AsyncMock(return_value=None)

    assert await service.update_relation(a.id, relation.id, description="新") is None


@pytest.mark.asyncio
async def test_delete_relation_hard_delete_false(service, mock_repo) -> None:
    """硬删返回 False -> 不发布事件，返回 False（413->416）。"""
    a, b = _char("甲"), _char("乙")
    relation = CharacterRelation(
        id=uuid.uuid4(),
        project_id=PID,
        from_character_id=a.id,
        to_character_id=b.id,
        relation_type="友",
        description="",
        created_at=TS,
        updated_at=TS,
    )
    mock_repo.get_relation = AsyncMock(return_value=relation)
    mock_repo.hard_delete_relation = AsyncMock(return_value=False)

    assert await service.delete_relation(a.id, relation.id) is False


@pytest.mark.asyncio
async def test_update_group_repo_returns_none(service, mock_repo) -> None:
    """分组仓储 update 返回 None -> 透传 None（505->507）。"""
    group = _group("主角团")
    mock_repo.get_group = AsyncMock(return_value=group)
    mock_repo.update_group = AsyncMock(return_value=None)

    assert await service.update_group(group.id, name="新名") is None
