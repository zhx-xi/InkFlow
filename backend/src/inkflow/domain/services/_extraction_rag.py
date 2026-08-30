"""F14 统一提取服务的 RAG 索引编排（spec §5.6）— 从门面拆分（#307）.

门面 `extraction_service.py` 的「RAG 索引」横切能力（spec §5.1 要点 6: 横切能力
解耦）拆分为本模块，含两部分:

1. 投影纯函数（§5.6 投影表）: 各档案实体 → IndexableEntity（确定性、可单测）。
2. `_ExtractionRAGMixin`: `reindex` 全量重建（含 #276 四步协议）/ `retrieve` 语义
   检索 / `_paged_list` 分页拉取。增量索引编排 `_collect_index_entities` 仍留在门面
   （它消费 `extract → _run_sources` 的 `executed` 产物，属提取主流程，见门面 §5.1
   步骤 ⑥）。

由 `ExtractionService` 继承（#307 拆分）；共享属性（`_vector_store` / `_character_repo`
/ `_world_repo` / `_timeline_repo` / `_foreshadowing_repo` / `_chapter_repo` /
`_fingerprint_provider` / `_reindex_lock`）由门面 `__init__` 装配，此处以类级注解
声明（供 mypy 解析 `self.*` 访问，运行时由门面赋值）。

`_to_int_id` 一并迁入本模块（门面 `extract` / `_resolve_sources` / `list_runs` 与
本模块 `reindex` 均使用）——迁入以切断「门面 ↔ 本模块」的 import 环（本模块对门面
零运行时依赖），门面 re-export。

依据: specs/f14-extraction/spec.md §5.6（RAG 索引流程）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from inkflow.domain.models.character import Character
from inkflow.domain.models.extraction import ReindexResult
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.extraction_errors import (
    RAGUnavailableError,
    VectorStoreError,
)
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.vector_store import (
    EntityType,
    IndexableEntity,
    RetrievedEntity,
    VectorStoreProtocol,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._chunking import (
    Chunk,
    ChunkingConfig,
    ChunkingMode,
    chunk_text,
)

logger = logging.getLogger(__name__)

_REINDEX_PAGE_SIZE = 100
"""reindex 分页循环页大小（spec §5.6: list(limit=100)）。"""


def _content_hash(text: str) -> str:
    """计算源内容 sha256 指纹（UTF-8 hexdigest，LLM 增量跳过判定依据）。"""
    return sha256(text.encode("utf-8")).hexdigest()


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）。"""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


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
        content=(f"名称：{setting.name}\n分类：{setting.category}\n内容：{setting.content}"),
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
    chunk: Chunk,
    project_id: str,
    *,
    overlap: bool = False,
    chapter_x: int | None = None,
    chapter_y: int | None = None,
    volume_title: str | None = None,
    indexed_at: str | None = None,
    source_hash: str | None = None,
) -> IndexableEntity:
    """章节文本块 → IndexableEntity（§5.6 投影表；块 id 三态，spec §5.6.3/§5.6.4）。

    块 id: overlap=False → {chapter_id}:{idx}（现状）；overlap=True →
    {chapter_id}:{idx}:{start_offset}（重叠块 idx 不唯一，偏移消歧）。
    metadata 补强: chunk_start 恒有；chapter_x/chapter_y/volume_title/indexed_at
    仅非 None 时写入（None 省略键，QA §P2-1 fallback）。
    """
    if overlap:
        entity_id = f"{chapter_id}:{chunk_index}:{chunk.start_offset}"
    else:
        entity_id = f"{chapter_id}:{chunk_index}"
    metadata: dict[str, str | int | float] = {
        "chapter_id": str(chapter_id),
        "chapter_title": chapter_title,
        "chunk_index": chunk_index,
        "project_id": project_id,
        "chunk_start": chunk.start_offset,
    }
    if chapter_x is not None:
        metadata["chapter_x"] = chapter_x
    if chapter_y is not None:
        metadata["chapter_y"] = chapter_y
    if volume_title is not None:
        metadata["volume_title"] = volume_title
    if indexed_at is not None:
        metadata["indexed_at"] = indexed_at
    if source_hash is not None:
        metadata["source_hash"] = source_hash
    return IndexableEntity(
        id=entity_id,
        entity_type=EntityType.CHAPTER_CHUNK,
        project_id=project_id,
        content=chunk.text,
        metadata=metadata,
    )


