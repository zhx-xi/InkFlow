"""CharacterService 数据面变更事件测试（#1088 批 A3；spec §15.3.2/§15.3.3）。

自 test_character_service.py 拆出（守 900 行护栏，同 #281 测试文件规模治理先例）：
character / character_relation / character_group 三个项目域——A 类取形参，
B 类从已加载实体解析 project_id；薄透传方法（delete_character / delete_group）
发 None + warning（spec §15.3.2 已知例外）。

依赖全 Mock 注入（镜像 test_character_service.py 的 fixture 形态）。
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
from inkflow.domain.models.project import Project
from inkflow.domain.ports.character_errors import CharacterNameConflictError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services.character_service import CharacterService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_OTHER = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _char(
    name: str,
    *,
    personality: str = "",
    background: str = "",
    goals: str = "",
    group_ids: list[uuid.UUID] | None = None,
    project_id: uuid.UUID = PID,
) -> Character:
    """构造测试用角色实体（固定时间戳，便于断言）。"""
    return Character(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        personality=personality,
        background=background,
        goals=goals,
        group_ids=group_ids or [],
        created_at=TS,
        updated_at=TS,
    )


def _group(name: str, *, project_id: uuid.UUID = PID, sort_order: int = 0) -> CharacterGroup:
    """构造测试用分组实体。"""
    return CharacterGroup(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        sort_order=sort_order,
        created_at=TS,
        updated_at=TS,
    )


def _rel(
    from_char: Character,
    to_char: Character,
    *,
    relation_type: str,
    description: str = "",
) -> CharacterRelation:
    """构造测试用关系实体。"""
    return CharacterRelation(
        id=uuid.uuid4(),
        project_id=from_char.project_id,
        from_character_id=from_char.id,
        to_character_id=to_char.id,
        relation_type=relation_type,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock CharacterRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda c: c)
    repo.update = AsyncMock(side_effect=lambda c: c)
    repo.soft_delete = AsyncMock(return_value=True)
    repo.hard_delete = AsyncMock(return_value=True)
    repo.add_group = AsyncMock(side_effect=lambda g: g)
    repo.get_group = AsyncMock(return_value=None)
    repo.list_groups = AsyncMock(return_value=[])
    repo.update_group = AsyncMock(side_effect=lambda g: g)
    repo.soft_delete_group = AsyncMock(return_value=True)
    repo.hard_delete_group = AsyncMock(return_value=True)
    repo.add_relation = AsyncMock(side_effect=lambda r: r)
    repo.get_relation = AsyncMock(return_value=None)
    repo.get_relation_by_key = AsyncMock(return_value=None)
    repo.list_relations = AsyncMock(return_value=[])
    repo.update_relation = AsyncMock(side_effect=lambda r: r)
    repo.soft_delete_relation = AsyncMock(return_value=True)
    repo.hard_delete_relation = AsyncMock(return_value=True)
    repo.soft_delete_relations_of = AsyncMock(return_value=None)
    return repo


def _project(*, project_id: uuid.UUID = PID) -> Project:
    """构造测试用项目实体（create_* 项目存在性校验 mock 返回）."""
    return Project(id=project_id, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 项目存在性校验（get 默认 = 项目存在）.

    #1138 起 create_group 落库前校验项目存在，故默认返回真实 Project。
    """
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def mock_extractor() -> MagicMock:
    """Mock CharacterExtractor — extract 入口的管线调用。"""
    extractor = MagicMock(spec=CharacterExtractor)
    extractor.extract = AsyncMock()
    return extractor


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_extractor: MagicMock,
) -> CharacterService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return CharacterService(
        repository=mock_repo,
        extractor=mock_extractor,
        project_repo=mock_project_repo,
    )


