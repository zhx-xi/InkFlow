"""F14 统一提取服务门面 — 分发 / 增量判定 / 结果归一 / RAG 索引编排.

ExtractionService 是 F14 的横切收敛核心（spec §5）: 把 F9-F13 已存在的
提取/生成/检查管线收敛到统一接口（ExtractionType 6 种）背后，叠加两块
横切能力——增量提取（源内容 sha256 hash 变更追踪，只处理变更源，§5.2）
与 RAG 向量索引（ADR-013，§5.6）。

门面零业务逻辑（§5.1 要点 1）: 提取/合并/校验语义全部在委托管线内
（CharacterService.extract / WorldService.extract / OutlineService.generate /
TimelineService.check_consistency / ForeshadowingExtractor /
TimelineExtractor），本类只做:
① 项目存在性校验（统一 404 语义）
② 类型注册表查 handler（STYLE 占位 422，§6.1）
③ 增量判定（_resolve_sources: hash 比对 run 表，skip 时不调用 LLM）
④ 逐源分发执行（_dispatch: 各类型请求构造 + 结果归一化，§5.3）
⑤ 每源成功后立即 upsert ExtractionRun（断点续跑基础，§6.2）
⑥ index=true 时索引本次产物（§5.6）
⑦ 汇总返回 ExtractionResult

TIMELINE 双语义（§5.5）: 设置项判定在门面层——请求 auto_extract 显式值
→ 项目配置 project.config.extra["timeline_auto_extract"] → 默认 false；
开启 = TimelineExtractor（LLM 提取，按源 hash 增量），关闭 =
TimelineService.check_consistency（F12 确定性检查，每次执行，无 LLM）。

遵循 ADR-002/015: 领域层零框架 import，依赖全部通过构造函数注入
（Protocol 类型），测试注入 Mock。

依据: specs/f14-extraction-service/spec.md §5.1-§5.6/§6/§7/§8。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterExtractRequest,
)
from inkflow.domain.models.extraction import (
    ExtractionRequest,
    ExtractionResult,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
    ReindexResult,
)
from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingExtractionResult,
    ForeshadowingExtractRequest,
)
from inkflow.domain.models.outline import OutlineGenerateRequest
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineEvent,
    TimelineExtractionResult,
    TimelineExtractRequest,
)
from inkflow.domain.models.world import WorldExtractionResult, WorldExtractRequest, WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.extraction_errors import (
    ChapterNotFoundError,
    ChapterNotInProjectError,
    ExtractionValidationError,
    RAGUnavailableError,
    StyleNotImplementedError,
    UnsupportedExtractionTypeError,
)
from inkflow.domain.ports.extraction_run_repository import ExtractionRunRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.vector_store import (
    EntityType,
    IndexableEntity,
    RetrievedEntity,
    VectorStoreProtocol,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._chunking import chunk_text
from inkflow.domain.services._foreshadowing_extractor import ForeshadowingExtractor
from inkflow.domain.services._timeline_extractor import TimelineExtractor
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.outline_service import OutlineService
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.domain.services.world_service import WorldService

logger = logging.getLogger(__name__)

_MAX_CHAPTER_CHARS = 50000
"""单章提取上限（spec §5.2/§7: 超限 422，分块提取归 Phase 2+）。"""

_REINDEX_PAGE_SIZE = 100
"""reindex 分页循环页大小（spec §5.6: list(limit=100)）。"""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _content_hash(text: str) -> str:
    """计算源内容 sha256 指纹（UTF-8 hexdigest，增量判定依据，§5.2）。"""
    return sha256(text.encode("utf-8")).hexdigest()


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）。"""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


@dataclass
class _Source:
    """单个提取源 — 增量判定与逐源执行的最小单元（spec §5.2）。

    Attributes:
        key: 源标识（run.source_key: 章节模式=str(chapter_id)、手动="manual"、
            outline/timeline（关闭时）固定 "full"）.
        label: 人类可读标签（skip 原因文案用，如「chapter <id>」）.
        hash: 源内容 sha256 指纹（增量判定依据）.
        skip: 增量判定结果（True = 内容未变更，跳过不调用 LLM）.
        text: 源文本内容（章节内容 / 手动文本；outline 与 timeline 关闭时为 None）.
        chapter_id: 来源章节 UUID（仅章节模式；用于时间线提取锚点与 chapter_chunk 索引）.
        title: 章节标题（chapter_chunk 索引 metadata 用）.
    """

    key: str
    label: str
    hash: str
    skip: bool
    text: str | None = None
    chapter_id: uuid.UUID | None = None
    title: str | None = None


