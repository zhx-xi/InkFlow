"""#479 关系提取服务契约测试 — RelationExtractionService（RED 批）。

覆盖 spec f48-knowledge-graph §5.5.4（v1.2 定稿契约，#479 实现唯一真相）:
- 规则提取三规则集（R1/R2/R3 分支）逐条 + 目标实体查不到跳过 + 封闭枚举数量
- AI 提取: 未配模型门禁 LLMNotConfiguredError / both 降级 / 无章节 skipped /
  LLM 解析失败重试一次 / 名称解析（get_by_name + title 精确匹配）/ 解析失败丢弃
- 幂等: created=len(bulk 实际新增)、updated 恒 0
- 写入统一 source=RelationSource.AI（规则与 AI 同源语义，§5.5.9 验收 2）

依据: specs/f48-knowledge-graph/spec.md §5.5.4/§5.5.5/§5.5.8。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:
``inkflow.domain.services.relation_extraction_service``，逐字实现 spec §5.5.4:

1. ``class RelationExtractionService``（全 Keyword-only 构造）:
   - ``def __init__(self, *, knowledge_graph_service, character_repo, world_repo,
     outline_repo, timeline_repo, foreshadow_repo, map_pin_repo, chapter_repo,
     key_manager_factory=None, llm_client_factory=None, llm_default_model=None,
     extraction_run_repo=None) -> None``
   - ``async def extract_for_project(self, project_id: uuid.UUID, method: str)
     -> ExtractionResult``
   - method 非 rule/ai/both → ``ValueError``（API 层映射 422，服务层不抛 422）
   - 模块级 ``RULE_IDS: tuple[str, ...]`` —— 规则集封闭枚举，恰含 3 个标识
     ("r1", "r2", "r3")（§5.5.4「测试断言规则集数量 = 3」；新增规则必须同步扩展）

2. 规则提取（method 含 rule）—— 确定性三规则集，零 LLM：
   - R1: ``world_repo.list(pid)`` → WorldSetting.parent_id 非空 →
     ``world_repo.get(parent_id)`` 查目标 → world(child)→world(parent)，relation_type=「属于」
   - R2: ``foreshadow_repo.list(pid)`` → Foreshadowing.event_id 非空 →
     ``timeline_repo.get(event_id)`` → foreshadow→timeline，relation_type=「锚定于」
   - R3: ``map_pin_repo.list_maps_by_project(pid)`` → 逐图 ``list_pins(map_id)``：
     location_id 非空 → ``world_repo.get`` → map_pin→world「位于」；
     ref_id 非空且 type=role → ``character_repo.get`` → map_pin→character「出现于地图」；
     ref_id 非空且 type=event → ``timeline_repo.get`` → map_pin→timeline「出现于地图」；
     type=other → 不产出
   - 目标实体 repo 查不到（get 返回 None）→ 该条跳过 + warnings 含说明（不抛错）
   - 全部规则产出一并写入：单次 ``await knowledge_graph_service.bulk_create_relations(
     project_id, relations, source=RelationSource.AI)``（规则与 AI 统一 source=ai，
     §5.5.9 验收 2）；无待写关系 → 不调用 bulk_create_relations

3. AI 提取（method 含 ai）：
   - 门禁: ``key_manager_factory()().list_providers()`` 返回空列表 → raise
     ``LLMNotConfiguredError``（from ``inkflow.domain.ports.knowledge_graph_errors``；
     RED 期该类不存在 → 顶部 import 收集失败即预期）
   - method='both' 且未配模型 → 降级仅 rule + warnings 含「AI 提取跳过：未配置模型」
     （不抛错）
   - 输入: ``chapter_repo.list_chapters(pid)`` 全部章节正文拼接（截断上限 50000）；
     无章节 → ``ExtractionResult(status=skipped, skipped_reason 含「无章节」)``，不调 LLM
   - LLM: ``llm_client_factory()`` 返回 LLMClientProtocol 形态客户端（chat 方法，F14
     extractor 先例）；解析失败（无平衡 JSON 片段/结构非法）→ 重试一次（chat 恰调用 2 次）
   - 名称解析: character/world/outline → ``repo.get_by_name(project_id, name)``；
     timeline → ``timeline_repo.list_all`` 后 title 精确匹配（strip 首尾空白）；
     foreshadow → ``foreshadow_repo.list`` 后 title 精确匹配（strip）；
     解析失败 → 该条丢弃 + warnings；map_pin 不参与 AI 解析（只产出五类）
   - 写入: 解析成功的关系统一 ``bulk_create_relations(project_id, relations,
     source=RelationSource.AI)``

4. 幂等: bulk_create_relations 返回**实际新增列表**；result.created = len(新增)，
   result.updated 恒 0（跳过数进 warnings，§5.5.4「N 条关系已存在，跳过」）。

5. 结果信封: ``ExtractionResult.type == ExtractionType.KNOWLEDGE_RELATION``
   （§5.5.5 第 7 值，与 test_extraction_models 同步 RED）。

6. mock 形态（测试装配，GREEN 不得依赖）:
   - repo 全 ``AsyncMock(spec=对应 RepositoryProtocol)``；get*/get_by_name 默认
     return_value=None（「查不到」语义）；list*/list_all/list_chapters 默认空结果
   - key_manager_factory: ``MagicMock``，``factory()`` 返回 list_providers 可配的 manager
   - llm_client_factory: ``MagicMock``，``factory()`` 返回 AsyncMock client（chat 为 AsyncMock）
   - knowledge_graph_service: ``AsyncMock(spec=KnowledgeGraphService)``，
     bulk_create_relations return_value 默认 []（created=0 语义）

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import inkflow.domain.services.relation_extraction_service as relation_extraction_service
from inkflow.domain.models.character import Character
from inkflow.domain.models.extraction import (
    ExtractionResult,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.knowledge_graph import (
    EntityType,
    KnowledgeRelation,
    KnowledgeRelationCreate,
    RelationSource,
)
from inkflow.domain.models.map import MapPin, WorldMap
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.knowledge_graph_errors import LLMNotConfiguredError  # RED ②
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService
from inkflow.domain.services.relation_extraction_service import (  # RED ①：模块不存在
    RelationExtractionService,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


# ── 实体构造辅助 ────────────────────────────────────────────────────────────


def _world(name: str, *, parent_id: uuid.UUID | None = None) -> WorldSetting:
    """构造测试用世界观条目（parent_id 可空，R1 信号字段）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