class _ExtractionRAGMixin:
    """RAG 索引编排（spec §5.6）— `reindex` 全量重建 / `retrieve` 语义检索.

    由 `ExtractionService` 继承（#307 拆分）；共享属性由门面 `__init__` 装配，此处
    类级注解声明（不赋值——运行时由门面 `__init__` 装配）。
    """

    _vector_store: VectorStoreProtocol | None
    _character_repo: CharacterRepositoryProtocol | None
    _world_repo: WorldRepositoryProtocol | None
    _timeline_repo: TimelineRepositoryProtocol | None
    _foreshadowing_repo: ForeshadowingRepositoryProtocol | None
    _chapter_repo: ChapterRepositoryProtocol
    _fingerprint_provider: Callable[[], Awaitable[dict | None]] | None
    _reindex_lock: asyncio.Lock
    _chunking: ChunkingConfig
    _llm_chunk_analyzer: Callable[[str], Awaitable[list[int]]] | None

    async def reindex(
        self,
        project_id: uuid.UUID,
        entity_types: list[EntityType] | None = None,
    ) -> ReindexResult:
        """全量重建索引（spec §5.6 + #276 四步协议）— 顺序不可调换:

        ① 写 status="reindexing" 指纹（fingerprint_provider 非 None 时）
        ② 维度探测（probe_embedding_dimension vs probe_collection_dimension；
           空库 0 → 直灌，异维 → recreate_collections + collections_recreated）
        ③ upsert 全量（既有逐类型分页拉取 → index_batch）→ 差集删除
           （delete_stale(pid, 源侧 id 全集, entity_types)）
        ④ commit-last 写 status="fresh" 指纹（唯一提交点——任何失败不提交 fresh）

        并发 reindex 全程持 _reindex_lock 串行（契约 20）。

        Args:
            project_id: 所属项目 UUID.
            entity_types: 需重建的实体类型；None = 全部 5 种（缺省语义）.

        Returns:
            ReindexResult（indexed = 索引实体总数，幂等 upsert；
            collections_recreated = 维度不匹配重建标志）.

        Raises:
            RAGUnavailableError: 向量存储未装配（500）.
        """
        async with self._reindex_lock:
            if self._vector_store is None:
                raise RAGUnavailableError()
            # None = 全部 5 种（缺省语义）；[] = 显式空（#276 协议骨架，
            # 只走探测/差集/指纹不索引——父侧契约修正 2026-08-12）
            types = list(entity_types) if entity_types is not None else list(EntityType)
            pid = str(project_id)
            pid_int = _to_int_id(project_id)
            # ① 写 reindexing 指纹（非 None 时；commit-last 前失败不提交 fresh）
            fp = await self._fingerprint_provider() if self._fingerprint_provider else None
            if fp is not None:
                await self._vector_store.write_fingerprint(pid, fp, "reindexing")
            # ② 维度探测（空库 0 → 直灌；异维 → 重建 collection）
            recreated = False
            target_dim = await self._vector_store.probe_embedding_dimension()
            existing_dim = await self._vector_store.probe_collection_dimension(pid)
            if existing_dim and target_dim and existing_dim != target_dim:
                await self._vector_store.recreate_collections(types)
                recreated = True
            warnings: list[str] = []
            total = 0
            source_ids: set[str] = set()

            # ③ upsert 全量（既有逐类型分页拉取）→ 循环外差集删除
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
                    # Q4 拍板（spec §5.6.4）: chapter_x 为全书级，按 order_index
                    # 全局排序（1-based）；repo 保证排序时此步幂等，mock 无序时兜底。
                    chapters = sorted(chapters, key=lambda ch: getattr(ch, "order_index", 0.0))
                    cfg = self._chunking
                    chunk_overlap = cfg.overlap_ratio > 0
                    indexed_at = datetime.now(UTC).isoformat()
                    chapter_y = len(chapters)
                    # 卷标题补强（spec §5.6.4）: 仅当存在归属卷的章节才拉全卷映射
                    # （无卷章节 volume_title 省略；旧 mock 仓储无 list_volumes 契约兼容）
                    volume_titles: dict[Any, str] = {}
                    if any(getattr(ch, "volume_id", None) is not None for ch in chapters):
                        volumes = await self._chapter_repo.list_volumes(pid_int)
                        volume_titles = {v.id: v.title for v in volumes}
                    entities = []
                    for chapter_x, ch in enumerate(chapters, start=1):
                        volume_title = (
                            volume_titles.get(ch.volume_id)
                            if getattr(ch, "volume_id", None) is not None
                            else None
                        )
                        # #278 M4: LLM 增量跳过（QA §P2-2）——source_hash 匹配
                        # → 复用上次切片结果（不重灌、不被差集删除）
                        if cfg.mode is ChunkingMode.LLM:
                            h = _content_hash(ch.content)
                            existing = await self._vector_store.list_entities(
                                pid,
                                EntityType.CHAPTER_CHUNK,
                                where={"chapter_id": str(ch.id)},
                            )
                            if existing and all(
                                isinstance(md, dict) and md.get("source_hash") == h
                                for _, md in existing
                            ):
                                source_ids.update(eid for eid, _ in existing)
                                continue
                            chunks = await self._chunk_with_llm(ch.content, cfg, h, pid, ch)
                        else:
                            chunks = chunk_text(
                                ch.content,
                                mode=cfg.mode,
                                chunk_size=cfg.chunk_size,
                                overlap_ratio=cfg.overlap_ratio,
                            )
                        entities.extend(
                            _project_chapter_chunk(
                                ch.id,
                                ch.title,
                                i,
                                chunk,
                                pid,
                                overlap=chunk_overlap,
                                chapter_x=chapter_x,
                                chapter_y=chapter_y,
                                volume_title=volume_title,
                                indexed_at=indexed_at,
                                source_hash=(
                                    _content_hash(ch.content)
                                    if cfg.mode is ChunkingMode.LLM
                                    else None
                                ),
                            )
                            for i, chunk in enumerate(chunks)
                        )
                else:
                    continue
                if entities:
                    try:
                        await self._vector_store.index_batch(entities)
                    except Exception:
                        # ⚠️ 维度兜底重试（2026-08-12 真实冒烟实证）：
                        # 「空但维度锁定」的 collection（曾写入后数据被差集
                        # 删除清空）probe=0 探测不到维度 → upsert 撞旧维度崩
                        # （chroma InvalidArgumentError 384 vs 768）。
                        # 未重建过 → 重建后重试；重建过仍失败 → 原样上抛。
                        if not recreated:
                            await self._vector_store.recreate_collections(types)
                            recreated = True
                            await self._vector_store.index_batch(entities)
                        else:
                            raise
                    source_ids.update(e.id for e in entities)
                total += len(entities)

            await self._vector_store.delete_stale(pid, source_ids, entity_types=types)
            # ④ commit-last 写 fresh 指纹（唯一提交点）
            if fp is not None:
                await self._vector_store.write_fingerprint(pid, fp, "fresh")

            # 日志含 embedding model id——E2E/M4 防假成功观测点
            # （#276：断言日志中 model id = 当前配置模型，证明单例已刷新）
            embedding_model_id = (fp or {}).get("embedding", {}).get("model_id", "?")
            logger.info(
                "重建索引: project=%s types=%s indexed=%d embedding_model=%s recreated=%s",
                project_id,
                [t.value for t in types],
                total,
                embedding_model_id,
                recreated,
            )
            return ReindexResult(
                project_id=project_id,
                entity_types=types,
                indexed=total,
                warnings=warnings,
                collections_recreated=recreated,
            )

    async def _chunk_with_llm(
        self,
        text: str,
        cfg: ChunkingConfig,
        source_hash: str,
        pid: str,
        ch: Any,
    ) -> list[Chunk]:
        """LLM 档切片: await analyzer 得边界 → 闭包 analyzer → chunk_text；失败降级段落。

        Args:
            text: 待切分章节内容.
            cfg: 切片配置（LLM 档；降级段落路径透传 chunk_size/overlap_ratio）.
            source_hash: 当前内容 sha256（后续 _project_chapter_chunk 写 metadata 用）.
            pid: 项目 ID 字符串（保留签名完整性，兼容父侧契约）.
            ch: 章节对象（日志取 id 用）.
        """
        if self._llm_chunk_analyzer is None:
            logger.warning("LLM 切片器未配置，降级段落切片: chapter=%s", getattr(ch, "id", "?"))
            return chunk_text(
                text,
                mode=ChunkingMode.PARAGRAPH,
                chunk_size=cfg.chunk_size,
                overlap_ratio=cfg.overlap_ratio,
            )
        try:
            boundaries = await self._llm_chunk_analyzer(text)
        except Exception:
            logger.warning(
                "LLM 切片失败，降级段落切片: chapter=%s",
                getattr(ch, "id", "?"),
                exc_info=True,
            )
            return chunk_text(
                text,
                mode=ChunkingMode.PARAGRAPH,
                chunk_size=cfg.chunk_size,
                overlap_ratio=cfg.overlap_ratio,
            )
        return chunk_text(
            text,
            mode=ChunkingMode.LLM,
            chunk_size=cfg.chunk_size,
            overlap_ratio=cfg.overlap_ratio,
            analyzer=lambda t: boundaries,
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
        try:
            return await self._vector_store.retrieve(
                query,
                project_id=str(project_id),
                entity_types=entity_types,
                top_k=top_k,
                min_score=min_score,
            )
        except VectorStoreError:
            # #823: chromadb hnsw 段读取失败（"Nothing found on disk"，#468 同族）→
            # 一次自愈重试：重建索引后重试一次；仍失败则清晰上抛 VectorStoreError
            # （禁止吞空「内部错误（无详情）」）。
            logger.warning(
                "向量检索失败，尝试重建索引后重试: project=%s", project_id, exc_info=True
            )
            await self.reindex(project_id, entity_types)
            return await self._vector_store.retrieve(
                query,
                project_id=str(project_id),
                entity_types=entity_types,
                top_k=top_k,
                min_score=min_score,
            )