@dataclass
class _Normalized:
    """归一化后的管线结果（spec §5.3 各类型口径）.

    Attributes:
        created: 归一化「新增」计数.
        updated: 归一化「更新」计数.
        warnings: 该源管线 warning 列表.
        model: 实际使用的 LLM 模型（timeline 关闭时为 None）.
        detail: 原始结果 model_dump（mode="json"）.
        raw: 原始管线结果对象（RAG 索引编排取实体用）.
    """

    created: int
    updated: int
    warnings: list[str]
    model: str | None
    detail: dict[str, Any]
    raw: Any


def _normalize_result(type_: ExtractionType, result: Any) -> _Normalized:
    """将各管线原始结果归一为统一口径（spec §5.3 表）.

    character/setting/foreshadowing/timeline（开启时）: created/updated 为
    实体列表长度；outline: save=true 且新建 → 1、预览 → 0、updated 恒 0。
    timeline 关闭语义（ConsistencyReport）在 _dispatch 内单独归一。
    """
    if type_ is ExtractionType.OUTLINE:
        return _Normalized(
            created=1 if result.saved else 0,
            updated=0,
            warnings=list(result.warnings),
            model=result.model,
            detail=result.model_dump(mode="json"),
            raw=result,
        )
    return _Normalized(
        created=len(result.created),
        updated=len(result.updated),
        warnings=list(result.warnings),
        model=result.model,
        detail=result.model_dump(mode="json"),
        raw=result,
    )


def _project_character(character: Character, project_id: str) -> IndexableEntity:
    """角色档案 → IndexableEntity（§5.6 投影表: content 四字段拼装）。"""
    return IndexableEntity(
        id=str(character.id),
        entity_type=EntityType.CHARACTER,
        project_id=project_id,
        content=(
            f"姓名：{character.name}\n"
            f"性格：{character.personality}\n"
            f"背景：{character.background}\n"
            f"目标：{character.goals}"
        ),
        metadata={"name": character.name, "project_id": project_id},
    )


def _project_setting(setting: WorldSetting, project_id: str) -> IndexableEntity:
    """世界观条目 → IndexableEntity（§5.6 投影表）。"""
    return IndexableEntity(
        id=str(setting.id),
        entity_type=EntityType.SETTING,
        project_id=project_id,
        content=(
            f"名称：{setting.name}\n" f"分类：{setting.category}\n" f"内容：{setting.content}"
        ),
        metadata={
            "name": setting.name,
            "category": setting.category,
            "project_id": project_id,
        },
    )


def _project_foreshadowing(foreshadowing: Foreshadowing, project_id: str) -> IndexableEntity:
    """伏笔档案 → IndexableEntity（§5.6 投影表）。"""
    return IndexableEntity(
        id=str(foreshadowing.id),
        entity_type=EntityType.FORESHADOWING,
        project_id=project_id,
        content=(
            f"伏笔：{foreshadowing.title}\n"
            f"{foreshadowing.description}\n"
            f"（埋设位置：{foreshadowing.location}）"
        ),
        metadata={
            "name": foreshadowing.title,
            "status": foreshadowing.status.value,
            "project_id": project_id,
        },
    )


def _project_timeline_event(event: TimelineEvent, project_id: str) -> IndexableEntity:
    """时间线事件 → IndexableEntity（§5.6 投影表；chapter_id = source_chapter_id）。"""
    metadata: dict[str, str | int | float] = {
        "title": event.title,
        "timeline_flag": event.timeline_flag,
        "project_id": project_id,
    }
    if event.source_chapter_id is not None:
        metadata["chapter_id"] = str(event.source_chapter_id)
    return IndexableEntity(
        id=str(event.id),
        entity_type=EntityType.TIMELINE_EVENT,
        project_id=project_id,
        content=(
            f"事件：{event.title}\n"
            f"{event.description}\n"
            f"时间：{event.time_value} {event.time_unit}\n"
            f"叙事位置：{event.narrative_position}"
        ),
        metadata=metadata,
    )