def _foreshadow(title: str, *, event_id: uuid.UUID | None = None) -> Foreshadowing:
    """构造测试用伏笔（event_id 可空，R2 信号字段）。"""
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        event_id=event_id,
        created_at=TS,
        updated_at=TS,
    )


def _timeline_event(title: str) -> TimelineEvent:
    """构造测试用时间线事件（title 精确匹配目标，R2/R3c）。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        created_at=TS,
        updated_at=TS,
    )


def _character(name: str) -> Character:
    """构造测试用角色（AI 名称解析目标）。"""
    return Character(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        created_at=TS,
        updated_at=TS,
    )


def _outline(name: str) -> Outline:
    """构造测试用大纲（AI 名称解析目标）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        created_at=TS,
        updated_at=TS,
    )


def _world_map() -> WorldMap:
    """构造测试用地图（R3 pin 收集经 map→pin 链路）。"""
    return WorldMap(
        id=uuid.uuid4(),
        project_id=PID,
        name="天玄大陆地图",
        image_path="maps/test.png",
        created_at=TS,
        updated_at=TS,
    )


def _map_pin(
    label: str,
    *,
    location_id: uuid.UUID | None = None,
    ref_id: uuid.UUID | None = None,
    type: str = "location",
) -> MapPin:
    """构造测试用 pin（location_id/ref_id/type 为 R3 分支信号字段）。"""
    return MapPin(
        id=uuid.uuid4(),
        map_id=uuid.uuid4(),
        location_id=location_id,
        type=type,
        ref_id=ref_id,
        x=1.0,
        y=1.0,
        label=label,
        created_at=TS,
        updated_at=TS,
    )


