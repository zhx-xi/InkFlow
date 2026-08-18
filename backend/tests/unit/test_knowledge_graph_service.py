"""F48 知识图谱 — knowledge_graph_service RED 契约测试
（spec v1.1 §9 service ~20 cases，M2/M4 验收）.

GREEN 必须匹配的契约（导入路径 = spec §8 文件表声明，缺模块 →
本文件收集期 ModuleNotFoundError = 预期 RED）:
- 服务实现:   inkflow.domain.services.knowledge_graph_service.KnowledgeGraphService
- 领域模型:   inkflow.domain.models.knowledge_graph.{EntityType, RelationSource,
              KnowledgeRelation, KnowledgeRelationCreate, KnowledgeRelationUpdate,
              GraphNode, GraphEdge, KnowledgeGraphView}
- 错误类:     inkflow.domain.ports.knowledge_graph_errors.{KnowledgeGraphServiceError(422 基类),
              KnowledgeRelationConflictError, KnowledgeRelationSelfLoopError,
              KnowledgeEntityNotFoundError, KnowledgeRelationValidationError,
              KnowledgeRelationNotFoundError(404，不继承 422 基类)}
- 仓储协议:   inkflow.domain.ports.knowledge_relation_repository.KnowledgeRelationRepositoryProtocol
              （add/get/get_by_key/list/filter/update/delete/list_by_project/delete_by_entity/cleanup_for_entity）
- 项目错误:   ProjectNotFoundError 复用 inkflow.domain.ports.world_errors（F10，§3.3 异常映射表）
- 实体校验:   character/world/outline/timeline/foreshadow → repo.get(id) 存在 + 同项目；
              map_pin → map_repo.get_pin(id) + map_repo.get(pin.map_id) 的 map.project_id == 项目
              （§2.2 链路）；各实体错误统一转换 KnowledgeEntityNotFoundError（detail 含
              source/target 端 + 类型名，§3.3）

构造签名（Keyword-only，实体/项目 repo 默认 None = 未注入，向后兼容，§5.3 决策 3）:
    KnowledgeGraphService(
        *,
        relation_repo: KnowledgeRelationRepositoryProtocol,       # 必填
        project_repo: ProjectRepositoryProtocol | None = None,
        character_repo: CharacterRepositoryProtocol | None = None,
        world_repo: WorldRepositoryProtocol | None = None,
        outline_repo: OutlineRepositoryProtocol | None = None,
        timeline_repo: TimelineRepositoryProtocol | None = None,
        foreshadow_repo: ForeshadowingRepositoryProtocol | None = None,
        map_repo: MapRepositoryProtocol | None = None,
    )

方法契约（§5.1 校验链顺序: ①项目 ②自环 ③字段 ④实体 ⑤同键 ⑥落库）:
- create_relation(project_id, source_type, source_id, target_type, target_id,
                  relation_type, description="") -> KnowledgeRelation
                  # 内部构造 KnowledgeRelationCreate 做字段校验（relation_type 去空白 1-20、
                  # description ≤500）→ pydantic 异常转 KnowledgeRelationValidationError；
                  # source 恒 manual（§2.1 规则 5）
- get_relation(relation_id) -> KnowledgeRelation        # 不存在 → KnowledgeRelationNotFoundError
- update_relation(relation_id, *, source_type=None, source_id=None, target_type=None,
                  target_id=None, relation_type=None, description=None, source=None)
                  -> KnowledgeRelation
                  # 关系不存在 → KnowledgeRelationNotFoundError；source 非 None →
                  # KnowledgeRelationValidationError（source 不可改，§7 边界 7）；
                  # 变更键字段重新校验（同 create ②③④，只校验传入字段）；
                  # 改键撞他行 → KnowledgeRelationConflictError
- delete_relation(relation_id) -> bool                  # 真删；不存在 →
KnowledgeRelationNotFoundError
- list_relations(project_id, *, source_type=None, target_type=None, relation_type=None,
                 source=None, offset=0, limit=50) -> (list, total)   # 委托 repo.filter
- graph(project_id) -> KnowledgeGraphView
                  # nodes: 六类实体全量，组序 character→world→outline→timeline→foreshadow→
                  # map_pin，组内 name ASC（name/title/label 按 §2.2 映射）——服务层保证排序；
                  # edges: relation_repo.list_by_project ∪ character_repo.list_relations(pid)，
                  # 同键(source,target,label)去重 knowledge 优先，knowledge 段在前 cr 段在后，
                  # 组内 created_at ASC；孤立边（端点不在 nodes）跳过 + 不抛错（§7 边界 10/13）
- cleanup_for_entity(entity_type, entity_id) -> int     # 委托
relation_repo.cleanup_for_entity（§5.3）
- bulk_create_relations(project_id, relations: list[KnowledgeRelationCreate],
                        source: RelationSource | str = RelationSource.AI) -> list[KnowledgeRelation]
                  # §5.5 预留端口: 单事务批量 + 同键幂等（get_by_key 已存在 → 跳过）；
                  # 实体存在性由 #479 调用方保证（本端口不重复校验）

⚠️ 实现期注意（spec 内部不一致，测试以边界表为准）:
- spec §2.3 KnowledgeRelationCreate 代码块未声明 description ≤500 校验器，但 §5.1③/§7 边界 5/
  §9 测试策略 11 要求 description 501 字符 → 422——本文件按 422 契约断言。
- spec §5.2 文称「各实体 repo list_by_project」，实际 F9-F13 协议方法名为 list(project_id,...)
  （返回 (list, total) 元组）；
  F36 map 为 list_maps_by_project + list_pins。测试按真实协议方法 mock。

依据: specs/f48-knowledge-graph/spec.md §2.2/§2.3/§3.3/§5.1/§5.2/§5.3/§5.5/§5.6/§7/§9/§13 M2+M4。
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
from inkflow.domain.ports.knowledge_graph_errors import (
    KnowledgeEntityNotFoundError,
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
from inkflow.domain.ports.world_errors import ProjectNotFoundError
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


class TestCreateRelation:
    """create_relation 校验链（spec §5.1 ①-⑥ + §7 边界 1-5/9）."""

    async def test_project_not_found_raises_404(
        self, service, mock_project_repo, mock_relation_repo
    ):
        """① 项目不存在 → ProjectNotFoundError（F10 world_errors 复用，404 语义）."""
        with pytest.raises(ProjectNotFoundError):
            await service.create_relation(
                project_id=PID,
                source_type="character",
                source_id=uuid.uuid4(),
                target_type="world",
                target_id=uuid.uuid4(),
                relation_type="属于",
            )
        mock_project_repo.get.assert_awaited_once_with(PID.int)
        mock_relation_repo.add.assert_not_awaited()

    async def test_self_loop_raises(self, service, mock_project_repo, mock_relation_repo):
        """② 自环（同类型同 id）→ KnowledgeRelationSelfLoopError（§7 边界 3）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        ent = uuid.uuid4()
        with pytest.raises(KnowledgeRelationSelfLoopError):
            await service.create_relation(
                project_id=PID,
                source_type="character",
                source_id=ent,
                target_type="character",
                target_id=ent,
                relation_type="自环",
            )
        mock_relation_repo.add.assert_not_awaited()

    @pytest.mark.parametrize(
        ("relation_type", "description"),
        [
            ("   ", "合法描述"),  # 空白 relation_type
            ("关" * 21, ""),  # 21 字符超长
            ("合法类型", "字" * 501),  # description 501 字符
        ],
    )
    async def test_field_validation_raises(
        self, service, mock_project_repo, mock_relation_repo, relation_type, description
    ):
        """③ 字段校验：relation_type 空白/21 字符、description 501 字符 →
        KnowledgeRelationValidationError（§7 边界 5）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        with pytest.raises(KnowledgeRelationValidationError):
            await service.create_relation(
                project_id=PID,
                source_type="character",
                source_id=uuid.uuid4(),
                target_type="world",
                target_id=uuid.uuid4(),
                relation_type=relation_type,
                description=description,
            )
        mock_relation_repo.add.assert_not_awaited()

    async def test_source_entity_not_found(self, service, mock_project_repo, mock_relation_repo):
        """④ source 实体不存在 → KnowledgeEntityNotFoundError（detail 指明 source 端 + 类型）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        src = uuid.uuid4()
        with pytest.raises(KnowledgeEntityNotFoundError) as exc:
            await service.create_relation(
                project_id=PID,
                source_type="character",
                source_id=src,
                target_type="world",
                target_id=uuid.uuid4(),
                relation_type="属于",
            )
        assert "source" in str(exc.value)
        assert "character" in str(exc.value)
        mock_relation_repo.add.assert_not_awaited()

    async def test_target_entity_not_found(
        self, service, mock_project_repo, mock_character_repo, mock_world_repo, mock_relation_repo
    ):
        """④ target 实体不存在 → KnowledgeEntityNotFoundError（detail 指明 target 端 + 类型）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        src_char = _char("林尘")
        mock_character_repo.get = AsyncMock(return_value=src_char)
        with pytest.raises(KnowledgeEntityNotFoundError) as exc:
            await service.create_relation(
                project_id=PID,
                source_type="character",
                source_id=src_char.id,
                target_type="world",
                target_id=uuid.uuid4(),
                relation_type="属于",
            )
        assert "target" in str(exc.value)
        assert "world" in str(exc.value)
        mock_relation_repo.add.assert_not_awaited()

    async def test_cross_project_entity_raises(
        self, service, mock_project_repo, mock_character_repo, mock_relation_repo
    ):
        """④ 跨项目实体视为不存在 → KnowledgeEntityNotFoundError（§7 边界 2，校验 repo
        按项目过滤）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        mock_character_repo.get = AsyncMock(return_value=_char("林尘", project_id=PID_OTHER))
        with pytest.raises(KnowledgeEntityNotFoundError):
            await service.create_relation(
                project_id=PID,
                source_type="character",
                source_id=uuid.uuid4(),
                target_type="world",
                target_id=uuid.uuid4(),
                relation_type="属于",
            )
        mock_relation_repo.add.assert_not_awaited()

    async def test_duplicate_key_raises_conflict(
        self,
        service,
        mock_project_repo,
        mock_character_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """⑤ 同键关系已存在 → KnowledgeRelationConflictError（§7 边界 4）；⑥ 不落库."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        mock_character_repo.get = AsyncMock(return_value=src_char)
        mock_world_repo.get = AsyncMock(return_value=tgt_world)
        mock_relation_repo.get_by_key = AsyncMock(
            return_value=_kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        )

        with pytest.raises(KnowledgeRelationConflictError):
            await service.create_relation(
                project_id=PID,
                source_type="character",
                source_id=src_char.id,
                target_type="world",
                target_id=tgt_world.id,
                relation_type="属于",
            )
        mock_relation_repo.add.assert_not_awaited()

    async def test_character_to_character_allowed(
        self, service, mock_project_repo, mock_character_repo, mock_relation_repo
    ):
        """Q1=A 拍板：character→character 是合法关系（§2.1 规则 3b）——成功落库，source 恒 manual."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        a = _char("林尘")
        b = _char("阿澈")
        mock_character_repo.get = AsyncMock(side_effect=lambda cid: a if cid == a.id.int else b)

        created = await service.create_relation(
            project_id=PID,
            source_type="character",
            source_id=a.id,
            target_type="character",
            target_id=b.id,
            relation_type="师徒",
            description="林尘的师弟",
        )
        assert created.source == RelationSource.MANUAL
        assert created.project_id == PID
        assert created.relation_type == "师徒"
        added = mock_relation_repo.add.await_args.args[0]
        assert isinstance(added, KnowledgeRelation)
        assert added.source_type == EntityType.CHARACTER
        assert added.target_type == EntityType.CHARACTER
        assert added.description == "林尘的师弟"
        mock_character_repo.get.assert_awaited_with(b.id.int)

    async def test_success_source_manual_and_relation_type_stripped(
        self, service, mock_project_repo, mock_character_repo, mock_world_repo, mock_relation_repo
    ):
        """⑥ 成功路径：relation_type 去空白落库、source 恒 manual、get_by_key 以六元组 int
        键查询."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        mock_character_repo.get = AsyncMock(return_value=src_char)
        mock_world_repo.get = AsyncMock(return_value=tgt_world)

        created = await service.create_relation(
            project_id=PID,
            source_type="character",
            source_id=src_char.id,
            target_type="world",
            target_id=tgt_world.id,
            relation_type=" 属于 ",
            description="林尘出身清河县",
        )
        assert created.relation_type == "属于"
        assert created.source == RelationSource.MANUAL
        mock_character_repo.get.assert_awaited_once_with(src_char.id.int)
        mock_world_repo.get.assert_awaited_once_with(tgt_world.id.int)
        mock_relation_repo.get_by_key.assert_awaited_once_with(
            PID.int, "character", src_char.id.int, "world", tgt_world.id.int, "属于"
        )

    async def test_map_pin_valid_chain_passes(
        self,
        service,
        mock_project_repo,
        mock_map_repo,
        mock_world_repo,
        mock_relation_repo,
    ):
        """④ map_pin 校验链路（§2.2）：pin 存在 + 所属 map 项目匹配 → 通过."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        wm = _map("大陆图")
        pin = _pin("青云宗", map_id=wm.id)
        tgt_world = _world("清河县")
        mock_map_repo.get_pin = AsyncMock(return_value=pin)
        mock_map_repo.get = AsyncMock(return_value=wm)
        mock_world_repo.get = AsyncMock(return_value=tgt_world)

        created = await service.create_relation(
            project_id=PID,
            source_type="map_pin",
            source_id=pin.id,
            target_type="world",
            target_id=tgt_world.id,
            relation_type="位于",
        )
        mock_map_repo.get_pin.assert_awaited_once_with(pin.id.int)
        mock_map_repo.get.assert_awaited_once_with(wm.id.int)
        assert created.source_type == EntityType.MAP_PIN

    async def test_map_pin_orphan_or_wrong_project_raises(
        self, service, mock_project_repo, mock_map_repo, mock_world_repo, mock_relation_repo
    ):
        """④ map_pin 孤立（所属 map 已删）/ 跨项目 → KnowledgeEntityNotFoundError（§7 边界
        13/2）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        wm = _map("大陆图")
        pin = _pin("青云宗", map_id=wm.id)
        tgt_world = _world("清河县")
        mock_world_repo.get = AsyncMock(return_value=tgt_world)

        # pin 孤立：get_pin 命中但 map 不存在
        mock_map_repo.get_pin = AsyncMock(return_value=pin)
        mock_map_repo.get = AsyncMock(return_value=None)
        with pytest.raises(KnowledgeEntityNotFoundError) as exc:
            await service.create_relation(
                project_id=PID,
                source_type="map_pin",
                source_id=pin.id,
                target_type="world",
                target_id=tgt_world.id,
                relation_type="位于",
            )
        assert "source" in str(exc.value)
        assert "map_pin" in str(exc.value)

        # 所属 map 跨项目
        mock_map_repo.get = AsyncMock(return_value=_map("他图", project_id=PID_OTHER))
        with pytest.raises(KnowledgeEntityNotFoundError):
            await service.create_relation(
                project_id=PID,
                source_type="map_pin",
                source_id=pin.id,
                target_type="world",
                target_id=tgt_world.id,
                relation_type="位于",
            )
        mock_relation_repo.add.assert_not_awaited()


class TestUpdateRelation:
    """update_relation（spec §5.1 + §7 边界 6/7/8）."""

    async def test_not_found_raises_404(self, service, mock_relation_repo):
        """① 关系不存在 → KnowledgeRelationNotFoundError（404，§7 边界 8）."""
        with pytest.raises(KnowledgeRelationNotFoundError):
            await service.update_relation(uuid.uuid4(), relation_type="出身")
        mock_relation_repo.update.assert_not_awaited()

    async def test_source_field_not_modifiable(
        self, service, mock_relation_repo, mock_character_repo, mock_world_repo
    ):
        """② source 不可改（#479 写入方才能置 ai）→ KnowledgeRelationValidationError（§7 边界
        7）."""
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        existing = _kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        mock_relation_repo.get = AsyncMock(return_value=existing)

        with pytest.raises(KnowledgeRelationValidationError):
            await service.update_relation(existing.id, source="ai")
        mock_relation_repo.update.assert_not_awaited()

    async def test_relation_type_blank_rejected(self, service, mock_relation_repo):
        """② 变更字段校验：relation_type 空白 → KnowledgeRelationValidationError."""
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        existing = _kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        mock_relation_repo.get = AsyncMock(return_value=existing)

        with pytest.raises(KnowledgeRelationValidationError):
            await service.update_relation(existing.id, relation_type="   ")
        mock_relation_repo.update.assert_not_awaited()

    async def test_key_change_conflict_raises(
        self,
        service,
        mock_relation_repo,
        mock_character_repo,
        mock_outline_repo,
    ):
        """③ 改键后与另一行冲突 → KnowledgeRelationConflictError（§7 边界 6）."""
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        existing = _kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        mock_relation_repo.get = AsyncMock(return_value=existing)
        new_outline = _outline("第一卷")
        mock_outline_repo.get = AsyncMock(return_value=new_outline)
        mock_relation_repo.get_by_key = AsyncMock(
            return_value=_kr(
                source_id=src_char.id,
                target_type="outline",
                target_id=new_outline.id,
                relation_type="属于",
            )
        )

        with pytest.raises(KnowledgeRelationConflictError):
            await service.update_relation(
                existing.id, target_type="outline", target_id=new_outline.id
            )
        mock_relation_repo.update.assert_not_awaited()

    async def test_success_six_tuple_and_description_update(
        self,
        service,
        mock_relation_repo,
        mock_character_repo,
        mock_outline_repo,
    ):
        """④ 六元组可改 + description 传空串清空；source 字段保持 manual."""
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        existing = _kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        mock_relation_repo.get = AsyncMock(return_value=existing)
        new_outline = _outline("第一卷")
        mock_outline_repo.get = AsyncMock(return_value=new_outline)

        updated = await service.update_relation(
            existing.id,
            target_type="outline",
            target_id=new_outline.id,
            relation_type="出身",
            description="",
        )
        assert updated.id == existing.id
        assert updated.target_type == EntityType.OUTLINE
        assert updated.target_id == new_outline.id
        assert updated.relation_type == "出身"
        assert updated.description == ""
        assert updated.source == RelationSource.MANUAL
        merged = mock_relation_repo.update.await_args.args[0]
        assert isinstance(merged, KnowledgeRelation)
        assert merged.project_id == PID


class TestDeleteRelation:
    """delete_relation 真删（§5.1 + §7 边界 8）."""

    async def test_delete_success_delegates_int_id(self, service, mock_relation_repo):
        """关系存在 → 委托 repo.delete(int 主键) 真删，返回 True."""
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        existing = _kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        mock_relation_repo.get = AsyncMock(return_value=existing)

        assert await service.delete_relation(existing.id) is True
        mock_relation_repo.delete.assert_awaited_once_with(existing.id.int)

    async def test_delete_not_found_raises_404(self, service, mock_relation_repo):
        """关系不存在 → KnowledgeRelationNotFoundError（404，§7 边界 8）."""
        with pytest.raises(KnowledgeRelationNotFoundError):
            await service.delete_relation(uuid.uuid4())
        mock_relation_repo.delete.assert_not_awaited()


class TestGetRelation:
    """get_relation（§7 边界 8）."""

    async def test_get_not_found_raises_404(self, service, mock_relation_repo):
        """关系不存在 → KnowledgeRelationNotFoundError（404）."""
        with pytest.raises(KnowledgeRelationNotFoundError):
            await service.get_relation(uuid.uuid4())

    async def test_get_hit_returns_relation(self, service, mock_relation_repo):
        """关系存在 → 返回领域实体（int 主键转换）."""
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        rel = _kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        mock_relation_repo.get = AsyncMock(return_value=rel)

        got = await service.get_relation(rel.id)
        assert got.id == rel.id
        mock_relation_repo.get.assert_awaited_once_with(rel.id.int)


class TestListRelations:
    """list_relations 过滤 + 分页（§5.1/§5.6，created_at DESC 由 repo 保证）."""

    async def test_delegates_filters_and_pagination(self, service, mock_relation_repo):
        """委托 repo.filter 传 int 项目键 + 全部过滤参数 + 分页."""
        src_char = _char("林尘")
        tgt_world = _world("清河县")
        rel = _kr(source_id=src_char.id, target_id=tgt_world.id, relation_type="属于")
        mock_relation_repo.filter = AsyncMock(return_value=([rel], 1))

        items, total = await service.list_relations(
            PID,
            source_type="character",
            target_type="world",
            relation_type="属于",
            source="manual",
            offset=10,
            limit=20,
        )
        assert total == 1
        assert items[0].id == rel.id
        mock_relation_repo.filter.assert_awaited_once_with(
            PID.int,
            source_type="character",
            target_type="world",
            relation_type="属于",
            source="manual",
            offset=10,
            limit=20,
        )

# ── 已拆分至 test_knowledge_graph_service_graph.py ──
