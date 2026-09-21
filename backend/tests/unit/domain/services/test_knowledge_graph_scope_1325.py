"""#1325 知识图谱节点集 scope 契约测试（后端 RED 契约，父侧作者）。

契约来源：`specs/f48-knowledge-graph/spec.md` §5.2（v1.4 起）——图谱聚合 nodes 语义：

  - `scope="related"`（**默认**）：节点 = 参与至少一条关系的实体；
    **无任何关系时回退「角色全集」**（满足用户「默认只有角色块，添加关系后才出现
    地点/设定/伏笔」）；
  - `scope="all"`：六类实体全量节点（完整体检视图，438 级）；
  - 两种 scope 下 nodes 一律「每表全量」（**不得走 list() 的默认 limit=50**）——
    这是 C3 缺陷的修复面（旧实现在 217 节点时静默丢弃 8 条端点落在第 51+ 位的边）。

本文件由父侧（架构师）编写，Codex 侧**禁改**；mock 形态对齐既有兄弟文件
`test_knowledge_graph_service_graph.py` 的 fixture 约定。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import Character
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.knowledge_graph import (
    EntityType,
    KnowledgeRelation,
    RelationSource,
)
from inkflow.domain.models.map import MapPin, WorldMap
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.knowledge_relation_repository import (
    KnowledgeRelationRepositoryProtocol,
)
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)

# 实体类名 → EntityType（_kr 推导用）
_TYPE_OF: dict[str, EntityType] = {
    "Character": EntityType.CHARACTER,
    "WorldSetting": EntityType.WORLD,
    "Outline": EntityType.OUTLINE,
    "TimelineEvent": EntityType.TIMELINE,
    "Foreshadowing": EntityType.FORESHADOW,
    "MapPin": EntityType.MAP_PIN,
}


# ── 实体构造器（对齐兄弟文件形态）────────────────────────────────────


def _char(name: str) -> Character:
    """构造测试用角色实体."""
    return Character(id=uuid.uuid4(), project_id=PID, name=name, created_at=TS, updated_at=TS)


def _world(name: str) -> WorldSetting:
    """构造测试用世界观条目实体."""
    return WorldSetting(id=uuid.uuid4(), project_id=PID, name=name, created_at=TS, updated_at=TS)


def _outline(name: str) -> Outline:
    """构造测试用大纲实体."""
    return Outline(id=uuid.uuid4(), project_id=PID, name=name, created_at=TS, updated_at=TS)


def _event(title: str) -> TimelineEvent:
    """构造测试用时间线事件实体."""
    return TimelineEvent(id=uuid.uuid4(), project_id=PID, title=title, created_at=TS, updated_at=TS)


def _foreshadow(title: str) -> Foreshadowing:
    """构造测试用伏笔实体."""
    return Foreshadowing(id=uuid.uuid4(), project_id=PID, title=title, created_at=TS, updated_at=TS)


def _map(name: str) -> WorldMap:
    """构造测试用地图实体."""
    return WorldMap(
        id=uuid.uuid4(), project_id=PID, name=name, image_path="", created_at=TS, updated_at=TS
    )


def _pin(label: str, *, map_id: uuid.UUID) -> MapPin:
    """构造测试用地图 pin 实体."""
    return MapPin(
        id=uuid.uuid4(), map_id=map_id, x=10.0, y=20.0, label=label, created_at=TS, updated_at=TS
    )


def _project() -> Project:
    """构造测试用项目实体."""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


def _kr(
    *,
    source: Character | WorldSetting | Outline | TimelineEvent | Foreshadowing | MapPin,
    target: Character | WorldSetting | Outline | TimelineEvent | Foreshadowing | MapPin,
    relation_type: str,
) -> KnowledgeRelation:
    """按两端实体构造关系行（类型由实体类推导——省去手写六元组）."""
    return KnowledgeRelation(
        id=uuid.uuid4(),
        project_id=PID,
        source_type=_TYPE_OF[type(source).__name__],
        source_id=source.id,
        target_type=_TYPE_OF[type(target).__name__],
        target_id=target.id,
        relation_type=relation_type,
        description="",
        source=RelationSource.MANUAL,
        created_at=TS,
        updated_at=TS,
    )


def _seed(
    *,
    char_repo: MagicMock,
    world_repo: MagicMock,
    outline_repo: MagicMock,
    timeline_repo: MagicMock,
    foreshadow_repo: MagicMock,
    chars: list[Character],
    worlds: list[WorldSetting],
    outlines: list[Outline],
    events: list[TimelineEvent],
    foreshadows: list[Foreshadowing],
) -> None:
    """把五类实体播种到「全量方法」上（list() 故意留空 → 走分页即为缺陷）."""
    char_repo.list_all = AsyncMock(return_value=chars)
    world_repo.list_all_active = AsyncMock(return_value=worlds)
    outline_repo.list_all = AsyncMock(return_value=outlines)
    timeline_repo.list_all = AsyncMock(return_value=events)
    foreshadow_repo.list_all = AsyncMock(return_value=foreshadows)


# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def mock_relation_repo() -> MagicMock:
    """Mock 关系仓储（list_by_project 为图谱边唯一数据源）."""
    repo = MagicMock(spec=KnowledgeRelationRepositoryProtocol)
    repo.list_by_project = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock 项目仓储（graph 入口先判项目存在）."""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def mock_character_repo() -> MagicMock:
    """Mock 角色仓储（get + list + list_all）."""
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_world_repo() -> MagicMock:
    """Mock 世界观仓储（get + list + list_all_active——本仓无 list_all）."""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all_active = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_outline_repo() -> MagicMock:
    """Mock 大纲仓储（get + list + list_all）."""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_timeline_repo() -> MagicMock:
    """Mock 时间线仓储（get + list + list_all——list_all 本仓已存在）."""
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_foreshadow_repo() -> MagicMock:
    """Mock 伏笔仓储（get + list + list_all）."""
    repo = MagicMock(spec=ForeshadowingRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_map_repo() -> MagicMock:
    """Mock 地图仓储（map_pin 链路 + 节点）."""
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


class TestGraphScopeAll:
    """scope="all"：六类全量节点（§5.2 完整体检视图）。"""

    async def test_all_scope_returns_every_node(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_outline_repo,
        mock_timeline_repo,
        mock_foreshadow_repo,
        mock_map_repo,
    ):
        """all → 六类节点全在（含不参与任何关系的孤立实体）."""
        char_a, char_b = _char("林尘"), _char("阿澈")
        world_w = _world("清河县")
        outline_o = _outline("整体大纲")
        event_e = _event("序章")
        fs_f = _foreshadow("身世伏笔")
        wm = _map("大陆图")
        pin = _pin("城门口", map_id=wm.id)
        _seed(
            char_repo=mock_character_repo,
            world_repo=mock_world_repo,
            outline_repo=mock_outline_repo,
            timeline_repo=mock_timeline_repo,
            foreshadow_repo=mock_foreshadow_repo,
            chars=[char_a, char_b],
            worlds=[world_w],
            outlines=[outline_o],
            events=[event_e],
            foreshadows=[fs_f],
        )
        mock_map_repo.list_maps_by_project = AsyncMock(return_value=[wm])
        mock_map_repo.list_pins = AsyncMock(return_value=[pin])

        view = await service.graph(PID, scope="all")

        assert {n.id for n in view.nodes} == {
            f"character:{char_a.id}",
            f"character:{char_b.id}",
            f"world:{world_w.id}",
            f"outline:{outline_o.id}",
            f"timeline:{event_e.id}",
            f"foreshadow:{fs_f.id}",
            f"map_pin:{pin.id}",
        }

    async def test_all_scope_uses_full_list_not_paged(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_outline_repo,
        mock_timeline_repo,
        mock_foreshadow_repo,
    ):
        """C3 修复面：节点集必须走**全量方法**——分页 list() 一次都不许被调用.

        旧实现 `repo.list(project_id)` 恒带默认 limit=50 → 实测把 215 条时间线截成 50 条、
        并连带丢掉 8 条端点落在第 51+ 位的边（spec §5.2:432-434「每表全量返回」）。
        """
        _seed(
            char_repo=mock_character_repo,
            world_repo=mock_world_repo,
            outline_repo=mock_outline_repo,
            timeline_repo=mock_timeline_repo,
            foreshadow_repo=mock_foreshadow_repo,
            chars=[_char("林尘")],
            worlds=[_world("清河县")],
            outlines=[],
            events=[_event("序章")],
            foreshadows=[],
        )

        await service.graph(PID, scope="all")

        mock_character_repo.list.assert_not_awaited()
        mock_world_repo.list.assert_not_awaited()
        mock_outline_repo.list.assert_not_awaited()
        mock_timeline_repo.list.assert_not_awaited()
        mock_foreshadow_repo.list.assert_not_awaited()
        mock_character_repo.list_all.assert_awaited_once_with(PID)
        mock_world_repo.list_all_active.assert_awaited_once_with(PID)
        mock_timeline_repo.list_all.assert_awaited_once_with(PID)


class TestGraphScopeRelated:
    """scope="related"（默认）：只显示参与至少一条关系的实体（§5.2）。"""

    async def test_related_scope_keeps_only_connected_entities(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_outline_repo,
        mock_timeline_repo,
        mock_foreshadow_repo,
        mock_relation_repo,
    ):
        """有「林尘 →属于→ 清河县」一条关系 → 默认视图只剩这两个块.

        角色乙/大纲/时间线/伏笔都无边 → 不得出现（用户诉求「默认只有角色块，
        添加关系后才在线上和关联块显示地点/设定/伏笔」）。
        """
        char_a, char_b = _char("林尘"), _char("阿澈")
        world_w = _world("清河县")
        outline_o = _outline("整体大纲")
        event_e = _event("序章")
        fs_f = _foreshadow("身世伏笔")
        _seed(
            char_repo=mock_character_repo,
            world_repo=mock_world_repo,
            outline_repo=mock_outline_repo,
            timeline_repo=mock_timeline_repo,
            foreshadow_repo=mock_foreshadow_repo,
            chars=[char_a, char_b],
            worlds=[world_w],
            outlines=[outline_o],
            events=[event_e],
            foreshadows=[fs_f],
        )
        mock_relation_repo.list_by_project = AsyncMock(
            return_value=[_kr(source=char_a, target=world_w, relation_type="属于")]
        )

        view = await service.graph(PID)  # scope 缺省 = related

        assert {n.id for n in view.nodes} == {
            f"character:{char_a.id}",
            f"world:{world_w.id}",
        }
        # 反向断言：无边实体不得出现在默认视图
        node_ids = {n.id for n in view.nodes}
        for orphan in (char_b, outline_o, event_e, fs_f):
            assert all(n.entity_id != orphan.id for n in view.nodes), node_ids

    async def test_related_scope_falls_back_to_characters_when_no_relations(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_outline_repo,
        mock_timeline_repo,
        mock_foreshadow_repo,
    ):
        """无任何关系 → 回退「角色全集」（用户预期：一开始只看到角色块）."""
        char_a, char_b = _char("林尘"), _char("阿澈")
        world_w = _world("清河县")
        outline_o = _outline("整体大纲")
        _seed(
            char_repo=mock_character_repo,
            world_repo=mock_world_repo,
            outline_repo=mock_outline_repo,
            timeline_repo=mock_timeline_repo,
            foreshadow_repo=mock_foreshadow_repo,
            chars=[char_a, char_b],
            worlds=[world_w],
            outlines=[outline_o],
            events=[],
            foreshadows=[],
        )

        view = await service.graph(PID)

        assert {n.id for n in view.nodes} == {
            f"character:{char_a.id}",
            f"character:{char_b.id}",
        }
        assert all(n.type is EntityType.CHARACTER for n in view.nodes)
        # 反向断言：无关系时地点/大纲不得出现
        assert all(n.id != f"world:{world_w.id}" for n in view.nodes)
        assert all(n.id != f"outline:{outline_o.id}" for n in view.nodes)

    async def test_related_scope_no_characters_and_no_relations_is_empty(
        self,
        service,
        mock_world_repo,
    ):
        """无关系 + 无角色 → 空节点集（不伪造节点）."""
        mock_world_repo.list_all_active = AsyncMock(return_value=[_world("清河县")])

        view = await service.graph(PID)

        assert view.nodes == []
        assert view.edges == []

    async def test_related_scope_keeps_target_reachable_only_via_filtered_edge(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """🔴 顺序核心：related 收窄必须发生在「孤立边过滤」**之前**.

        构造两条边：e1 = 幽灵乙→阿澈（**孤立**：幽灵乙不在节点集，模拟已删实体的残留关系），
        e2 = 林尘→阿澈（有效）。若实现先用「已过滤边集」算 related，则阿澈会因 e1 被过滤
        而失联 → 被误删；正确实现用**未过滤**的关系行算 related → 阿澈保留。
        """
        ghost = _char("幽灵乙")  # 故意**不**放进节点集
        char_a = _char("林尘")
        char_b = _char("阿澈")
        world_w = _world("清河县")
        mock_character_repo.list_all = AsyncMock(return_value=[char_a, char_b])
        mock_world_repo.list_all_active = AsyncMock(return_value=[world_w])
        mock_relation_repo.list_by_project = AsyncMock(
            return_value=[
                _kr(source=ghost, target=char_b, relation_type="幽灵边"),
                _kr(source=char_a, target=char_b, relation_type="同伴"),
            ]
        )

        view = await service.graph(PID)

        node_ids = {n.id for n in view.nodes}
        assert node_ids == {f"character:{char_a.id}", f"character:{char_b.id}"}
        # 幽灵边仍按既有语义跳过；有效边保留
        assert [e.label for e in view.edges] == ["同伴"]

    async def test_related_scope_keeps_edges_of_related_nodes(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """related 视图的边集 = 两端口都在收窄后节点集的关系（既有语义不变）."""
        char_a, char_b = _char("林尘"), _char("阿澈")
        world_w = _world("清河县")
        mock_character_repo.list_all = AsyncMock(return_value=[char_a, char_b])
        mock_world_repo.list_all_active = AsyncMock(return_value=[world_w])
        mock_relation_repo.list_by_project = AsyncMock(
            return_value=[_kr(source=char_a, target=char_b, relation_type="师徒")]
        )

        view = await service.graph(PID)

        assert [e.label for e in view.edges] == ["师徒"]
        assert view.edges[0].source == f"character:{char_a.id}"
        assert view.edges[0].target == f"character:{char_b.id}"


class TestGraphScopeBackwardCompat:
    """向后兼容：不传 scope 时行为 == related（默认值不得改变既有调用面语义）."""

    async def test_default_scope_equals_related(
        self,
        service,
        mock_character_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """`graph(PID)` 与 `graph(PID, scope="related")` 产出同一节点集."""
        char_a = _char("林尘")
        char_b = _char("阿澈")
        world_w = _world("清河县")
        mock_character_repo.list_all = AsyncMock(return_value=[char_a, char_b])
        mock_world_repo.list_all_active = AsyncMock(return_value=[world_w])
        mock_relation_repo.list_by_project = AsyncMock(
            return_value=[_kr(source=char_a, target=world_w, relation_type="属于")]
        )

        default_view = await service.graph(PID)
        explicit_view = await service.graph(PID, scope="related")

        assert {n.id for n in default_view.nodes} == {n.id for n in explicit_view.nodes}
        assert {e.id for e in default_view.edges} == {e.id for e in explicit_view.edges}

    async def test_minimal_service_still_works_with_scope(
        self,
        mock_relation_repo: MagicMock,
    ):
        """仅注入 relation_repo 的最小服务（六实体 repo 全 None）→ 空图谱，不抛错."""
        svc = KnowledgeGraphService(relation_repo=mock_relation_repo)

        view = await svc.graph(PID)

        assert view.nodes == []
        assert view.edges == []
