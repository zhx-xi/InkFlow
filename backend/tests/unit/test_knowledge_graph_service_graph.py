"""F48 知识图谱 — knowledge_graph_service 契约测试（兄弟文件）。

F48 900 行护栏拆分（F43 P2 先例）：TestGraph/Cleanup/BulkCreate 自主文件
test_knowledge_graph_service.py 迁出，fixtures/helpers 副本独立（不 import
主文件——pytest fixture 跨文件不可见 + 循环依赖）。

契约内容（构造签名/方法契约/§7 边界）见主文件 test_knowledge_graph_service.py
文件头 docstring，本文件仅承载迁出的 TestGraph/TestCleanup/TestBulkCreate 与
错误类层次契约，行为与拆分前完全一致（34 用例总数不变）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import Character, CharacterRelation
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.knowledge_graph import (
    EntityType,
    KnowledgeGraphView,
    KnowledgeRelation,
    KnowledgeRelationCreate,
    RelationSource,
)
from inkflow.domain.models.map import MapPin, WorldMap
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.knowledge_graph_errors import (
    KnowledgeEntityNotFoundError,
    KnowledgeGraphServiceError,
    KnowledgeRelationConflictError,
    KnowledgeRelationNotFoundError,
    KnowledgeRelationSelfLoopError,
    KnowledgeRelationValidationError,
)
from inkflow.domain.ports.knowledge_relation_repository import KnowledgeRelationRepositoryProtocol
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_OTHER = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
# ── 测试实体构造器 ─────────────────────────────────────────────────


def _char(name: str, *, project_id: uuid.UUID = PID) -> Character:
    """构造测试用角色实体."""
    return Character(
        id=uuid.uuid4(), project_id=project_id, name=name, created_at=TS, updated_at=TS
    )


def _world(name: str, *, project_id: uuid.UUID = PID) -> WorldSetting:
    """构造测试用世界观条目实体."""
    return WorldSetting(
        id=uuid.uuid4(), project_id=project_id, name=name, created_at=TS, updated_at=TS
    )


def _outline(name: str, *, project_id: uuid.UUID = PID) -> Outline:
    """构造测试用大纲实体."""
    return Outline(id=uuid.uuid4(), project_id=project_id, name=name, created_at=TS, updated_at=TS)


def _event(title: str, *, project_id: uuid.UUID = PID) -> TimelineEvent:
    """构造测试用时间线事件实体."""
    return TimelineEvent(
        id=uuid.uuid4(), project_id=project_id, title=title, created_at=TS, updated_at=TS
    )


def _foreshadow(title: str, *, project_id: uuid.UUID = PID) -> Foreshadowing:
    """构造测试用伏笔实体."""
    return Foreshadowing(
        id=uuid.uuid4(), project_id=project_id, title=title, created_at=TS, updated_at=TS
    )


def _map(name: str, *, project_id: uuid.UUID = PID) -> WorldMap:
    """构造测试用地图实体."""
    return WorldMap(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        image_path="",
        created_at=TS,
        updated_at=TS,
    )


def _pin(label: str, *, map_id: uuid.UUID) -> MapPin:
    """构造测试用地图 pin 实体."""
    return MapPin(
        id=uuid.uuid4(),
        map_id=map_id,
        x=10.0,
        y=20.0,
        label=label,
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    """构造测试用项目实体."""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


def _kr(
    *,
    source_type: str = "character",
    source_id: uuid.UUID,
    target_type: str = "world",
    target_id: uuid.UUID,
    relation_type: str,
    description: str = "",
    source: str = "manual",
    created_at: datetime = TS,
) -> KnowledgeRelation:
    """构造测试用图谱关系实体（source 默认 manual——v1.0 创建恒 manual）."""
    return KnowledgeRelation(
        id=uuid.uuid4(),
        project_id=PID,
        source_type=EntityType(source_type),
        source_id=source_id,
        target_type=EntityType(target_type),
        target_id=target_id,
        relation_type=relation_type,
        description=description,
        source=RelationSource(source),
        created_at=created_at,
        updated_at=created_at,
    )


def _cr(
    from_char: Character,
    to_char: Character,
    *,
    relation_type: str,
    created_at: datetime = TS,
) -> CharacterRelation:
    """构造测试用 F9 角色关系实体（图谱合并段数据源）."""
    return CharacterRelation(
        id=uuid.uuid4(),
        project_id=PID,
        from_character_id=from_char.id,
        to_character_id=to_char.id,
        relation_type=relation_type,
        created_at=created_at,
        updated_at=created_at,
    )


# ── Mock fixtures ─────────────────────────────────────────────────


@pytest.fixture
def mock_relation_repo() -> MagicMock:
    """Mock KnowledgeRelationRepositoryProtocol — 默认全方法可用，测试按需覆盖."""
    repo = MagicMock(spec=KnowledgeRelationRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda r: r)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_key = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.filter = AsyncMock(return_value=([], 0))
    repo.update = AsyncMock(side_effect=lambda r: r)
    repo.delete = AsyncMock(return_value=True)
    repo.list_by_project = AsyncMock(return_value=[])
    repo.delete_by_entity = AsyncMock(return_value=0)
    repo.cleanup_for_entity = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — create 入口校验项目存在性."""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_character_repo() -> MagicMock:
    """Mock CharacterRepositoryProtocol — 实体校验（get）+ 图谱节点（list）+
    合并段（list_relations）."""
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_relations = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_world_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 世界观实体校验 + 图谱节点."""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    return repo


@pytest.fixture
def mock_outline_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol — 大纲实体校验 + 图谱节点."""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    return repo


