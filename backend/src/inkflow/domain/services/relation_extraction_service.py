"""F48 知识图谱关系提取服务 — 规则三规则集 + AI 模板提取（#479 G1 核心交付）.

覆盖 spec f48-knowledge-graph §5.5.4:
- 规则提取（零 LLM）: R1 world 父子「属于」/ R2 foreshadow→timeline「锚定于」/
  R3 map_pin 三分支「位于」「出现于地图」；目标实体查不到 → 跳过 + warning
- AI 提取: LLMNotConfiguredError 门禁 / both 降级 / 无章节 skipped /
  解析失败重试一次 / 名称解析（get_by_name + title 精确匹配）/ 解析失败丢弃
- 幂等: created=len(bulk 实际新增)、updated 恒 0；写入统一 source=RelationSource.AI

遵循 ADR-015: 领域层零 LangChain import，依赖全部构造函数注入（Protocol 类型）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from inkflow.domain.models.character import Character
from inkflow.domain.models.extraction import (
    ExtractionResult,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.knowledge_graph import (
    EntityType,
    KnowledgeRelationCreate,
    RelationSource,
)
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import (
    ForeshadowingRepositoryProtocol,
)
from inkflow.domain.ports.knowledge_graph_errors import LLMNotConfiguredError
from inkflow.domain.ports.llm_client import (
    ChatMessage,
    ChatResponse,
    LLMClientProtocol,
)
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services import _kg_relation_extractor
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService

RULE_IDS: tuple[str, ...] = ("r1", "r2", "r3")
"""规则集封闭枚举 — 恰含 3 个标识（§5.5.4「测试断言规则集数量=3」）."""

_MAX_TEXT_LENGTH = 50000
"""AI 提取章节正文拼接截断上限（与 ExtractionRequest.text 上限一致）."""

_MAX_PARSE_ATTEMPTS = 2
"""LLM 输出解析尝试次数（首次失败 + 重试一次）."""

_Entity = Character | WorldSetting | Outline | TimelineEvent | Foreshadowing
"""名称解析目标实体联合类型（AI 只产出五类，map_pin 不参与）."""


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为存储层 int id（沿用 F1 `_to_int_id` 模式）."""

    if isinstance(value, uuid.UUID):
        return value.int
    return value  # pragma: no cover  # 调用方恒传 UUID，int 分支为防御性类型兼容


class _KeyManagerProtocol(Protocol):
    """APIKeyManager 形态子集（AI 门禁只需 list_providers）."""

    def list_providers(self) -> list[str]: ...


