"""Coverage backfill batch 2: AgentEntityService grants 授权矩阵分支。

Mock 注入 AgentRepositoryProtocol（镜像 test_agent_entity_service），经公开
create/update 驱动：
- 同 domain 重复授予 -> GrantValidationError（222-223）
- grants 与 tool_ids 同时传入 -> GrantValidationError（253-254 / 319-320）
- 仅 grants -> 校验并清空 tool_ids（255-258 / 328-330）
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent import Agent, AgentCreate, AgentUpdate
from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
from inkflow.domain.ports.agent_errors import GrantValidationError
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.services.agent_entity_service import AgentEntityService

TS = datetime(2026, 8, 1, 10, 0, 0)


def _agent(agent_id: int, name: str, **kw) -> Agent:
    return Agent(id=agent_id, name=name, created_at=TS, updated_at=TS, **kw)


def _grant(domain: ToolDomain) -> GrantEntry:
    return GrantEntry(domain=domain, ops=[ToolOp.READ])


@pytest.fixture
def mock_agent_repo() -> MagicMock:
    repo = MagicMock(spec=AgentRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda a: a)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda a: a)
    repo.delete = AsyncMock(return_value=True)
    repo.list_agents_by_skill = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def service(mock_agent_repo: MagicMock, tmp_path: Path) -> AgentEntityService:
    root = tmp_path / "skills"
    root.mkdir()
    return AgentEntityService(agent_repository=mock_agent_repo, skills_root=root)


@pytest.mark.asyncio
async def test_create_rejects_duplicate_grant_domain(
    service, mock_agent_repo
) -> None:
    """同一 domain 重复授予 -> GrantValidationError，不落库（222-223）。"""
    grants = [_grant(ToolDomain.OUTLINE), _grant(ToolDomain.OUTLINE)]

    with pytest.raises(GrantValidationError):
        await service.create(AgentCreate(name="重复授权", grants=grants))

    mock_agent_repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rejects_grants_and_tool_ids_together(
    service, mock_agent_repo
) -> None:
    """grants 与 tool_ids 同时传入 -> GrantValidationError（253-254）。"""
    with pytest.raises(GrantValidationError):
        await service.create(
            AgentCreate(
                name="双授权",
                grants=[_grant(ToolDomain.OUTLINE)],
                tool_ids=[],
            )
        )

    mock_agent_repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_with_grants_clears_tool_ids(service, mock_agent_repo) -> None:
    """仅传 grants -> 校验通过、tool_ids 置空后落库（255-258）。"""
    grants = [_grant(ToolDomain.OUTLINE), _grant(ToolDomain.WRITING)]

    saved = await service.create(AgentCreate(name="授权角色", grants=grants))

    assert [g.domain for g in saved.grants] == [ToolDomain.OUTLINE, ToolDomain.WRITING]
    assert saved.tool_ids == []
    mock_agent_repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_rejects_grants_and_tool_ids_together(
    service, mock_agent_repo
) -> None:
    """update 同时传 grants 与 tool_ids -> GrantValidationError（319-320）。"""
    mock_agent_repo.get.return_value = _agent(7, "旧名")

    with pytest.raises(GrantValidationError):
        await service.update(
            7,
            AgentUpdate(grants=[_grant(ToolDomain.OUTLINE)], tool_ids=[]),
        )

    mock_agent_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_with_grants_syncs_tool_ids(service, mock_agent_repo) -> None:
    """update 仅传 grants -> 校验通过且 tool_ids 同步清空（328-330）。"""
    mock_agent_repo.get.return_value = _agent(7, "旧名")

    updated = await service.update(7, AgentUpdate(grants=[_grant(ToolDomain.MEMORY)]))

    assert [g.domain for g in updated.grants] == [ToolDomain.MEMORY]
    assert updated.tool_ids == []
