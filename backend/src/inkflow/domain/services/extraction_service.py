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
② 类型注册表查 handler（6 槽全注册，STYLE → StyleService 委托，§6.1/F16 §8.2）
③ 增量判定（_resolve_sources: hash 比对 run 表，skip 时不调用 LLM）
④ 逐源分发执行（_dispatch: 各类型请求构造 + 结果归一化，§5.3）
⑤ 每源成功后立即 upsert ExtractionRun（断点续跑基础，§6.2）
⑥ index=true 时索引本次产物（§5.6）
⑦ 汇总返回 ExtractionResult

TIMELINE 双语义（§5.5）: 设置项判定在门面层——请求 auto_extract 显式值
→ 项目配置 project.config.extra["timeline_auto_extract"] → 默认 false；
开启 = TimelineExtractor（LLM 提取，按源 hash 增量），关闭 =
TimelineService.check_consistency（F12 确定性检查，每次执行，无 LLM）。

STYLE（F16 落地，spec §8.2 修订表）: 注册 StyleService.analyze 委托——每次
执行（固定 full 源，无增量 skip）、门面恒确定性（llm_analysis=False，F14
ExtractionRequest 无该字段）、结果归一 created=0/updated=0/model=None、
index=true 时恒 False + warning。

遵循 ADR-002/015: 领域层零框架 import，依赖全部通过构造函数注入
（Protocol 类型），测试注入 Mock。

依据: specs/f14-extraction/spec.md §5.1-§5.6/§6/§7/§8 +
specs/f16-style-analysis/spec.md §8.2（STYLE 槽位落地）。

