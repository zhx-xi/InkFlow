"""#1551 关系「只算不写」公开入口契约（RED）。

被测（GREEN 才实现）:
- ``RelationExtractionService.extract_rules`` —— 原私有 ``_extract_rules`` 升为**公开**
  compute-only 入口（规则集「只算不写」、零 LLM、零落库），供 ``_extraction_staging``
  跨模块调用，消除私有访问。
- 私有名 ``_extract_rules`` 不再存在（防回归：私有跨模块调用不可能再出现）。
- 行为等价：``extract_rules`` 只填充传入的 relations / warnings，不触发任何落库
  （``knowledge_graph_service.bulk_create_relations`` 不被调用）。

依据: specs/f14-extraction/spec.md §5.9 / §6.1（#1551，0.17.0 W8c）。

RED 预期: 当前仅有私有 ``_extract_rules`` → ``hasattr(RelationExtractionService,
"extract_rules")`` 为 False、``hasattr(..., "_extract_rules")`` 为 True → 用例 FAIL。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from inkflow.domain.models.knowledge_graph import EntityType, KnowledgeRelationCreate
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService
from inkflow.domain.services.relation_extraction_service import RelationExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 10, 9, tzinfo=UTC)


def _service() -> tuple[RelationExtractionService, AsyncMock, AsyncMock]:
    """装配服务；world_repo 造「1 子 1 父」→ R1 产出 1 条「属于」关系。"""
    kg = AsyncMock(spec=KnowledgeGraphService)
    world_repo = AsyncMock(spec=WorldRepositoryProtocol)
    parent = WorldSetting(
        id=uuid.uuid4(), project_id=PID, name="父条目", created_at=TS, updated_at=TS
    )
    child = WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name="子条目",
        parent_id=parent.id,
        created_at=TS,
        updated_at=TS,
    )
    world_repo.list.return_value = ([child], 1)
    world_repo.get.return_value = parent
    foreshadow_repo = AsyncMock(spec=ForeshadowingRepositoryProtocol)
    foreshadow_repo.list.return_value = ([], 0)
    map_pin_repo = AsyncMock(spec=MapRepositoryProtocol)
    map_pin_repo.list_maps_by_project.return_value = []
    service = RelationExtractionService(
        knowledge_graph_service=kg,
        character_repo=AsyncMock(spec=CharacterRepositoryProtocol),
        world_repo=world_repo,
        outline_repo=AsyncMock(spec=OutlineRepositoryProtocol),
        timeline_repo=AsyncMock(spec=TimelineRepositoryProtocol),
        foreshadow_repo=foreshadow_repo,
        map_pin_repo=map_pin_repo,
        chapter_repo=AsyncMock(spec=ChapterRepositoryProtocol),
    )
    return service, kg, world_repo


class TestPublicComputeOnlyEntry:
    """``extract_rules`` 公开化 + compute-only 语义。"""

    def test_extract_rules_is_public_and_private_name_gone(self) -> None:
        """公开入口存在；私有名已消除（防私有跨模块调用回归）。"""
        assert hasattr(RelationExtractionService, "extract_rules")
        assert callable(RelationExtractionService.extract_rules)
        assert not hasattr(RelationExtractionService, "_extract_rules")

    async def test_extract_rules_computes_without_writing(self) -> None:
        """compute-only：填充 relations / warnings，但不触发任何落库。"""
        service, kg, _world_repo = _service()
        relations: list[KnowledgeRelationCreate] = []
        warnings: list[str] = []

        await service.extract_rules(PID, relations, warnings)

        assert len(relations) == 1
        assert relations[0].relation_type == "属于"
        assert relations[0].source_type == EntityType.WORLD
        kg.bulk_create_relations.assert_not_awaited()  # 零写入