@pytest.fixture
def mock_timeline_repo() -> MagicMock:
    """Mock TimelineRepositoryProtocol — 时间线事件校验 + 图谱节点."""
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    return repo


@pytest.fixture
def mock_foreshadow_repo() -> MagicMock:
    """Mock ForeshadowingRepositoryProtocol — 伏笔校验 + 图谱节点."""
    repo = MagicMock(spec=ForeshadowingRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    return repo


@pytest.fixture
def mock_map_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — map_pin 校验链路（get_pin + get）+
    图谱节点（list_maps_by_project + list_pins）."""
    repo = MagicMock(spec=MapRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_pin = AsyncMock(return_value=None)
    repo.list_pins = AsyncMock(return_value=[])
    repo.list_maps_by_project = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def service(
    mock_relation_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_character_repo: MagicMock,
    mock_world_repo: MagicMock,
    mock_outline_repo: MagicMock,
    mock_timeline_repo: MagicMock,
    mock_foreshadow_repo: MagicMock,
    mock_map_repo: MagicMock,
) -> KnowledgeGraphService:
    """被测服务实例（全 Mock 依赖注入，镜像 deps 装配面）."""
    return KnowledgeGraphService(
        relation_repo=mock_relation_repo,
        project_repo=mock_project_repo,
        character_repo=mock_character_repo,
        world_repo=mock_world_repo,
        outline_repo=mock_outline_repo,
        timeline_repo=mock_timeline_repo,
        foreshadow_repo=mock_foreshadow_repo,
        map_repo=mock_map_repo,
    )

class TestGraph:
    """graph 图谱聚合（spec §5.2/§5.6 + §7 边界 10/13/14）."""

    async def test_empty_project_returns_empty_graph(self, service):
        """空项目图谱 → nodes=[] + edges=[]（§7 边界 14，空图谱合法）."""
        view = await service.graph(PID)
        assert isinstance(view, KnowledgeGraphView)
        assert view.nodes == []
        assert view.edges == []

    async def test_nodes_six_types_grouped_name_sorted(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_outline_repo,
        mock_timeline_repo,
        mock_foreshadow_repo,
        mock_map_repo,
    ):
        """nodes 六类实体全量；组序 character→world→outline→timeline→foreshadow→map_pin；
        组内 name ASC（§5.6；服务层排序——mock 注入乱序数据验证）。"""
        char_b, char_a = _char("B角色"), _char("A角色")
        world = _world("清河县")
        outline_b, outline_a = _outline("B大纲"), _outline("A大纲")
        event = _event("序章")
        foreshadow = _foreshadow("身世伏笔")
        wm = _map("大陆图")
        pin_b, pin_a = _pin("B地", map_id=wm.id), _pin("A地", map_id=wm.id)

        mock_character_repo.list = AsyncMock(return_value=([char_b, char_a], 2))
        mock_world_repo.list = AsyncMock(return_value=([world], 1))
        mock_outline_repo.list = AsyncMock(return_value=([outline_b, outline_a], 2))
        mock_timeline_repo.list = AsyncMock(return_value=([event], 1))
        mock_foreshadow_repo.list = AsyncMock(return_value=([foreshadow], 1))
        mock_map_repo.list_maps_by_project = AsyncMock(return_value=[wm])
        mock_map_repo.list_pins = AsyncMock(return_value=[pin_b, pin_a])

        view = await service.graph(PID)

        assert [n.type for n in view.nodes] == [
            EntityType.CHARACTER,
            EntityType.CHARACTER,
            EntityType.WORLD,
            EntityType.OUTLINE,
            EntityType.OUTLINE,
            EntityType.TIMELINE,
            EntityType.FORESHADOW,
            EntityType.MAP_PIN,
            EntityType.MAP_PIN,
        ]
        # 组内 name ASC（A 在 B 前，Unicode 码点序）
        assert [n.name for n in view.nodes] == [
            "A角色",
            "B角色",
            "清河县",
            "A大纲",
            "B大纲",
            "序章",
            "身世伏笔",
            "A地",
            "B地",
        ]
        # 节点 ID 格式 "<entity_type>:<entity_uuid>"（§2.4）
        assert view.nodes[0].id == f"character:{char_a.id}"
        assert view.nodes[0].entity_id == char_a.id
        assert view.nodes[-1].id == f"map_pin:{pin_b.id}"  # name ASC：B地在末尾
        assert view.nodes[-1].entity_id == pin_b.id
        assert view.nodes[3].name == "A大纲"  # Outline.name 映射
        assert view.nodes[5].name == "序章"  # TimelineEvent.title 映射
        mock_character_repo.list.assert_awaited_once_with(PID.int)
        mock_map_repo.list_maps_by_project.assert_awaited_once_with(PID.int)
        mock_map_repo.list_pins.assert_awaited_once_with(wm.id.int)

    async def test_edges_merge_knowledge_and_character_relations(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """edges 合并 knowledge_relations ∪ character_relations，
        source_table 正确（§5.2/§9 场景 4）."""
        char_a, char_b = _char("林尘"), _char("阿澈")
        world_w = _world("清河县")
        mock_character_repo.list = AsyncMock(return_value=([char_a, char_b], 2))
        mock_world_repo.list = AsyncMock(return_value=([world_w], 1))
        kr = _kr(source_id=char_a.id, target_id=world_w.id, relation_type="属于")
        cr = _cr(char_a, char_b, relation_type="师徒")
        mock_relation_repo.list_by_project = AsyncMock(return_value=[kr])
        mock_character_repo.list_relations = AsyncMock(return_value=[cr])

        view = await service.graph(PID)

        assert len(view.edges) == 2
        kr_edge = next(e for e in view.edges if e.source_table == "knowledge_relations")
        cr_edge = next(e for e in view.edges if e.source_table == "character_relations")
        assert kr_edge.id == f"kr:{kr.id}"
        assert kr_edge.source == f"character:{char_a.id}"
        assert kr_edge.target == f"world:{world_w.id}"
        assert kr_edge.label == "属于"
        assert kr_edge.description == ""
        assert cr_edge.id == f"cr:{cr.id}"
        assert cr_edge.source == f"character:{char_a.id}"
        assert cr_edge.target == f"character:{char_b.id}"
        assert cr_edge.label == "师徒"
        mock_relation_repo.list_by_project.assert_awaited_once_with(PID.int)
        mock_character_repo.list_relations.assert_awaited_once_with(PID.int)

    async def test_edges_dedup_knowledge_priority(
        self,
        service,
        mock_character_repo,
        mock_relation_repo,
    ):
        """同键（source+target+label）两表都出现 → 只显示 knowledge_relations 行，cr
        行折叠（§5.2/Q1=A）."""
        char_a, char_b = _char("林尘"), _char("阿澈")
        mock_character_repo.list = AsyncMock(return_value=([char_a, char_b], 2))
        kr = _kr(
            source_type="character",
            source_id=char_a.id,
            target_type="character",
            target_id=char_b.id,
            relation_type="师徒",
        )
        cr = _cr(char_a, char_b, relation_type="师徒")
        mock_relation_repo.list_by_project = AsyncMock(return_value=[kr])
        mock_character_repo.list_relations = AsyncMock(return_value=[cr])

        view = await service.graph(PID)

        assert len(view.edges) == 1
        assert view.edges[0].id == f"kr:{kr.id}"
        assert view.edges[0].source_table == "knowledge_relations"
        assert not any(e.id.startswith("cr:") for e in view.edges)

    async def test_orphan_edges_skipped_no_error(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """孤立边（实体已删但关系残留）→ 跳过该边 + 不抛错（§7 边界 10，mock 实体 repo 返回
        None/空）."""
        char_a = _char("林尘")
        world_w = _world("清河县")
        mock_character_repo.list = AsyncMock(return_value=([char_a], 1))
        mock_world_repo.list = AsyncMock(return_value=([world_w], 1))
        valid_kr = _kr(source_id=char_a.id, target_id=world_w.id, relation_type="属于")
        orphan_kr = _kr(
            source_type="character",
            source_id=uuid.uuid4(),  # 实体不存在于 nodes
            target_type="world",
            target_id=uuid.uuid4(),
            relation_type="悬空边",
        )
        mock_relation_repo.list_by_project = AsyncMock(return_value=[valid_kr, orphan_kr])
        mock_character_repo.list_relations = AsyncMock(return_value=[])

        view = await service.graph(PID)  # 不 500

        assert [e.id for e in view.edges] == [f"kr:{valid_kr.id}"]

    async def test_edges_ordered_kr_before_cr_created_at_asc(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """边排序：knowledge 段在前、character 段在后，组内 created_at ASC（§5.6；mock
        注入乱序验证）."""
        char_a, char_b = _char("林尘"), _char("阿澈")
        world_w = _world("清河县")
        mock_character_repo.list = AsyncMock(return_value=([char_a, char_b], 2))
        mock_world_repo.list = AsyncMock(return_value=([world_w], 1))
        kr_early = _kr(
            source_id=char_a.id,
            target_id=world_w.id,
            relation_type="属于",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        kr_late = _kr(
            source_type="world",
            source_id=world_w.id,
            target_type="character",
            target_id=char_a.id,
            relation_type="位于",
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        cr = _cr(
            char_a,
            char_b,
            relation_type="师徒",
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        # 注入乱序（服务层需按 created_at ASC 组内重排）
        mock_relation_repo.list_by_project = AsyncMock(return_value=[kr_late, kr_early])
        mock_character_repo.list_relations = AsyncMock(return_value=[cr])

        view = await service.graph(PID)

        assert [e.id for e in view.edges] == [
            f"kr:{kr_early.id}",
            f"kr:{kr_late.id}",
            f"cr:{cr.id}",
        ]

class TestCleanup:
    """cleanup_for_entity 级联清理回调（spec §5.3/§9 场景 7）."""

    async def test_delegates_to_relation_repo(self, service, mock_relation_repo):
        """实体硬删 → cleanup_for_entity(entity_type, entity_id) 委托 repo（int 主键 +
        枚举转字符串）."""
        mock_relation_repo.cleanup_for_entity = AsyncMock(return_value=2)
        ent_id = uuid.uuid4()

        deleted = await service.cleanup_for_entity(EntityType.CHARACTER, ent_id)
        assert deleted == 2
        mock_relation_repo.cleanup_for_entity.assert_awaited_once_with("character", ent_id.int)

        await service.cleanup_for_entity("world", ent_id)
        mock_relation_repo.cleanup_for_entity.assert_awaited_with("world", ent_id.int)

    async def test_minimal_service_backward_compat(self, mock_relation_repo):
        """默认 None 依赖向后兼容（§5.3 决策 3）：仅注入 relation_repo 也能清理与空图谱查询."""
        svc = KnowledgeGraphService(relation_repo=mock_relation_repo)

        assert await svc.cleanup_for_entity("character", 123) == 0
        view = await svc.graph(PID)
        assert view.nodes == []
        assert view.edges == []
        mock_relation_repo.cleanup_for_entity.assert_awaited_once_with("character", 123)

class TestBulkCreate:
    """bulk_create_relations 预留端口（spec §5.5/#479 面，§9 测试策略）."""

    async def test_single_transaction_source_ai(self, service, mock_relation_repo):
        """批量写入：source 默认 ai；每行 add 落库并返回."""
        dto1 = KnowledgeRelationCreate(
            source_type="character",
            source_id=uuid.uuid4(),
            target_type="world",
            target_id=uuid.uuid4(),
            relation_type="属于",
        )
        dto2 = KnowledgeRelationCreate(
            source_type="character",
            source_id=uuid.uuid4(),
            target_type="outline",
            target_id=uuid.uuid4(),
            relation_type="参与",
        )

        created = await service.bulk_create_relations(PID, [dto1, dto2])

        assert len(created) == 2
        assert all(r.source == RelationSource.AI for r in created)
        assert mock_relation_repo.add.await_count == 2

    async def test_same_key_idempotent_skips_existing(self, service, mock_relation_repo):
        """同键幂等：get_by_key 已存在 → 跳过该行不重复插入（#479 幂等去重键）."""
        dto = KnowledgeRelationCreate(
            source_type="character",
            source_id=uuid.uuid4(),
            target_type="world",
            target_id=uuid.uuid4(),
            relation_type="属于",
        )
        existing = _kr(
            source_id=dto.source_id, target_id=dto.target_id, relation_type="属于", source="ai"
        )
        mock_relation_repo.get_by_key = AsyncMock(return_value=existing)

        created = await service.bulk_create_relations(PID, [dto])

        assert created == []
        mock_relation_repo.add.assert_not_awaited()
def test_error_class_hierarchy():
    """错误类层次契约（§3.3）：422 类继承 KnowledgeGraphServiceError；404 类不继承."""
    assert issubclass(KnowledgeRelationConflictError, KnowledgeGraphServiceError)
    assert issubclass(KnowledgeRelationSelfLoopError, KnowledgeGraphServiceError)
    assert issubclass(KnowledgeEntityNotFoundError, KnowledgeGraphServiceError)
    assert issubclass(KnowledgeRelationValidationError, KnowledgeGraphServiceError)
    assert not issubclass(KnowledgeRelationNotFoundError, KnowledgeGraphServiceError)