@dataclass
class _AiOutcome:
    """AI 提取中间结果 — 解析/名称解析后的关系与 warning 汇总."""

    relations: list[KnowledgeRelationCreate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: str | None = None


class RelationExtractionService:
    """知识图谱关系提取服务（spec f48 §5.5.4）.

    method 为 rule/ai/both 三态：rule 走确定性三规则集（零 LLM）；ai 走
    LLM 模板提取（未配置模型 → LLMNotConfiguredError 门禁）；both 先 rule
    后 ai（未配置模型时降级仅 rule）。
    """

    def __init__(
        self,
        *,
        knowledge_graph_service: KnowledgeGraphService,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        outline_repo: OutlineRepositoryProtocol,
        timeline_repo: TimelineRepositoryProtocol,
        foreshadow_repo: ForeshadowingRepositoryProtocol,
        map_pin_repo: MapRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        key_manager_factory: Callable[[], _KeyManagerProtocol] | None = None,
        llm_client_factory: Callable[[], LLMClientProtocol] | None = None,
        llm_default_model: str | None = None,
        extraction_run_repo: object | None = None,
    ) -> None:
        self._knowledge_graph_service = knowledge_graph_service
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._outline_repo = outline_repo
        self._timeline_repo = timeline_repo
        self._foreshadow_repo = foreshadow_repo
        self._map_pin_repo = map_pin_repo
        self._chapter_repo = chapter_repo
        self._key_manager_factory = key_manager_factory
        self._llm_client_factory = llm_client_factory
        self._llm_default_model = llm_default_model
        self._extraction_run_repo = extraction_run_repo

    # ── 公共入口 ─────────────────────────────────────────────────────────

    async def extract_for_project(self, project_id: uuid.UUID, method: str) -> ExtractionResult:
        """执行知识图谱关系提取（按 method 组合规则与 AI 路径）.

        Args:
            project_id: 目标项目 UUID.
            method: rule / ai / both（非法值 → ValueError，API 层映射 422）.

        Returns:
            统一 ExtractionResult 信封（type=KNOWLEDGE_RELATION）.

        Raises:
            ValueError: method 非 rule/ai/both.
            LLMNotConfiguredError: method=ai 且未配置任何模型.
        """

        if method not in {"rule", "ai", "both"}:
            raise ValueError(f"非法提取方法: {method}，仅支持 rule/ai/both")

        pid_int = _to_int_id(project_id)
        relations: list[KnowledgeRelationCreate] = []
        warnings: list[str] = []
        model: str | None = None

        if method in {"rule", "both"}:
            await self._extract_rules(pid_int, relations, warnings)

        if method in {"ai", "both"}:
            providers: list[str] = []
            if self._key_manager_factory is not None:
                providers = self._key_manager_factory().list_providers()
            if not providers:
                if method == "both":
                    warnings.append("AI 提取跳过：未配置模型")
                else:
                    raise LLMNotConfiguredError()
            else:
                outcome = await self._extract_ai(pid_int)
                if outcome is None:
                    if method == "ai":
                        return ExtractionResult(
                            type=ExtractionType.KNOWLEDGE_RELATION,
                            status=ExtractionStatus.SKIPPED,
                            skipped_reason="无章节内容",
                            created=0,
                            updated=0,
                            warnings=[],
                        )
                    warnings.append("无章节内容，AI 提取跳过")
                else:
                    relations.extend(outcome.relations)
                    warnings.extend(outcome.warnings)
                    model = outcome.model

        if not relations:
            return ExtractionResult(
                type=ExtractionType.KNOWLEDGE_RELATION,
                status=ExtractionStatus.SUCCESS,
                created=0,
                updated=0,
                warnings=warnings,
                model=model,
            )
        created_rows = await self._knowledge_graph_service.bulk_create_relations(
            project_id, relations, source=RelationSource.AI
        )
        return ExtractionResult(
            type=ExtractionType.KNOWLEDGE_RELATION,
            status=ExtractionStatus.SUCCESS,
            created=len(created_rows),
            updated=0,
            warnings=warnings,
            model=model,
        )

    # ── 规则提取（零 LLM） ────────────────────────────────────────────────

    async def _extract_rules(
        self,
        pid_int: int,
        relations: list[KnowledgeRelationCreate],
        warnings: list[str],
    ) -> None:
        """规则提取三规则集：R1 父子世界观 / R2 伏笔事件 / R3 地图 pin."""

        await self._rule_r1(pid_int, relations, warnings)
        await self._rule_r2(pid_int, relations, warnings)
        await self._rule_r3(pid_int, relations, warnings)

    async def _rule_r1(
        self,
        pid_int: int,
        relations: list[KnowledgeRelationCreate],
        warnings: list[str],
    ) -> None:
        """R1: WorldSetting.parent_id 非空 → world(child)→world(parent)「属于」."""

        worlds, _ = await self._world_repo.list(pid_int)
        for child in worlds:
            if child.parent_id is None:
                continue
            parent = await self._world_repo.get(_to_int_id(child.parent_id))
            if parent is None:
                warnings.append(f"R1 跳过: 世界观 {child.name} 的父条目不存在")
                continue
            relations.append(
                KnowledgeRelationCreate(
                    source_type=EntityType.WORLD,
                    source_id=child.id,
                    target_type=EntityType.WORLD,
                    target_id=parent.id,
                    relation_type="属于",
                )
            )

    async def _rule_r2(
        self,
        pid_int: int,
        relations: list[KnowledgeRelationCreate],
        warnings: list[str],
    ) -> None:
        """R2: Foreshadowing.event_id 非空 → foreshadow→timeline「锚定于」."""

        foreshadows, _ = await self._foreshadow_repo.list(pid_int)
        for fs in foreshadows:
            if fs.event_id is None:
                continue
            event = await self._timeline_repo.get(_to_int_id(fs.event_id))
            if event is None:
                warnings.append(f"R2 跳过: 伏笔 {fs.title} 锚定的事件不存在")
                continue
            relations.append(
                KnowledgeRelationCreate(
                    source_type=EntityType.FORESHADOW,
                    source_id=fs.id,
                    target_type=EntityType.TIMELINE,
                    target_id=event.id,
                    relation_type="锚定于",
                )
            )

    async def _rule_r3(
        self,
        pid_int: int,
        relations: list[KnowledgeRelationCreate],
        warnings: list[str],
    ) -> None:
        """R3 三分支: location→world「位于」/ role→character「出现于地图」/
        event→timeline「出现于地图」；type=other 不产出."""

        maps = await self._map_pin_repo.list_maps_by_project(pid_int)
        for wm in maps:
            pins = await self._map_pin_repo.list_pins(_to_int_id(wm.id))
            for pin in pins:
                if pin.type == "other":
                    continue
                if pin.location_id is not None:
                    world = await self._world_repo.get(_to_int_id(pin.location_id))
                    if world is None:
                        warnings.append(f"R3 跳过: pin {pin.label} 关联的地点不存在")
                        continue
                    relations.append(
                        KnowledgeRelationCreate(
                            source_type=EntityType.MAP_PIN,
                            source_id=pin.id,
                            target_type=EntityType.WORLD,
                            target_id=world.id,
                            relation_type="位于",
                        )
                    )
                    continue
                if pin.ref_id is not None and pin.type == "role":
                    character = await self._character_repo.get(_to_int_id(pin.ref_id))
                    if character is None:
                        warnings.append(f"R3 跳过: pin {pin.label} 关联的角色不存在")
                        continue
                    relations.append(
                        KnowledgeRelationCreate(
                            source_type=EntityType.MAP_PIN,
                            source_id=pin.id,
                            target_type=EntityType.CHARACTER,
                            target_id=character.id,
                            relation_type="出现于地图",
                        )
                    )
                    continue
                if pin.ref_id is not None and pin.type == "event":
                    event = await self._timeline_repo.get(_to_int_id(pin.ref_id))
                    if event is None:
                        warnings.append(f"R3 跳过: pin {pin.label} 关联的事件不存在")
                        continue
                    relations.append(
                        KnowledgeRelationCreate(
                            source_type=EntityType.MAP_PIN,
                            source_id=pin.id,
                            target_type=EntityType.TIMELINE,
                            target_id=event.id,
                            relation_type="出现于地图",
                        )
                    )

    # ── AI 提取 ───────────────────────────────────────────────────────────

    async def _extract_ai(self, pid_int: int) -> _AiOutcome | None:
        """AI 模板提取: 章节输入 → LLM 调用 → 解析重试 → 名称解析.

        Returns:
            None 表示无章节（调用方按 skipped 语义处理）.
        """

        chapters, _ = await self._chapter_repo.list_chapters(pid_int)
        if not chapters:
            return None
        text = "".join(chapter.content for chapter in chapters)[:_MAX_TEXT_LENGTH]

        assert self._llm_client_factory is not None  # AI 门禁已通过，装配必注入工厂
        client = self._llm_client_factory()
        messages = _kg_relation_extractor.build_kg_relation_messages(text)
        response, parsed, error = await self._chat_with_retry(client, messages)
        if parsed is None:
            return _AiOutcome(warnings=[f"AI 提取解析失败: {error}"])

        warnings: list[str] = []
        relations: list[KnowledgeRelationCreate] = []
        for item in parsed:
            relation = await self._resolve_item(pid_int, item, warnings)
            if relation is not None:
                relations.append(relation)
        model = response.model if response is not None else self._llm_default_model
        return _AiOutcome(relations=relations, warnings=warnings, model=model)

    async def _chat_with_retry(
        self,
        client: LLMClientProtocol,
        messages: list[ChatMessage],
    ) -> tuple[ChatResponse | None, list[dict[str, Any]] | None, str]:
        """调用 LLM 并解析关系数组；解析失败重试一次（chat 恰调 2 次）."""

        history = list(messages)
        response: ChatResponse | None = None
        last_error = ""
        for _ in range(_MAX_PARSE_ATTEMPTS):
            response = await client.chat(list(history), model=self._llm_default_model)
            parsed, last_error = _kg_relation_extractor.parse_kg_relations(response.content)
            if parsed is not None:
                return response, parsed, ""
            history.append(ChatMessage(role="assistant", content=response.content))
            history.append(
                ChatMessage(
                    role="user",
                    content=_kg_relation_extractor.build_fix_prompt(last_error),
                )
            )
        return response, None, last_error

    async def _resolve_item(
        self,
        pid_int: int,
        item: dict[str, Any],
        warnings: list[str],
    ) -> KnowledgeRelationCreate | None:
        """名称解析单条关系；解析失败 → 丢弃 + warning（不抛错）."""

        source_type = EntityType(item["from_type"])
        target_type = EntityType(item["to_type"])
        source = await self._resolve_entity(pid_int, source_type, item["from_name"])
        target = await self._resolve_entity(pid_int, target_type, item["to_name"])
        if source is None or target is None:
            warnings.append(f"关系 {item['from_name']} -> {item['to_name']} 实体解析失败，已跳过")
            return None
        return KnowledgeRelationCreate(
            source_type=source_type,
            source_id=source.id,
            target_type=target_type,
            target_id=target.id,
            relation_type=item["relation_type"],
            description=str(item.get("description", "")),
        )

    async def _resolve_entity(
        self,
        pid_int: int,
        entity_type: EntityType,
        name: str,
    ) -> _Entity | None:
        """实体名称 → id 解析: character/world/outline 走 get_by_name，
        timeline/foreshadow 走列表 title 精确匹配（strip 首尾空白）."""

        if entity_type is EntityType.CHARACTER:
            return await self._character_repo.get_by_name(pid_int, name)
        if entity_type is EntityType.WORLD:
            return await self._world_repo.get_by_name(pid_int, name)
        if entity_type is EntityType.OUTLINE:
            return await self._outline_repo.get_by_name(pid_int, name)
        if entity_type is EntityType.TIMELINE:
            events = await self._timeline_repo.list_all(pid_int)
            return next(
                (event for event in events if event.title.strip() == name.strip()),
                None,
            )
        if entity_type is EntityType.FORESHADOW:
            foreshadows, _ = await self._foreshadow_repo.list(pid_int)
            return next(
                (fs for fs in foreshadows if fs.title.strip() == name.strip()),
                None,
            )
        return None  # pragma: no cover  # AI 门禁保证五类，map_pin 不可达