def _project_chapter_chunk(
    chapter_id: uuid.UUID,
    chapter_title: str,
    chunk_index: int,
    chunk: str,
    project_id: str,
) -> IndexableEntity:
    """章节文本块 → IndexableEntity（§5.6 投影表；块 id = {chapter_id}:{idx}）。"""
    return IndexableEntity(
        id=f"{chapter_id}:{chunk_index}",
        entity_type=EntityType.CHAPTER_CHUNK,
        project_id=project_id,
        content=chunk,
        metadata={
            "chapter_id": str(chapter_id),
            "chapter_title": chapter_title,
            "chunk_index": chunk_index,
            "project_id": project_id,
        },
    )


class ExtractionService:
    """统一提取服务门面（spec §5）— 分发 6 种类型 + 增量提取 + RAG 编排.

    依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:

    Args:
        project_repo: 项目仓储（F1），项目存在性统一校验（§5.1 要点 2）.
        chapter_repo: 章节仓储（F2），章节模式源读取（§5.2）与 reindex 章节分块.
        run_repo: 增量追踪记录仓储（§8.1），增量判定 + 逐源落库.
        character_service: F9 角色服务（CHARACTER 委托 extract）.
        world_service: F10 世界观服务（SETTING 委托 extract）.
        outline_service: F11 大纲服务（OUTLINE 委托 generate）.
        timeline_service: F12 时间线服务（TIMELINE 关闭语义委托 check_consistency）.
        foreshadowing_extractor: F14 伏笔提取管线（FORESHADOWING 委托）.
        timeline_extractor: F14 时间线提取管线（TIMELINE 开启语义委托）.
        character_repo / world_repo / timeline_repo / foreshadowing_repo:
            reindex 全量重建用档案仓储（§5.6）.
        vector_store: RAG 向量存储（ADR-013）；None = 未装配，
            index=true / reindex / retrieve 时报 RAGUnavailableError（§5.6/§6.3）.
    """

    def __init__(
        self,
        *,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        run_repo: ExtractionRunRepositoryProtocol,
        character_service: CharacterService,
        world_service: WorldService,
        outline_service: OutlineService,
        timeline_service: TimelineService,
        foreshadowing_extractor: ForeshadowingExtractor,
        timeline_extractor: TimelineExtractor,
        character_repo: CharacterRepositoryProtocol | None = None,
        world_repo: WorldRepositoryProtocol | None = None,
        timeline_repo: TimelineRepositoryProtocol | None = None,
        foreshadowing_repo: ForeshadowingRepositoryProtocol | None = None,
        vector_store: VectorStoreProtocol | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._chapter_repo = chapter_repo
        self._run_repo = run_repo
        self._character_service = character_service
        self._world_service = world_service
        self._outline_service = outline_service
        self._timeline_service = timeline_service
        self._foreshadowing_extractor = foreshadowing_extractor
        self._timeline_extractor = timeline_extractor
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._timeline_repo = timeline_repo
        self._foreshadowing_repo = foreshadowing_repo
        self._vector_store = vector_store

        # 类型注册表（spec §6.1: 6 槽，5 实现 + 1 占位）。
        # TIMELINE 槽位为双 handler 选择器（§5.5: 设置项开启 → TimelineExtractor，
        # 关闭 → TimelineService.check_consistency）；STYLE 槽位 handler=None → 422。
        self._handlers: dict[ExtractionType, Callable[..., Any] | None] = {
            ExtractionType.CHARACTER: self._character_service.extract,
            ExtractionType.SETTING: self._world_service.extract,
            ExtractionType.OUTLINE: self._outline_service.generate,
            ExtractionType.TIMELINE: self._timeline_handler,
            ExtractionType.FORESHADOWING: self._foreshadowing_extractor.extract,
            ExtractionType.STYLE: None,
        }

    # ── 统一提取入口（spec §5.1 模式总览）────────────────────────

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """执行统一提取 — 项目校验 → 类型查表 → 增量判定 → 逐源执行 → 可选索引.

        Args:
            request: 统一提取请求（6 种类型，type 决定参数语义）.

        Returns:
            统一结果信封（ExtractionResult，§5.3）.

        Raises:
            ProjectNotFoundError: 项目不存在（404 语义）.
            StyleNotImplementedError: STYLE 类型未实现（422 占位）.
            UnsupportedExtractionTypeError: 未注册类型（422，防御性）.
            ExtractionValidationError: 类型相关参数不合法（422）.
            ChapterNotFoundError / ChapterNotInProjectError: 章节校验失败（422）.
            LLMRequestError / 各管线错误: 透传（router 转 500）.
            RAGUnavailableError: index=true 但向量存储未装配（500）.
        """
        # ① 门面统一校验项目存在（所有类型统一，§5.1 要点 2）
        project = await self._project_repo.get(_to_int_id(request.project_id))
        if project is None:
            raise ProjectNotFoundError()

        # ② 类型注册表查 handler（§6.1: STYLE 占位 → 422；未注册 → 422 防御）
        handler = self._handlers.get(request.type)
        if handler is None:
            if request.type is ExtractionType.STYLE:
                raise StyleNotImplementedError()
            raise UnsupportedExtractionTypeError()

        # ③ 类型相关输入约束（§6.4）+ 增量判定（§5.2: skip 时不调用 LLM）
        self._validate_input(request, project)
        sources = await self._resolve_sources(request, project)

        # ④⑤ 逐源执行 + 每源成功后立即 upsert run（断点续跑基础，§6.2）
        result, executed = await self._run_sources(request, sources, project)

        # ⑥ index=true → 索引本次产物（§5.6；outline/timeline 关闭时忽略 + warning）
        if request.index:
            if self._indexing_enabled(request, project):
                if result.status is ExtractionStatus.SUCCESS and executed:
                    if self._vector_store is None:
                        raise RAGUnavailableError()
                    entities = self._collect_index_entities(request, executed)
                    if entities:
                        await self._vector_store.index_batch(entities)
                    result.indexed = True
            else:
                result.warnings.append("outline/timeline 类型不支持自动索引")

        # ⑦ 汇总返回（result 由 _run_sources 构建）
        return result

    # ── 增量判定（spec §5.2）────────────────────────────────────

    def _validate_input(self, request: ExtractionRequest, project: Project) -> None:
        """类型相关输入约束（spec §6.4）— 类型不匹配字段一律 422 显式报错."""
        has_source = request.text is not None or request.chapter_ids is not None
        if request.type is ExtractionType.OUTLINE:
            if has_source:
                raise ExtractionValidationError(
                    "outline 类型不支持 text/chapter_ids（使用 prompt/num_chapters）"
                )
            return
        if request.type is ExtractionType.TIMELINE:
            if not self._auto_extract_on(request, project):
                if has_source:
                    raise ExtractionValidationError(
                        "时间线自动提取未开启（配置 timeline_auto_extract）"
                    )
                return
            if request.text is not None:
                raise ExtractionValidationError("时间线自动提取仅支持章节模式（chapter_ids）")
            if request.chapter_ids is None:
                raise ExtractionValidationError("timeline 类型必须提供 text 或 chapter_ids")
            return
        if not has_source:
            raise ExtractionValidationError(
                "character/setting/foreshadowing 类型必须提供 text 或 chapter_ids"
            )

    async def _resolve_sources(self, request: ExtractionRequest, project: Project) -> list[_Source]:
        """计算待执行源列表（含 skip 判定，spec §5.2 伪代码）.

        outline 与 timeline（设置项关闭）固定单源 "full"、每次执行；
        timeline（开启）与 character/setting/foreshadowing 按源 hash 增量:
        章节模式逐章读取校验（不存在/跨项目/超长 → 422），手动模式单源
        source_key="manual"。
        """
        if request.type is ExtractionType.OUTLINE:
            return [_Source(key="full", label="full", hash=_content_hash(""), skip=False)]
        if request.type is ExtractionType.TIMELINE and not self._auto_extract_on(request, project):
            return [_Source(key="full", label="full", hash=_content_hash(""), skip=False)]

        if request.text is not None:
            h = _content_hash(request.text)
            run = await self._run_repo.get(_to_int_id(request.project_id), request.type, "manual")
            skip = run is not None and run.content_hash == h and not request.force
            return [_Source(key="manual", label="manual", hash=h, skip=skip, text=request.text)]

        sources: list[_Source] = []
        for chapter_id in request.chapter_ids or []:
            chapter = await self._chapter_repo.get_chapter(_to_int_id(chapter_id))
            if chapter is None:
                raise ChapterNotFoundError()  # F2 get 不含软删
            if chapter.project_id != request.project_id:
                raise ChapterNotInProjectError()
            if len(chapter.content) > _MAX_CHAPTER_CHARS:
                raise ExtractionValidationError("章节内容超过提取上限（50000 字符）")
            h = _content_hash(chapter.content)
            run = await self._run_repo.get(
                _to_int_id(request.project_id), request.type, str(chapter_id)
            )
            skip = run is not None and run.content_hash == h and not request.force
            sources.append(
                _Source(
                    key=str(chapter_id),
                    label=f"chapter {chapter_id}",
                    hash=h,
                    skip=skip,
                    text=chapter.content,
                    chapter_id=chapter_id,
                    title=chapter.title,
                )
            )
        return sources

    # ── 逐源执行（spec §5.2/§5.3/§6.2）──────────────────────────

    async def _run_sources(
        self,
        request: ExtractionRequest,
        sources: list[_Source],
        project: Project,
    ) -> tuple[ExtractionResult, list[tuple[_Source, Any]]]:
        """逐源执行管线；失败立即抛异常（已成功源 run 已落库，重跑自动 skip）.

        Returns:
            (汇总 ExtractionResult, 已执行源与原始结果列表（索引编排用）).
        """
        processed = skipped = created = updated = 0
        warnings: list[str] = []
        model: str | None = None
        detail: dict[str, Any] = {}
        executed: list[tuple[_Source, Any]] = []
        run_indexed = request.index and self._indexing_enabled(request, project)

        for src in sources:
            if src.skip:
                skipped += 1
                continue
            normalized = await self._dispatch(request, src, project)
            processed += 1
            created += normalized.created
            updated += normalized.updated
            warnings.extend(normalized.warnings)
            model = normalized.model or model
            if processed == 1:  # detail 保留首个执行源的原始结果（§5.3）
                detail = normalized.detail
            executed.append((src, normalized.raw))
            await self._run_repo.upsert(
                ExtractionRun(
                    id=0,  # DB 自增主键占位（同仓储测试约定）
                    project_id=request.project_id,
                    type=request.type,
                    source_key=src.key,
                    content_hash=src.hash,
                    status=ExtractionStatus.SUCCESS,
                    created_count=normalized.created,
                    updated_count=normalized.updated,
                    warnings_json=json.dumps(warnings, ensure_ascii=False),
                    model=normalized.model,
                    indexed=run_indexed,
                    run_at=_utcnow(),
                )
            )
            logger.info(
                "提取完成: project=%s type=%s source=%s created=%d updated=%d",
                request.project_id,
                request.type.value,
                src.key,
                normalized.created,
                normalized.updated,
            )

        if processed == 0:
            # 全源 skip: 对首个源 upsert 一行 skipped（记录确认事实，§6.2）
            first = sources[0]
            await self._run_repo.upsert(
                ExtractionRun(
                    id=0,
                    project_id=request.project_id,
                    type=request.type,
                    source_key=first.key,
                    content_hash=first.hash,
                    status=ExtractionStatus.SKIPPED,
                    run_at=_utcnow(),
                )
            )
            return (
                ExtractionResult(
                    type=request.type,
                    status=ExtractionStatus.SKIPPED,
                    skipped_reason=f"内容未变更（源: {first.label}）",
                    processed_sources=0,
                    skipped_sources=skipped,
                ),
                [],
            )

        return (
            ExtractionResult(
                type=request.type,
                status=ExtractionStatus.SUCCESS,
                processed_sources=processed,
                skipped_sources=skipped,
                created=created,
                updated=updated,
                warnings=warnings,
                model=model,
                detail=detail,
            ),
            executed,
        )

    async def _dispatch(
        self, request: ExtractionRequest, source: _Source, project: Project
    ) -> _Normalized:
        """按类型分发到对应管线并归一化结果（spec §5.1 步骤 ④/§5.3）."""
        result: Any
        if request.type is ExtractionType.CHARACTER:
            result = await self._character_service.extract(
                CharacterExtractRequest(
                    project_id=request.project_id,
                    text=source.text or "",
                    model=request.model,
                )
            )
        elif request.type is ExtractionType.SETTING:
            result = await self._world_service.extract(
                WorldExtractRequest(
                    project_id=request.project_id,
                    text=source.text or "",
                    model=request.model,
                )
            )
        elif request.type is ExtractionType.OUTLINE:
            result = await self._outline_service.generate(
                OutlineGenerateRequest(
                    project_id=request.project_id,
                    prompt=request.prompt,
                    num_chapters=request.num_chapters,
                    save=request.save,
                    model=request.model,
                )
            )
        elif request.type is ExtractionType.TIMELINE:
            result = await self._timeline_handler(request, source, project)
            if result is None:  # 防御: 项目已校验存在，正常不会发生
                return _Normalized(0, 0, [], None, {}, None)
            if isinstance(result, ConsistencyReport):
                # 设置项关闭: F12 确定性检查，无 LLM（§5.3 口径）
                return _Normalized(
                    created=0,
                    updated=0,
                    warnings=[],
                    model=None,
                    detail=result.model_dump(mode="json"),
                    raw=result,
                )
            # 设置项开启: TimelineExtractionResult（§5.5）
            return _Normalized(
                created=len(result.created),
                updated=len(result.updated),
                warnings=list(result.warnings),
                model=result.model,
                detail=result.model_dump(mode="json"),
                raw=result,
            )
        elif request.type is ExtractionType.FORESHADOWING:
            result = await self._foreshadowing_extractor.extract(
                ForeshadowingExtractRequest(
                    project_id=request.project_id,
                    text=source.text or "",
                    model=request.model,
                ),
                default_model=project.config.model,
            )
        else:
            raise UnsupportedExtractionTypeError()
        return _normalize_result(request.type, result)

    async def _timeline_handler(
        self,
        request: ExtractionRequest,
        source: _Source,
        project: Project,
    ) -> ConsistencyReport | TimelineExtractionResult | None:
        """TIMELINE 槽位双 handler 选择器（§5.5）— 设置项判定在门面层.

        开启 → TimelineExtractor.extract（LLM 提取，章节源）; 关闭 →
        TimelineService.check_consistency（F12 确定性检查，无 LLM）。
        """
        if self._auto_extract_on(request, project):
            if source.chapter_id is None:
                raise ExtractionValidationError("时间线自动提取仅支持章节模式（chapter_ids）")
            return await self._timeline_extractor.extract(
                TimelineExtractRequest(
                    project_id=request.project_id,
                    chapter_id=source.chapter_id,
                    text=source.text or "",
                    model=request.model,
                ),
                default_model=project.config.model,
            )
        return await self._timeline_service.check_consistency(
            request.project_id, include_flashbacks=request.include_flashbacks
        )

    def _auto_extract_on(self, request: ExtractionRequest, project: Project) -> bool:
        """TIMELINE 设置项三级判定（spec §2.6）: 请求显式值 → 项目配置 → 默认 false."""
        if request.auto_extract is not None:
            return request.auto_extract
        return bool(project.config.extra.get("timeline_auto_extract", False))

    def _indexing_enabled(self, request: ExtractionRequest, project: Project) -> bool:
        """类型是否支持自动索引（spec §5.3: outline/timeline 关闭时恒 False）。"""
        if request.type in (
            ExtractionType.CHARACTER,
            ExtractionType.SETTING,
            ExtractionType.FORESHADOWING,
        ):
            return True
        if request.type is ExtractionType.TIMELINE:
            return self._auto_extract_on(request, project)
        return False

    # ── RAG 索引编排（spec §5.6）────────────────────────────────

    def _collect_index_entities(
        self,
        request: ExtractionRequest,
        executed: list[tuple[_Source, Any]],
    ) -> list[IndexableEntity]:
        """将本次 executed 源产物投影为 IndexableEntity（§5.6 投影表）.

        character/setting/foreshadowing/timeline（开启）: created/updated
        实体按类型投影；章节模式额外索引该章 chapter_chunk 块。
        """
        entities: list[IndexableEntity] = []
        pid = str(request.project_id)
        for src, result in executed:
            if request.type is ExtractionType.CHARACTER and isinstance(
                result, CharacterExtractionResult
            ):
                entities.extend(
                    _project_character(e, pid) for e in [*result.created, *result.updated]
                )
            elif request.type is ExtractionType.SETTING and isinstance(
                result, WorldExtractionResult
            ):
                entities.extend(
                    _project_setting(e, pid) for e in [*result.created, *result.updated]
                )
            elif request.type is ExtractionType.FORESHADOWING and isinstance(
                result, ForeshadowingExtractionResult
            ):
                entities.extend(
                    _project_foreshadowing(e, pid) for e in [*result.created, *result.updated]
                )
            elif request.type is ExtractionType.TIMELINE and isinstance(
                result, TimelineExtractionResult
            ):
                entities.extend(
                    _project_timeline_event(e, pid) for e in [*result.created, *result.updated]
                )
            if src.chapter_id is not None:
                entities.extend(
                    _project_chapter_chunk(src.chapter_id, src.title or "", i, chunk, pid)
                    for i, chunk in enumerate(chunk_text(src.text or ""))
                )
        return entities

    async def reindex(
        self,
        project_id: uuid.UUID,
        entity_types: list[EntityType] | None = None,
    ) -> ReindexResult:
        """全量重建索引（spec §5.6）— 从各模块仓储分页拉取档案 → index_batch.

        Args:
            project_id: 所属项目 UUID.
            entity_types: 需重建的实体类型；None = 全部 5 种（缺省语义）.

        Returns:
            ReindexResult（indexed = 索引实体总数，幂等 upsert）.

        Raises:
            RAGUnavailableError: 向量存储未装配（500）.
        """
        if self._vector_store is None:
            raise RAGUnavailableError()
        types = list(entity_types) if entity_types else list(EntityType)
        warnings: list[str] = []
        total = 0
        pid = str(project_id)
        pid_int = _to_int_id(project_id)

        for entity_type in types:
            if entity_type is EntityType.CHARACTER:
                if self._character_repo is None:
                    warnings.append(f"实体类型 {entity_type.value} 未配置仓储，已跳过")
                    continue
                records = await self._paged_list(self._character_repo.list, pid_int)
                entities = [_project_character(c, pid) for c in records]
            elif entity_type is EntityType.SETTING:
                if self._world_repo is None:
                    warnings.append(f"实体类型 {entity_type.value} 未配置仓储，已跳过")
                    continue
                records = await self._paged_list(self._world_repo.list, pid_int)
                entities = [_project_setting(s, pid) for s in records]
            elif entity_type is EntityType.FORESHADOWING:
                if self._foreshadowing_repo is None:
                    warnings.append(f"实体类型 {entity_type.value} 未配置仓储，已跳过")
                    continue
                records = await self._paged_list(self._foreshadowing_repo.list, pid_int)
                entities = [_project_foreshadowing(f, pid) for f in records]
            elif entity_type is EntityType.TIMELINE_EVENT:
                if self._timeline_repo is None:
                    warnings.append(f"实体类型 {entity_type.value} 未配置仓储，已跳过")
                    continue
                events = await self._timeline_repo.list_all(pid_int)
                entities = [_project_timeline_event(e, pid) for e in events]
            elif entity_type is EntityType.CHAPTER_CHUNK:
                chapters = await self._paged_list(self._chapter_repo.list_chapters, pid_int)
                entities = [
                    _project_chapter_chunk(ch.id, ch.title, i, chunk, pid)
                    for ch in chapters
                    for i, chunk in enumerate(chunk_text(ch.content))
                ]
            else:
                continue
            if entities:
                await self._vector_store.index_batch(entities)
            total += len(entities)

        logger.info(
            "重建索引: project=%s types=%s indexed=%d",
            project_id,
            [t.value for t in types],
            total,
        )
        return ReindexResult(
            project_id=project_id,
            entity_types=types,
            indexed=total,
            warnings=warnings,
        )

    async def _paged_list(self, fn: Callable[..., Any], project_id: int) -> list[Any]:
        """分页循环拉取仓储列表（limit=100，spec §5.6 reindex 分页）。"""
        items: list[Any] = []
        offset = 0
        while True:
            page, total = await fn(project_id=project_id, offset=offset, limit=_REINDEX_PAGE_SIZE)
            items.extend(page)
            offset += len(page)
            if not page or offset >= total:
                break
        return items

    async def retrieve(
        self,
        query: str,
        *,
        project_id: uuid.UUID,
        entity_types: list[EntityType] | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[RetrievedEntity]:
        """语义检索（spec §5.6）— 参数透传 vector_store（project_id 转字符串）.

        Raises:
            RAGUnavailableError: 向量存储未装配（500）.
        """
        if self._vector_store is None:
            raise RAGUnavailableError()
        return await self._vector_store.retrieve(
            query,
            project_id=str(project_id),
            entity_types=entity_types,
            top_k=top_k,
            min_score=min_score,
        )

    # ── 增量状态查询 ────────────────────────────────────────────

    async def list_runs(
        self,
        project_id: uuid.UUID,
        type: ExtractionType | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ExtractionRun], int]:
        """分页查询项目内 run 记录（spec §3.3）— 透传 run_repo.list.

        Returns:
            (run 列表, 总数) 元组（按 run_at DESC，最新在前）.
        """
        return await self._run_repo.list(
            _to_int_id(project_id), type=type, offset=offset, limit=limit
        )