class TestDataChangeEvents:
    """#1088 批 A3：角色域写路径发布事件（项目域；B 类从已加载实体解析 project_id）。"""

    async def test_create_character_publishes_create(
        self, service, mock_repo, recorded_events
    ) -> None:
        """A 类：create_character 成功 → character/create，project_id 取形参。"""
        created = await service.create_character(project_id=PID, name="林尘")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("character", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_character_conflict_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：同名冲突（写失败）→ 不发布。"""
        mock_repo.get_by_name = AsyncMock(return_value=_char(name="林尘"))

        with pytest.raises(CharacterNameConflictError):
            await service.create_character(project_id=PID, name="林尘")

        assert recorded_events == []

    async def test_update_character_publishes_update_with_entity_project_id(
        self, service, mock_repo, recorded_events
    ) -> None:
        """B 类：update_character 成功 → character/update，project_id 非 None。"""
        mock_repo.get = AsyncMock(return_value=_char(name="林尘"))

        updated = await service.update_character(uuid.uuid4(), CharacterUpdate(personality="坚韧"))

        assert updated is not None
        assert len(recorded_events) == 1
        assert (recorded_events[0].domain, recorded_events[0].op) == ("character", "update")
        assert recorded_events[0].project_id == str(PID)

    async def test_update_character_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：角色不存在（返回 None）→ 不发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        assert (
            await service.update_character(uuid.uuid4(), CharacterUpdate(personality="坚韧"))
            is None
        )
        assert recorded_events == []

    async def test_delete_character_publishes_none_project_id_with_warning(
        self, service, mock_repo, recorded_events, caplog
    ) -> None:
        """delete_character 未加载实体（薄透传）→ None + warning（spec §15.3.2 已知例外）。"""
        character_id = uuid.uuid4()
        caplog.set_level("WARNING", logger="inkflow.domain.services.character_service")

        assert await service.delete_character(character_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("character", "delete")
        assert event.resource_id == str(character_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_character_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：角色不存在（返回 False）→ 不发布。"""
        mock_repo.hard_delete = AsyncMock(return_value=False)

        assert await service.delete_character(uuid.uuid4()) is False
        assert recorded_events == []

    async def test_create_relation_publishes_with_start_character_project(
        self, service, mock_repo, recorded_events
    ) -> None:
        """character_relation/create：project_id 从已加载的起点角色推出。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        mock_repo.get = AsyncMock(side_effect=[from_char, to_char])

        relation = await service.create_relation(from_char.id, to_char.id, "挚友")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("character_relation", "create")
        assert event.resource_id == str(relation.id)
        assert event.project_id == str(PID)

    async def test_update_relation_publishes_update(
        self, service, mock_repo, recorded_events
    ) -> None:
        """character_relation/update：Relation 实体在更新前已加载 → project_id 非 None。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        relation = _rel(from_char, to_char, relation_type="挚友")
        mock_repo.get_relation = AsyncMock(return_value=relation)

        updated = await service.update_relation(from_char.id, relation.id, description="并肩作战")

        assert updated is not None
        assert len(recorded_events) == 1
        assert (recorded_events[0].domain, recorded_events[0].op) == (
            "character_relation",
            "update",
        )
        assert recorded_events[0].project_id == str(PID)

    async def test_delete_relation_publishes_delete(
        self, service, mock_repo, recorded_events
    ) -> None:
        """character_relation/delete：Relation 实体已加载（非薄透传）→ project_id 非 None。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        relation = _rel(from_char, to_char, relation_type="挚友")
        mock_repo.get_relation = AsyncMock(return_value=relation)

        assert await service.delete_relation(from_char.id, relation.id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("character_relation", "delete")
        assert event.resource_id == str(relation.id)
        assert event.project_id == str(PID)

    async def test_delete_relation_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：关系不存在（返回 False）→ 不发布。"""
        mock_repo.get_relation = AsyncMock(return_value=None)

        assert await service.delete_relation(uuid.uuid4(), uuid.uuid4()) is False
        assert recorded_events == []

    async def test_create_group_publishes_create(self, service, mock_repo, recorded_events) -> None:
        """A 类：create_group 成功 → character_group/create，project_id 取形参。"""
        group = await service.create_group(PID, "主角团")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("character_group", "create")
        assert event.resource_id == str(group.id)
        assert event.project_id == str(PID)

    async def test_update_group_publishes_update(self, service, mock_repo, recorded_events) -> None:
        """B 类：update_group 成功 → character_group/update，project_id 非 None。"""
        mock_repo.get_group = AsyncMock(return_value=_group(name="主角团"))

        updated = await service.update_group(uuid.uuid4(), name="核心角色")

        assert updated is not None
        assert len(recorded_events) == 1
        assert (recorded_events[0].domain, recorded_events[0].op) == (
            "character_group",
            "update",
        )
        assert recorded_events[0].project_id == str(PID)

    async def test_update_group_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：分组不存在（返回 None）→ 不发布。"""
        mock_repo.get_group = AsyncMock(return_value=None)

        assert await service.update_group(uuid.uuid4(), name="核心角色") is None
        assert recorded_events == []

    async def test_delete_group_publishes_none_project_id_with_warning(
        self, service, mock_repo, recorded_events, caplog
    ) -> None:
        """delete_group 未加载实体（薄透传）→ None + warning（spec §15.3.2 已知例外）。"""
        group_id = uuid.uuid4()
        caplog.set_level("WARNING", logger="inkflow.domain.services.character_service")

        assert await service.delete_group(group_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("character_group", "delete")
        assert event.resource_id == str(group_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_group_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：分组不存在（返回 False）→ 不发布。"""
        mock_repo.hard_delete_group = AsyncMock(return_value=False)

        assert await service.delete_group(uuid.uuid4()) is False
        assert recorded_events == []
