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

依据: specs/f14-extraction-service/spec.md §5.6（RAG 索引流程）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from inkflow.domain.models.character import Character
from inkflow.domain.models.extraction import ReindexResult
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.extraction_errors import RAGUnavailableError
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.vector_store import (
    EntityType,
    IndexableEntity,
    RetrievedEntity,
    VectorStoreProtocol,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._chunking import chunk_text

logger = logging.getLogger(__name__)

_REINDEX_PAGE_SIZE = 100
"""reindex 分页循环页大小（spec §5.6: list(limit=100)）。"""


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
                    entities = [
                        _project_chapter_chunk(ch.id, ch.title, i, chunk, pid)
                        for ch in chapters
                        for i, chunk in enumerate(chunk_text(ch.content))
                    ]
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