RAG 编排拆分（#307）: `reindex` / `retrieve` / `_paged_list` 与投影纯函数迁至
`_extraction_rag.py`（`_ExtractionRAGMixin`，本类继承）；本类保留 extract 的
增量索引编排（`_collect_index_entities`，§5.1 步骤 ⑥）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from inkflow.core.config import config
from inkflow.domain.models.character import (
    CharacterExtractionResult,
    CharacterExtractRequest,
)
from inkflow.domain.models.extraction import (
    ExtractionRequest,
    ExtractionResult,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.domain.models.foreshadowing import (
    ForeshadowingExtractionResult,
    ForeshadowingExtractRequest,
)
from inkflow.domain.models.outline import OutlineGenerateRequest
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineExtractionResult,
    TimelineExtractRequest,
)
from inkflow.domain.models.world import WorldExtractionResult, WorldExtractRequest
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.extraction_errors import (
    ChapterNotFoundError,
    ChapterNotInProjectError,
    ExtractionValidationError,
    RAGUnavailableError,
    UnsupportedExtractionTypeError,
)
from inkflow.domain.ports.extraction_run_repository import ExtractionRunRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.vector_store import (
    IndexableEntity,
    VectorStoreProtocol,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._chunking import ChunkingConfig, chunk_text
from inkflow.domain.services._extraction_rag import (
    _ExtractionRAGMixin,
    _project_chapter_chunk,
    _project_character,
    _project_foreshadowing,
    _project_setting,
    _project_timeline_event,
    _to_int_id,
)
from inkflow.domain.services._foreshadowing_extractor import ForeshadowingExtractor
from inkflow.domain.services._timeline_extractor import TimelineExtractor
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.model_resolution import resolve_model
from inkflow.domain.services.outline_service import OutlineService
from inkflow.domain.services.style_service import StyleService
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.domain.services.world_service import WorldService

logger = logging.getLogger(__name__)

_MAX_CHAPTER_CHARS = 50000
"""单章提取上限（spec §5.2/§7: 超限 422，分块提取归 Phase 2+）。"""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _content_hash(text: str) -> str:
    """计算源内容 sha256 指纹（UTF-8 hexdigest，增量判定依据，§5.2）。"""
    return sha256(text.encode("utf-8")).hexdigest()


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


class ExtractionService(_ExtractionRAGMixin):
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
        style_service: F16 风格检测服务（STYLE 委托 analyze——每次执行 +
            门面恒确定性 llm_analysis=False，spec §8.2）.
        character_repo / world_repo / timeline_repo / foreshadowing_repo:
            reindex 全量重建用档案仓储（§5.6）.
        vector_store: RAG 向量存储（ADR-013）；None = 未装配，
            index=true / reindex / retrieve 时报 RAGUnavailableError（§5.6/§6.3）.
        fingerprint_provider: reindex 四步协议指纹提供器（#276）——返回当前
            configured 指纹 dict；None = 不写指纹（向后兼容）。reindex 全程
            持锁（_reindex_lock），先写 reindexing 后 commit-last 写 fresh。
        chunking: 切片配置（#277 M3，spec §5.6.1）——None = 默认
            fixed/500/0.0（向后兼容）。reindex 与增量索引共用该配置。
        llm_chunk_analyzer: LLM 档语义边界提供器（#278 M4，spec §5.6.7）——
            async Callable（复用 F5 LLMClient 语义）；None = 未配置（降级段落
            切片，向后兼容）。仅在 reindex 的 CHAPTER_CHUNK 分支生效。
        llm_default_model: 全局默认模型（#520 D1=C）——project.config.model 为
            None 时回退该值（deps.py 注入 config.llm_default_model）.
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
        style_service: StyleService,
        character_repo: CharacterRepositoryProtocol | None = None,
        world_repo: WorldRepositoryProtocol | None = None,
        timeline_repo: TimelineRepositoryProtocol | None = None,
        foreshadowing_repo: ForeshadowingRepositoryProtocol | None = None,
        vector_store: VectorStoreProtocol | None = None,
        fingerprint_provider: Callable[[], Awaitable[dict | None]] | None = None,
        chunking: ChunkingConfig | None = None,
        llm_chunk_analyzer: Callable[[str], Awaitable[list[int]]] | None = None,
        llm_default_model: str = config.llm_default_model,
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
        self._style_service = style_service
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._timeline_repo = timeline_repo
        self._foreshadowing_repo = foreshadowing_repo
        self._vector_store = vector_store
        self._fingerprint_provider = fingerprint_provider
        self._chunking = chunking if chunking is not None else ChunkingConfig()
        self._llm_chunk_analyzer = llm_chunk_analyzer
        self._llm_default_model = llm_default_model
        self._reindex_lock = asyncio.Lock()

        # 类型注册表（spec §6.1: 6 槽全注册；F16 §8.2: STYLE → StyleService.analyze）。
        # TIMELINE 槽位为双 handler 选择器（§5.5: 设置项开启 → TimelineExtractor，
        # 关闭 → TimelineService.check_consistency）。
        self._handlers: dict[ExtractionType, Callable[..., Any] | None] = {
            ExtractionType.CHARACTER: self._character_service.extract,
            ExtractionType.SETTING: self._world_service.extract,
            ExtractionType.OUTLINE: self._outline_service.generate,
            ExtractionType.TIMELINE: self._timeline_handler,
            ExtractionType.FORESHADOWING: self._foreshadowing_extractor.extract,
            ExtractionType.STYLE: self._style_service.analyze,
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

        # ② 类型注册表查 handler（§6.1: 6 槽全注册，未注册 → 422 防御）
        handler = self._handlers.get(request.type)
        if handler is None:
            raise UnsupportedExtractionTypeError()

        # ③ 类型相关输入约束（§6.4）+ 增量判定（§5.2: skip 时不调用 LLM）
        self._validate_input(request, project)
        sources = await self._resolve_sources(request, project)

        # ④⑤ 逐源执行 + 每源成功后立即 upsert run（断点续跑基础，§6.2）
        result, executed = await self._run_sources(request, sources, project)

        # ⑥ index=true → 索引本次产物（§5.6；outline/timeline 关闭时与 STYLE
        # 恒 False——忽略 + warning，§8.2 表 #7）
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
                unsupported = (
                    "outline/timeline/style"
                    if request.type is ExtractionType.STYLE
                    else "outline/timeline"
                )
                result.warnings.append(f"{unsupported} 类型不支持自动索引")

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
        if request.type is ExtractionType.STYLE:
            # F16 落地（§8.2 表 #3）: 同 character 语义——text 或 chapter_ids 必填其一
            # （互斥由 ExtractionRequest model_validator 保证）；门面无 llm_analysis 字段
            if not has_source:
                raise ExtractionValidationError("style 类型必须提供 text 或 chapter_ids")
            return
        if not has_source:
            raise ExtractionValidationError(
                "character/setting/foreshadowing 类型必须提供 text 或 chapter_ids"
            )

    async def _resolve_sources(self, request: ExtractionRequest, project: Project) -> list[_Source]:
        """计算待执行源列表（含 skip 判定，spec §5.2 伪代码）.

        outline 与 timeline（设置项关闭）固定单源 "full"、每次执行；
        STYLE（F16 落地）同语义——固定单源 "full"、每次执行（不读 run 表 hash，
        确定性只读计算廉价，无 skip 价值，§8.2 表 #4）；
        timeline（开启）与 character/setting/foreshadowing 按源 hash 增量:
        章节模式逐章读取校验（不存在/跨项目/超长 → 422），手动模式单源
        source_key="manual"。
        """
        if request.type is ExtractionType.OUTLINE:
            return [_Source(key="full", label="full", hash=_content_hash(""), skip=False)]
        if request.type is ExtractionType.TIMELINE and not self._auto_extract_on(request, project):
            return [_Source(key="full", label="full", hash=_content_hash(""), skip=False)]
        if request.type is ExtractionType.STYLE:
            # F16（§8.2 表 #4）: 每次执行——不读 run 表 hash、恒 skip=False
            # （确定性只读计算廉价，无增量价值）；章节读取在 StyleService 内（门面不读章节）
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
                default_model=resolve_model(
                    None, project.config.model, self._llm_default_model
                )
                or "",
            )
        elif request.type is ExtractionType.STYLE:
            # F16 落地（§8.2 表 #6）: 委托 StyleService.analyze——门面恒确定性
            # （llm_analysis=False，F14 ExtractionRequest 无该字段）；text/chapter_ids
            # 原样透传（章节读取在 StyleService 内，门面不读章节）
            result = await self._style_service.analyze(
                project_id=request.project_id,
                text=request.text,
                chapter_ids=request.chapter_ids,
                llm_analysis=False,
            )
            # 结果归一（§8.2 表 #6）: 无实体产物 → created=0/updated=0；无 LLM → model=None；
            # detail=StyleReport.model_dump；warnings 透传顶层（镜像 timeline 关闭先例）
            return _Normalized(
                created=0,
                updated=0,
                warnings=list(result.warnings),
                model=None,
                detail=result.model_dump(mode="json"),
                raw=result,
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
                default_model=resolve_model(
                    None, project.config.model, self._llm_default_model
                )
                or "",
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
        """类型是否支持自动索引（spec §5.3: outline/timeline 关闭时与 STYLE 恒 False）。

        STYLE 恒 False（§8.2 表 #7）: style 不在 RAG 范围（F14 §2.4 已声明）。
        """
        if request.type in (
            ExtractionType.CHARACTER,
            ExtractionType.SETTING,
            ExtractionType.FORESHADOWING,
        ):
            return True
        if request.type is ExtractionType.TIMELINE:
            return self._auto_extract_on(request, project)
        if request.type is ExtractionType.STYLE:
            return False
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
                cfg = self._chunking
                indexed_at = _utcnow().isoformat()
                chunks = chunk_text(
                    src.text or "",
                    mode=cfg.mode,
                    chunk_size=cfg.chunk_size,
                    overlap_ratio=cfg.overlap_ratio,
                )
                entities.extend(
                    _project_chapter_chunk(
                        src.chapter_id,
                        src.title or "",
                        i,
                        chunk,
                        pid,
                        overlap=cfg.overlap_ratio > 0,
                        indexed_at=indexed_at,
                    )
                    for i, chunk in enumerate(chunks)
                )
        return entities

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