def _kr(
    source_type: EntityType,
    source_id: uuid.UUID,
    target_type: EntityType,
    target_id: uuid.UUID,
    relation_type: str,
) -> KnowledgeRelation:
    """构造 bulk_create_relations 返回的「实际新增」关系（幂等计数语义）。"""
    return KnowledgeRelation(
        id=uuid.uuid4(),
        project_id=PID,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation_type=relation_type,
        created_at=TS,
        updated_at=TS,
    )


def _ai_payload(relations: list[dict]) -> str:
    """构造合法 LLM 提取 JSON 输出（§5.5.4: [{from_name, from_type, to_name, ...}]）。"""
    return json.dumps(relations, ensure_ascii=False)


def _bulk_call(kg: AsyncMock) -> tuple[list[KnowledgeRelationCreate], RelationSource | None]:
    """取 bulk_create_relations 最近一次调用的 (relations, source)，兼容位置/关键字形态。"""
    args, kwargs = kg.bulk_create_relations.await_args
    relations = args[1] if len(args) > 1 else kwargs["relations"]
    source = kwargs.get("source", args[2] if len(args) > 2 else None)
    return relations, source


# ── 服务装配 ────────────────────────────────────────────────────────────────


@pytest.fixture
def harness() -> SimpleNamespace:
    """装配 RelationExtractionService 全依赖（Mock repo + 默认已配模型 + 空 LLM 客户端）。"""
    kg = AsyncMock(spec=KnowledgeGraphService)

    async def _mirror_bulk(project_id, relations, source=None):
        """默认 bulk mock：「全部新增」镜像返回提交的关系（created=提交数语义）。

        真实 bulk_create_relations 返回实际新增列表；「全部新增」场景下
        新增列表 == 提交列表。RED 期默认 return_value=[] 会让
        created=len(新增)=0 与「全部新增」用例断言冲突——此处用 side_effect
        镜像覆盖，使 created == 提交数（幂等用例显式 override 旁路）。
        """
        return [
            _kr(r.source_type, r.source_id, r.target_type, r.target_id, r.relation_type)
            for r in relations
        ]

    kg.bulk_create_relations.side_effect = _mirror_bulk

    repos = {
        "character_repo": AsyncMock(spec=CharacterRepositoryProtocol),
        "world_repo": AsyncMock(spec=WorldRepositoryProtocol),
        "outline_repo": AsyncMock(spec=OutlineRepositoryProtocol),
        "timeline_repo": AsyncMock(spec=TimelineRepositoryProtocol),
        "foreshadow_repo": AsyncMock(spec=ForeshadowingRepositoryProtocol),
        "map_pin_repo": AsyncMock(spec=MapRepositoryProtocol),
        "chapter_repo": AsyncMock(spec=ChapterRepositoryProtocol),
    }
    # 列表/查询类默认空结果；get*/get_by_name 默认 None（「查不到」语义，防 AsyncMock
    # 非 None 假绿：裸 AsyncMock 方法调用返回 truthy 子 mock，会绕过跳过分支）
    repos["world_repo"].list.return_value = ([], 0)
    repos["foreshadow_repo"].list.return_value = ([], 0)
    repos["timeline_repo"].list_all.return_value = []
    repos["map_pin_repo"].list_maps_by_project.return_value = []
    repos["map_pin_repo"].list_pins.return_value = []
    repos["chapter_repo"].list_chapters.return_value = ([], 0)
    for name in ("character_repo", "world_repo", "timeline_repo", "foreshadow_repo"):
        repos[name].get.return_value = None
    for name in ("character_repo", "world_repo", "outline_repo"):
        repos[name].get_by_name.return_value = None

    key_manager = MagicMock()
    key_manager.list_providers.return_value = ["openai"]  # 默认「已配模型」
    key_manager_factory = MagicMock(return_value=key_manager)

    client = AsyncMock()
    client.chat.return_value = ChatResponse(content=_ai_payload([]), model="test-model")
    llm_client_factory = MagicMock(return_value=client)

    service = RelationExtractionService(
        knowledge_graph_service=kg,
        character_repo=repos["character_repo"],
        world_repo=repos["world_repo"],
        outline_repo=repos["outline_repo"],
        timeline_repo=repos["timeline_repo"],
        foreshadow_repo=repos["foreshadow_repo"],
        map_pin_repo=repos["map_pin_repo"],
        chapter_repo=repos["chapter_repo"],
        key_manager_factory=key_manager_factory,
        llm_client_factory=llm_client_factory,
        llm_default_model="test-model",
        extraction_run_repo=None,
    )
    return SimpleNamespace(
        service=service,
        kg=kg,
        repos=repos,
        key_manager_factory=key_manager_factory,
        llm_client_factory=llm_client_factory,
        client=client,
    )


