"""KnowledgeGraphService 数据面变更事件测试（#1090 批次 B；spec §15.3.2/§15.3.3/§15.6.4）。

契约来源：W3C 设计裁定表 §2.5（父侧单一真相源）+ spec §15.3.3 四不变量。
- create_relation / update_relation 成功 → knowledge_relation/create|update（project_id 非 None）。
- delete_relation：get_relation 已加载实体（spec §15.3.2 反例先例点名）→ project_id 非 None；
  关系不存在 → KnowledgeRelationNotFoundError（零发布）；repo.delete 返回 False → 零发布。
- bulk_create_relations：批量完成发**一条**域级事件（resource_id=str(project_id)，§15.6.4
  防 N 条风暴）；created 空（全部同键跳过）→ 不发。
- cleanup_for_entity：签名无 project_id（实体级联清理）→ deleted>0 时发
  (resource_id=str(entity_id), project_id=None)，deleted==0 → 不发。

⚠️ 本模块 logger 为 loguru（非 stdlib logging），caplog 不捕获其记录 →
cleanup_for_entity 只断言事件四元组，不断言 warning 文案（设计表 §2.5 的 warning
落地由 GREEN 侧保证，不在此以 caplog 锁）。

依赖全 Mock 注入（镜像 test_knowledge_graph_service.py 的 fixture 形态）。
RED 阶段预期：正例断言 FAIL，负例可能已 PASS。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import Character
from inkflow.domain.models.knowledge_graph import (
    EntityType,
    KnowledgeRelation,
    KnowledgeRelationCreate,
)
from inkflow.domain.models.project import Project
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.knowledge_graph_errors import (
    KnowledgeRelationNotFoundError,
)
from inkflow.domain.ports.knowledge_relation_repository import (
    KnowledgeRelationRepositoryProtocol,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _char(name: str = "林尘", *, project_id: uuid.UUID = PID) -> Character:
    """构造测试用角色实体（create_relation 的 source/target 校验对象）。"""
    return Character(
        id=uuid.uuid4(), project_id=project_id, name=name, created_at=TS, updated_at=TS
    )


def _relation(
    source: Character, target: Character, *, relation_type: str = "挚友"
) -> KnowledgeRelation:
    """构造测试用图谱关系实体（固定时间戳，便于断言）。"""
    return KnowledgeRelation(
        id=uuid.uuid4(),
        project_id=PID,
        source_type=EntityType.CHARACTER,
        source_id=source.id,
        target_type=EntityType.CHARACTER,
        target_id=target.id,
        relation_type=relation_type,
        created_at=TS,
        updated_at=TS,
    )


def _dto(
    source: Character, target: Character, *, relation_type: str = "挚友"
) -> KnowledgeRelationCreate:
    """构造批量写入用 DTO。"""
    return KnowledgeRelationCreate(
        source_type=EntityType.CHARACTER,
        source_id=source.id,
        target_type=EntityType.CHARACTER,
        target_id=target.id,
        relation_type=relation_type,
    )


@pytest.fixture
def mock_relation_repo() -> MagicMock:
    """Mock KnowledgeRelationRepositoryProtocol — 默认全方法可用。"""
    repo = MagicMock(spec=KnowledgeRelationRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda r: r)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_key = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.filter = AsyncMock(return_value=([], 0))
    repo.list_by_project = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda r: r)
    repo.delete = AsyncMock(return_value=True)
    repo.delete_by_entity = AsyncMock(return_value=0)
    repo.cleanup_for_entity = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — get 默认 = 项目存在。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(
        return_value=Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)
    )
    return repo


@pytest.fixture
def mock_character_repo() -> MagicMock:
    """Mock CharacterRepositoryProtocol — 实体校验（默认按 id 命中角色）。"""
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(side_effect=lambda cid: _char())
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_relations = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def service(
    mock_relation_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_character_repo: MagicMock,
) -> KnowledgeGraphService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return KnowledgeGraphService(
        relation_repo=mock_relation_repo,
        project_repo=mock_project_repo,
        character_repo=mock_character_repo,
    )


class TestRelationCrudDataChange:
    """knowledge_relation 单条 CRUD 写路径发布事件。"""

    async def test_create_relation_publishes_create(
        self, service: KnowledgeGraphService, mock_character_repo: MagicMock, recorded_events
    ) -> None:
        """create_relation 成功 → knowledge_relation/create，project_id 取形参。"""
        source = _char("林尘")
        target = _char("苏瑶")
        mock_character_repo.get = AsyncMock(
            side_effect=lambda cid: source if cid == source.id.int else target
        )

        created = await service.create_relation(
            PID, "character", source.id, "character", target.id, "挚友"
        )

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("knowledge_relation", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_relation_project_missing_publishes_nothing(
        self,
        service: KnowledgeGraphService,
        mock_project_repo: MagicMock,
        recorded_events,
    ) -> None:
        """反例：项目不存在（写失败）→ 零发布。"""
        mock_project_repo.get = AsyncMock(return_value=None)

        with pytest.raises(ProjectNotFoundError):
            await service.create_relation(
                PID, "character", uuid.uuid4(), "character", uuid.uuid4(), "挚友"
            )

        assert recorded_events == []

    async def test_update_relation_publishes_update(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """update_relation 成功 → knowledge_relation/update，project_id 从已加载实体解析。"""
        relation = _relation(_char("林尘"), _char("苏瑶"))
        mock_relation_repo.get = AsyncMock(return_value=relation)
        mock_relation_repo.get_by_key = AsyncMock(return_value=relation)

        updated = await service.update_relation(relation.id, description="并肩作战")

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("knowledge_relation", "update")
        assert event.resource_id == str(relation.id)
        assert event.project_id == str(PID)

    async def test_update_relation_missing_publishes_nothing(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """反例：关系不存在（404 异常）→ 零发布。"""
        mock_relation_repo.get = AsyncMock(return_value=None)

        with pytest.raises(KnowledgeRelationNotFoundError):
            await service.update_relation(uuid.uuid4(), description="并肩作战")

        assert recorded_events == []

    async def test_delete_relation_publishes_delete_with_entity_project_id(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """delete_relation 已加载实体（非薄透传）→ project_id 非 None（§15.3.2 反例先例）。"""
        relation = _relation(_char("林尘"), _char("苏瑶"))
        mock_relation_repo.get = AsyncMock(return_value=relation)

        assert await service.delete_relation(relation.id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("knowledge_relation", "delete")
        assert event.resource_id == str(relation.id)
        assert event.project_id == str(PID)

    async def test_delete_relation_missing_publishes_nothing(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """反例：关系不存在（404 异常）→ 零发布。"""
        mock_relation_repo.get = AsyncMock(return_value=None)

        with pytest.raises(KnowledgeRelationNotFoundError):
            await service.delete_relation(uuid.uuid4())

        assert recorded_events == []

    async def test_delete_relation_repo_false_publishes_nothing(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """反例：repo.delete 返回 False（写失败）→ 零发布。"""
        relation = _relation(_char("林尘"), _char("苏瑶"))
        mock_relation_repo.get = AsyncMock(return_value=relation)
        mock_relation_repo.delete = AsyncMock(return_value=False)

        assert await service.delete_relation(relation.id) is False
        assert recorded_events == []


class TestBulkAndCleanupDataChange:
    """批量写入与实体级联清理的域级事件契约。"""

    async def test_bulk_create_relations_publishes_single_domain_event(
        self, service: KnowledgeGraphService, recorded_events
    ) -> None:
        """批量创建非空 → 恰好**一条**域级事件（resource_id=str(project_id)，防 N 条风暴）。"""
        source = _char("林尘")
        target = _char("苏瑶")
        created = await service.bulk_create_relations(
            PID, [_dto(source, target), _dto(source, target, relation_type="师徒")]
        )

        assert len(created) == 2
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("knowledge_relation", "create")
        assert event.resource_id == str(PID)
        assert event.project_id == str(PID)

    async def test_bulk_create_relations_empty_publishes_nothing(
        self, service: KnowledgeGraphService, recorded_events
    ) -> None:
        """反例：created 空（无待写入行）→ 零发布。"""
        created = await service.bulk_create_relations(PID, [])

        assert created == []
        assert recorded_events == []

    async def test_bulk_create_relations_all_skipped_publishes_nothing(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """反例：全部同键跳过（created 空）→ 零发布。"""
        source = _char("林尘")
        target = _char("苏瑶")
        mock_relation_repo.get_by_key = AsyncMock(return_value=_relation(source, target))

        created = await service.bulk_create_relations(PID, [_dto(source, target)])

        assert created == []
        assert recorded_events == []

    async def test_cleanup_for_entity_publishes_entity_level_delete(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """deleted>0 → 实体级 delete：resource_id=str(entity_id)，project_id=None（安全偏向）。"""
        entity_id = uuid.uuid4()
        mock_relation_repo.cleanup_for_entity = AsyncMock(return_value=2)

        assert await service.cleanup_for_entity(EntityType.CHARACTER, entity_id) == 2

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("knowledge_relation", "delete")
        assert event.resource_id == str(entity_id)
        assert event.project_id is None

    async def test_cleanup_for_entity_zero_deleted_publishes_nothing(
        self, service: KnowledgeGraphService, mock_relation_repo: MagicMock, recorded_events
    ) -> None:
        """反例：deleted==0（无变化）→ 零发布。"""
        mock_relation_repo.cleanup_for_entity = AsyncMock(return_value=0)

        assert await service.cleanup_for_entity("character", uuid.uuid4()) == 0
        assert recorded_events == []
