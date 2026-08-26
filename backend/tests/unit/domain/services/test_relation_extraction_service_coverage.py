"""F48 关系提取服务 — 规则 skip 边界 + AI 解析耗尽分支契约测试（#479 覆盖率收尾）。

补测 G1 RED 批未覆盖的边界分支：R1/R2 信号字段为 None 的跳过、R3 三分支目标
实体查不到、method=both 无章节 warning、LLM 解析重试耗尽。
依据: specs/f48-knowledge-graph/spec.md §5.5.4。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from inkflow.domain.models.extraction import ExtractionStatus
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.map import MapPin, WorldMap
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService
from inkflow.domain.services.relation_extraction_service import RelationExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _world(name: str, *, parent_id: uuid.UUID | None = None) -> WorldSetting:
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


def _foreshadow(title: str, *, event_id: uuid.UUID | None = None) -> Foreshadowing:
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        event_id=event_id,
        created_at=TS,
        updated_at=TS,
    )


def _timeline_event(title: str) -> TimelineEvent:
    return TimelineEvent(id=uuid.uuid4(), project_id=PID, title=title, created_at=TS, updated_at=TS)


def _map_pin(*, location_id=None, ref_id=None, type="location", label="pin") -> MapPin:
    return MapPin(
        id=uuid.uuid4(),
        map_id=uuid.uuid4(),
        location_id=location_id,
        ref_id=ref_id,
        type=type,
        x=1.0,
        y=1.0,
        label=label,
        created_at=TS,
        updated_at=TS,
    )


def _harness(**repos_overrides) -> SimpleNamespace:
    """装配 RelationExtractionService（镜像 G1 harness，默认已配模型）。"""
    kg = AsyncMock(spec=KnowledgeGraphService)
    kg.bulk_create_relations.return_value = []
    repos = {
        "character_repo": AsyncMock(),
        "world_repo": AsyncMock(),
        "outline_repo": AsyncMock(),
        "timeline_repo": AsyncMock(),
        "foreshadow_repo": AsyncMock(),
        "map_pin_repo": AsyncMock(),
        "chapter_repo": AsyncMock(),
    }
    repos["world_repo"].list.return_value = ([], 0)
    repos["foreshadow_repo"].list.return_value = ([], 0)
    repos["timeline_repo"].list_all.return_value = []
    repos["map_pin_repo"].list_maps_by_project.return_value = []
    repos["map_pin_repo"].list_pins.return_value = []
    repos["chapter_repo"].list_chapters.return_value = ([], 0)
    for name in ("character_repo", "world_repo", "timeline_repo", "foreshadow_repo"):
        repos[name].get.return_value = None
    key_manager = MagicMock()
    key_manager.list_providers.return_value = ["openai"]
    client = AsyncMock()
    client.chat.return_value = ChatResponse(content="bad", model="test-model")
    service = RelationExtractionService(
        knowledge_graph_service=kg,
        character_repo=repos["character_repo"],
        world_repo=repos["world_repo"],
        outline_repo=repos["outline_repo"],
        timeline_repo=repos["timeline_repo"],
        foreshadow_repo=repos["foreshadow_repo"],
        map_pin_repo=repos["map_pin_repo"],
        chapter_repo=repos["chapter_repo"],
        key_manager_factory=MagicMock(return_value=key_manager),
        llm_client_factory=MagicMock(return_value=client),
        llm_default_model="test-model",
        extraction_run_repo=None,
    )
    return SimpleNamespace(service=service, kg=kg, repos=repos, client=client)


class TestRuleSkipBoundaries:
    """规则提取：信号字段为 None / 目标实体查不到的跳过分支。"""

    async def test_r1_parent_id_none_skips(self):
        """顶层世界观（parent_id=None）→ 不产出，不调 bulk。"""
        h = _harness()
        top = _world("天玄大陆")  # parent_id=None
        h.repos["world_repo"].list.return_value = ([top], 1)

        result = await h.service.extract_for_project(PID, "rule")

        h.kg.bulk_create_relations.assert_not_awaited()
        assert result.created == 0

    async def test_r2_event_id_none_skips(self):
        """无锚定事件的伏笔（event_id=None）→ 不产出。"""
        h = _harness()
        fs = _foreshadow("玉佩")  # event_id=None
        h.repos["foreshadow_repo"].list.return_value = ([fs], 1)

        result = await h.service.extract_for_project(PID, "rule")

        h.kg.bulk_create_relations.assert_not_awaited()
        assert result.created == 0

    async def test_r3_world_missing_skips_with_warning(self):
        """pin location_id 非空但地点查不到 → 跳过 + warning。"""
        h = _harness()
        wm = WorldMap(
            id=uuid.uuid4(),
            project_id=PID,
            name="图",
            image_path="maps/test.png",
            created_at=TS,
            updated_at=TS,
        )
        pin = _map_pin(location_id=uuid.uuid4(), type="location")
        h.repos["map_pin_repo"].list_maps_by_project.return_value = [wm]
        h.repos["map_pin_repo"].list_pins.return_value = [pin]
        h.repos["world_repo"].get.return_value = None

        result = await h.service.extract_for_project(PID, "rule")

        h.kg.bulk_create_relations.assert_not_awaited()
        assert result.created == 0
        assert any("不存在" in w for w in result.warnings)

    async def test_r3_character_missing_skips_with_warning(self):
        """pin type=role 但角色查不到 → 跳过 + warning。"""
        h = _harness()
        wm = WorldMap(
            id=uuid.uuid4(),
            project_id=PID,
            name="图",
            image_path="maps/test.png",
            created_at=TS,
            updated_at=TS,
        )
        pin = _map_pin(ref_id=uuid.uuid4(), type="role")
        h.repos["map_pin_repo"].list_maps_by_project.return_value = [wm]
        h.repos["map_pin_repo"].list_pins.return_value = [pin]

        result = await h.service.extract_for_project(PID, "rule")

        h.kg.bulk_create_relations.assert_not_awaited()
        assert result.created == 0
        assert any("不存在" in w for w in result.warnings)

    async def test_r3_event_missing_skips_with_warning(self):
        """pin type=event 但事件查不到 → 跳过 + warning。"""
        h = _harness()
        wm = WorldMap(
            id=uuid.uuid4(),
            project_id=PID,
            name="图",
            image_path="maps/test.png",
            created_at=TS,
            updated_at=TS,
        )
        pin = _map_pin(ref_id=uuid.uuid4(), type="event")
        h.repos["map_pin_repo"].list_maps_by_project.return_value = [wm]
        h.repos["map_pin_repo"].list_pins.return_value = [pin]

        result = await h.service.extract_for_project(PID, "rule")

        h.kg.bulk_create_relations.assert_not_awaited()
        assert result.created == 0
        assert any("不存在" in w for w in result.warnings)


class TestAiBoundaries:
    """AI 提取：both 无章节 warning / 解析重试耗尽。"""

    async def test_both_no_chapters_appends_warning(self):
        """method=both + 已配模型 + 无章节 → warnings 含「无章节内容」，不 skipped。"""
        h = _harness()
        # 有规则关系产出，确保走完 both 全链路（无章节 AI 跳过 warning）
        parent = _world("天玄大陆")
        child = _world("帝都", parent_id=parent.id)
        h.repos["world_repo"].list.return_value = ([child], 1)
        h.repos["world_repo"].get.return_value = parent
        h.repos["chapter_repo"].list_chapters.return_value = ([], 0)

        result = await h.service.extract_for_project(PID, "both")

        assert result.status == ExtractionStatus.SUCCESS
        assert any("无章节内容" in w for w in result.warnings)

    async def test_ai_parse_exhausted_warns_not_raises(self):
        """LLM 连续 2 次坏输出（解析耗尽）→ created=0 + warnings 含解析失败，不抛错。"""
        h = _harness()
        from inkflow.domain.models.chapter import Chapter

        chapter = Chapter(
            id=uuid.uuid4(),
            project_id=PID,
            title="第一章",
            content="正文",
            created_at=TS,
            updated_at=TS,
        )
        h.repos["chapter_repo"].list_chapters.return_value = ([chapter], 1)
        h.client.chat.side_effect = [
            ChatResponse(content="不是 JSON", model="test-model"),
            ChatResponse(content="还是不是 JSON", model="test-model"),
        ]

        result = await h.service.extract_for_project(PID, "ai")

        assert h.client.chat.await_count == 2  # 重试耗尽
        h.kg.bulk_create_relations.assert_not_awaited()
        assert result.created == 0
        assert any("解析失败" in w for w in result.warnings)