def _disable_model(harness: SimpleNamespace) -> None:
    """把 key_manager 切到「未配置任何模型」态（list_providers 空列表）。"""
    harness.key_manager_factory.return_value.list_providers.return_value = []


def _assert_success_result(result: ExtractionResult, *, created: int) -> None:
    """成功信封契约：type=KNOWLEDGE_RELATION、status=success、updated 恒 0。"""
    assert result.type == ExtractionType.KNOWLEDGE_RELATION  # RED ②（第 7 值尚不存在）
    assert result.status == ExtractionStatus.SUCCESS
    assert result.created == created
    assert result.updated == 0


class TestRuleExtraction:
    """规则提取（method 含 rule）— 三规则集逐条 + 跳过语义 + 封闭枚举。"""

    def test_rule_set_is_closed_enumeration_of_three(self):
        """规则集封闭枚举：RULE_IDS 恰含 3 个标识（§5.5.4「测试断言规则集数量=3」）。"""
        assert len(relation_extraction_service.RULE_IDS) == 3
        assert set(relation_extraction_service.RULE_IDS) == {"r1", "r2", "r3"}

    async def test_r1_world_parent_relation(self, harness: SimpleNamespace):
        """R1: WorldSetting.parent_id 非空 → world(child)→world(parent)「属于」。"""
        parent = _world("天玄大陆")
        child = _world("帝都", parent_id=parent.id)
        harness.repos["world_repo"].list.return_value = ([child], 1)
        harness.repos["world_repo"].get.return_value = parent

        result = await harness.service.extract_for_project(PID, "rule")

        harness.kg.bulk_create_relations.assert_awaited_once()
        relations, source = _bulk_call(harness.kg)
        assert len(relations) == 1
        rel = relations[0]
        assert rel.source_type == EntityType.WORLD
        assert rel.source_id == child.id
        assert rel.target_type == EntityType.WORLD
        assert rel.target_id == parent.id
        assert rel.relation_type == "属于"
        assert source == RelationSource.AI  # 规则与 AI 统一 source=ai
        _assert_success_result(result, created=1)

    async def test_r2_foreshadow_timeline_relation(self, harness: SimpleNamespace):
        """R2: Foreshadowing.event_id 非空 → foreshadow→timeline「锚定于」。"""
        event = _timeline_event("玉佩在重逢时回收")
        fs = _foreshadow("玉佩伏笔", event_id=event.id)
        harness.repos["foreshadow_repo"].list.return_value = ([fs], 1)
        harness.repos["timeline_repo"].get.return_value = event

        result = await harness.service.extract_for_project(PID, "rule")

        relations, source = _bulk_call(harness.kg)
        assert len(relations) == 1
        rel = relations[0]
        assert rel.source_type == EntityType.FORESHADOW
        assert rel.source_id == fs.id
        assert rel.target_type == EntityType.TIMELINE
        assert rel.target_id == event.id
        assert rel.relation_type == "锚定于"
        assert source == RelationSource.AI
        _assert_success_result(result, created=1)

    async def test_r3_map_pin_three_branches(self, harness: SimpleNamespace):
        """R3 三分支: location_id→world「位于」/ ref_id+role→character「出现于地图」/
        ref_id+event→timeline「出现于地图」；type=other 不产出（分支封闭）。"""
        world = _world("天玄大陆")
        character = _character("林尘")
        event = _timeline_event("皇城大战")
        wm = _world_map()
        pin_loc = _map_pin("帝都", location_id=world.id)
        pin_role = _map_pin("林尘", ref_id=character.id, type="role")
        pin_event = _map_pin("大战", ref_id=event.id, type="event")
        pin_other = _map_pin("装饰物", ref_id=event.id, type="other")  # 非 role/event → 无产出
        harness.repos["map_pin_repo"].list_maps_by_project.return_value = [wm]
        harness.repos["map_pin_repo"].list_pins.return_value = [
            pin_loc,
            pin_role,
            pin_event,
            pin_other,
        ]
        harness.repos["world_repo"].get.return_value = world
        harness.repos["character_repo"].get.return_value = character
        harness.repos["timeline_repo"].get.return_value = event

        result = await harness.service.extract_for_project(PID, "rule")

        relations, source = _bulk_call(harness.kg)
        assert len(relations) == 3  # other 分支被排除
        by_target = {(r.target_type, r.relation_type): r for r in relations}
        assert all(r.source_type == EntityType.MAP_PIN for r in relations)
        loc_rel = by_target[(EntityType.WORLD, "位于")]
        assert loc_rel.source_id == pin_loc.id and loc_rel.target_id == world.id
        role_rel = by_target[(EntityType.CHARACTER, "出现于地图")]
        assert role_rel.source_id == pin_role.id and role_rel.target_id == character.id
        evt_rel = by_target[(EntityType.TIMELINE, "出现于地图")]
        assert evt_rel.source_id == pin_event.id and evt_rel.target_id == event.id
        assert source == RelationSource.AI
        _assert_success_result(result, created=3)

    async def test_r1_parent_missing_skips_with_warning(self, harness: SimpleNamespace):
        """目标实体 repo 查不到（get → None）→ 该条跳过 + warnings 含说明，不抛错。"""
        child = _world("帝都", parent_id=uuid.uuid4())  # 父条目已删/跨项目
        harness.repos["world_repo"].list.return_value = ([child], 1)
        harness.repos["world_repo"].get.return_value = None

        result = await harness.service.extract_for_project(PID, "rule")

        harness.kg.bulk_create_relations.assert_not_awaited()  # 无待写关系 → 不调用
        assert result.created == 0
        assert any("跳过" in w or "不存在" in w for w in result.warnings)

    async def test_r2_event_missing_skips_with_warning(self, harness: SimpleNamespace):
        """R2 目标事件查不到 → 跳过 + warning（与 R1 同款语义）。"""
        fs = _foreshadow("玉佩伏笔", event_id=uuid.uuid4())
        harness.repos["foreshadow_repo"].list.return_value = ([fs], 1)
        harness.repos["timeline_repo"].get.return_value = None

        result = await harness.service.extract_for_project(PID, "rule")

        harness.kg.bulk_create_relations.assert_not_awaited()
        assert result.created == 0
        assert any("跳过" in w or "不存在" in w for w in result.warnings)

    async def test_rule_method_never_touches_llm(self, harness: SimpleNamespace):
        """规则路径零 LLM: 不触模型门禁、不调 LLM 客户端（§5.5.4「零 LLM」）。"""
        parent = _world("天玄大陆")
        child = _world("帝都", parent_id=parent.id)
        harness.repos["world_repo"].list.return_value = ([child], 1)
        harness.repos["world_repo"].get.return_value = parent

        await harness.service.extract_for_project(PID, "rule")

        harness.key_manager_factory.assert_not_called()
        harness.llm_client_factory.assert_not_called()
        harness.client.chat.assert_not_awaited()

    @pytest.mark.parametrize("method", ["", "llm", "AI", "rule+ai", "rule ", "ai "])
    async def test_invalid_method_raises_value_error(self, harness: SimpleNamespace, method):
        """非法 method → ValueError（契约: 服务层抛 ValueError，API 层映射 422）。"""
        with pytest.raises(ValueError):
            await harness.service.extract_for_project(PID, method)


class TestAiExtraction:
    """AI 提取（method 含 ai）— 门禁 / 降级 / 输入 / LLM 重试 / 名称解析 / 幂等。"""

    async def test_ai_without_model_raises_llm_not_configured(self, harness: SimpleNamespace):
        """门禁: list_providers() 空 → raise LLMNotConfiguredError（D3 拍板核心）。"""
        _disable_model(harness)

        with pytest.raises(LLMNotConfiguredError):  # RED ②（错误类尚不存在）
            await harness.service.extract_for_project(PID, "ai")

        harness.llm_client_factory.assert_not_called()
        harness.kg.bulk_create_relations.assert_not_awaited()

    async def test_both_without_model_falls_back_to_rules(self, harness: SimpleNamespace):
        """both 未配模型 → 降级仅 rule + warnings 含「AI 提取跳过：未配置模型」（不抛错）。"""
        _disable_model(harness)
        parent = _world("天玄大陆")
        child = _world("帝都", parent_id=parent.id)
        harness.repos["world_repo"].list.return_value = ([child], 1)
        harness.repos["world_repo"].get.return_value = parent

        result = await harness.service.extract_for_project(PID, "both")

        relations, source = _bulk_call(harness.kg)
        assert len(relations) == 1  # R1 规则边照常产出
        assert source == RelationSource.AI
        assert any("未配置模型" in w for w in result.warnings)
        harness.llm_client_factory.assert_not_called()
        _assert_success_result(result, created=1)

    async def test_ai_without_chapters_skipped(self, harness: SimpleNamespace):
        """无章节 → status=skipped、skipped_reason 含「无章节」，不调 LLM。"""
        harness.repos["chapter_repo"].list_chapters.return_value = ([], 0)

        result = await harness.service.extract_for_project(PID, "ai")

        assert result.status == ExtractionStatus.SKIPPED
        assert result.skipped_reason is not None and "无章节" in result.skipped_reason
        harness.llm_client_factory.assert_not_called()
        harness.kg.bulk_create_relations.assert_not_awaited()

    async def test_ai_parse_failure_retries_once(self, harness: SimpleNamespace):
        """LLM 输出解析失败 → 重试一次（chat 恰调用 2 次，F14 extractor 先例）。"""
        chapter = _chapter("第一章", "林尘踏上修行之路。")
        harness.repos["chapter_repo"].list_chapters.return_value = ([chapter], 1)
        char = _character("林尘")
        world = _world("天玄大陆")
        harness.repos["character_repo"].get_by_name.return_value = char
        harness.repos["world_repo"].get_by_name.return_value = world
        harness.client.chat.side_effect = [
            ChatResponse(content="不是 JSON，没有花括号", model="test-model"),
            ChatResponse(
                content=_ai_payload(
                    [
                        {
                            "from_name": "林尘",
                            "from_type": "character",
                            "to_name": "天玄大陆",
                            "to_type": "world",
                            "relation_type": "历练于",
                            "description": "主角在异界历练",
                        }
                    ]
                ),
                model="test-model",
            ),
        ]

        result = await harness.service.extract_for_project(PID, "ai")

        assert harness.client.chat.await_count == 2  # 首次失败 + 重试一次
        relations, source = _bulk_call(harness.kg)
        assert len(relations) == 1
        rel = relations[0]
        assert rel.source_type == EntityType.CHARACTER
        assert rel.source_id == char.id
        assert rel.target_type == EntityType.WORLD
        assert rel.target_id == world.id
        assert rel.relation_type == "历练于"
        assert source == RelationSource.AI
        _assert_success_result(result, created=1)

    async def test_ai_name_resolution_all_types(self, harness: SimpleNamespace):
        """名称解析全类型: character/world/outline 走 get_by_name；
        timeline 走 list_all、foreshadow 走 list，title 精确匹配（strip 首尾空白）。"""
        chapter = _chapter("第一章", "林尘与玉佩重逢。")
        harness.repos["chapter_repo"].list_chapters.return_value = ([chapter], 1)
        char = _character("林尘")
        world = _world("天玄大陆")
        outline = _outline("主线大纲")
        event = _timeline_event("  重逢  ")  # 首尾空白 → 解析须 strip
        fs = _foreshadow("玉佩")
        harness.repos["character_repo"].get_by_name.return_value = char
        harness.repos["world_repo"].get_by_name.return_value = world
        harness.repos["outline_repo"].get_by_name.return_value = outline
        harness.repos["timeline_repo"].list_all.return_value = [event]
        harness.repos["foreshadow_repo"].list.return_value = ([fs], 1)
        harness.client.chat.return_value = ChatResponse(
            content=_ai_payload(
                [
                    {
                        "from_name": "林尘",
                        "from_type": "character",
                        "to_name": "天玄大陆",
                        "to_type": "world",
                        "relation_type": "历练于",
                    },
                    {
                        "from_name": "主线大纲",
                        "from_type": "outline",
                        "to_name": "林尘",
                        "to_type": "character",
                        "relation_type": "包含",
                    },
                    {
                        "from_name": "重逢",
                        "from_type": "timeline",
                        "to_name": "林尘",
                        "to_type": "character",
                        "relation_type": "锚定",
                    },
                    {
                        "from_name": "玉佩",
                        "from_type": "foreshadow",
                        "to_name": "重逢",
                        "to_type": "timeline",
                        "relation_type": "伏笔于",
                    },
                ]
            ),
            model="test-model",
        )

        result = await harness.service.extract_for_project(PID, "ai")

        relations, _ = _bulk_call(harness.kg)
        assert len(relations) == 4
        by_pair = {(r.source_type, r.target_type, r.relation_type): r for r in relations}
        assert by_pair[(EntityType.CHARACTER, EntityType.WORLD, "历练于")].source_id == char.id
        assert by_pair[(EntityType.OUTLINE, EntityType.CHARACTER, "包含")].source_id == outline.id
        assert by_pair[(EntityType.TIMELINE, EntityType.CHARACTER, "锚定")].source_id == event.id
        assert by_pair[(EntityType.FORESHADOW, EntityType.TIMELINE, "伏笔于")].source_id == fs.id
        # get_by_name 以项目内名称为查询键（第 2 位置参数）
        names = [c.args[1] for c in harness.repos["character_repo"].get_by_name.await_args_list]
        assert "林尘" in names
        _assert_success_result(result, created=4)

    async def test_ai_resolution_failure_drops_with_warning(self, harness: SimpleNamespace):
        """名称解析失败（get_by_name → None）→ 该条丢弃 + warnings，不抛错。"""
        chapter = _chapter("第一章", "内容")
        harness.repos["chapter_repo"].list_chapters.return_value = ([chapter], 1)
        harness.repos["character_repo"].get_by_name.return_value = None  # 查不到
        harness.client.chat.return_value = ChatResponse(
            content=_ai_payload(
                [
                    {
                        "from_name": "不存在的人",
                        "from_type": "character",
                        "to_name": "天玄大陆",
                        "to_type": "world",
                        "relation_type": "历练于",
                    }
                ]
            ),
            model="test-model",
        )

        result = await harness.service.extract_for_project(PID, "ai")

        harness.kg.bulk_create_relations.assert_not_awaited()  # 全部丢弃 → 不写
        assert result.created == 0
        assert any("不存在的人" in w or "跳过" in w or "解析" in w for w in result.warnings)

    async def test_ai_created_counts_from_bulk_return(self, harness: SimpleNamespace):
        """幂等: bulk_create_relations 返回实际新增列表；created=len(新增)、updated 恒 0。"""
        chapter = _chapter("第一章", "内容")
        harness.repos["chapter_repo"].list_chapters.return_value = ([chapter], 1)
        char = _character("林尘")
        world = _world("天玄大陆")
        harness.repos["character_repo"].get_by_name.return_value = char
        harness.repos["world_repo"].get_by_name.return_value = world
        harness.client.chat.return_value = ChatResponse(
            content=_ai_payload(
                [
                    {
                        "from_name": "林尘",
                        "from_type": "character",
                        "to_name": "天玄大陆",
                        "to_type": "world",
                        "relation_type": "历练于",
                    },
                    {
                        "from_name": "林尘",
                        "from_type": "character",
                        "to_name": "天玄大陆",
                        "to_type": "world",
                        "relation_type": "战斗于",
                    },
                ]
            ),
            model="test-model",
        )

        # 幂等: 2 条提交，1 条与已有六元组重复被 bulk 内部跳过 → 覆盖 harness
        # 镜像 side_effect，返回实际新增 1 条（side_effect 优先于 return_value）
        async def _dedup_bulk(project_id, relations, source=None):
            return [_kr(EntityType.CHARACTER, char.id, EntityType.WORLD, world.id, "历练于")]

        harness.kg.bulk_create_relations.side_effect = _dedup_bulk

        result = await harness.service.extract_for_project(PID, "ai")

        relations, _ = _bulk_call(harness.kg)
        assert len(relations) == 2  # 提交数不因幂等减少（幂等发生在 bulk 内部）
        assert result.created == 1  # created = len(bulk 实际新增)
        assert result.updated == 0  # ai 提取恒不更新


class TestGuardEnv:
    """守护用例 — 当前应 PASS（仅依赖既有模型，验证测试环境假设，防假绿）。"""

    def test_guard_knowledge_relation_create_dto(self):
        """守护: KnowledgeRelationCreate 六元组 + RelationSource.AI 值可构造（测试数据地基）。"""
        dto = KnowledgeRelationCreate(
            source_type=EntityType.WORLD,
            source_id=uuid.uuid4(),
            target_type=EntityType.WORLD,
            target_id=uuid.uuid4(),
            relation_type="属于",
        )
        assert dto.relation_type == "属于"
        assert dto.description == ""
        assert RelationSource.AI.value == "ai"
        assert EntityType.FORESHADOW.value == "foreshadow"
        assert EntityType.MAP_PIN.value == "map_pin"

    async def test_guard_bulk_call_helper_parses_shape(self):
        """守护: _bulk_call 辅助对 (PID, relations, source=...) 调用形态的解析正确。"""
        kg = AsyncMock()
        kg.bulk_create_relations.return_value = []
        dto = KnowledgeRelationCreate(
            source_type=EntityType.WORLD,
            source_id=uuid.uuid4(),
            target_type=EntityType.WORLD,
            target_id=uuid.uuid4(),
            relation_type="属于",
        )

        await kg.bulk_create_relations(PID, [dto], source=RelationSource.AI)

        relations, source = _bulk_call(kg)
        assert relations == [dto]
        assert source == RelationSource.AI
        assert kg.bulk_create_relations.await_args.args[0] == PID


def _chapter(title: str, content: str):
    """构造测试用章节（惰性 import Chapter 防顶部依赖过重——实际无碍，仅作局部辅助）。"""
    from inkflow.domain.models.chapter import Chapter

    return Chapter(id=uuid.uuid4(), project_id=PID, title=title, content=content)
