"""F22 全文搜索编排服务 —— 词法 FTS5 + semantic RAG 增强（spec §5.1-5.3/5.8）.

SearchService 是第 16 变体「索引检索型」的编排核心：经 6 类数据源 Repository
只读聚合（分页循环，limit=50 默认）→ 每实体一条 SearchDocument（jieba 分词后
文本）→ SearchRepositoryProtocol（FTS5 索引）查询；semantic 模式复用既有
VectorStoreProtocol（F14），不新建向量基础设施。

索引维护策略（Q2 拍板）：默认懒重建（脏检测 + 全量重建），设置项
ai_maintenance=true 时增量同步（失败回退全量重建，E13），手动 rebuild 跳过
脏检测；重建并发用实例级 asyncio.Lock + 双检锁（E7）。

零跨模块 MODIFY：只依赖 domain/ports/ 与 _search_tokenizer 纯函数，
domain 层零框架 import 门禁天然满足（ADR-002/015）。

依据: specs/f22-search-service/spec.md §5/§6/§8.2。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from inkflow.domain.models.search import (
    SearchEntityType,
    SearchHit,
    SearchMode,
    SearchQuery,
    SearchResponse,
)
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.search_repository import SearchDocument, SearchRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity, VectorStoreProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._search_tokenizer import (
    build_match,
    prepare_index_text,
    tokenize,
)

_TABLES = [
    "chapters",
    "characters",
    "world_settings",
    "outlines",
    "timeline_events",
    "foreshadowings",
]
"""6 张业务表名常量（父侧裁定 2026-08-09 签名：is_stale 表名列表）。"""

_PAGE_SIZE = 50
"""分页循环页大小（spec §5.1：list(limit=50) 循环拉取全量）。"""

# SearchEntityType → F14 EntityType 映射（spec §5.8：outline 无向量类型恒空）。
_SEMANTIC_TYPES: dict[SearchEntityType, EntityType] = {
    SearchEntityType.CHAPTER: EntityType.CHAPTER_CHUNK,
    SearchEntityType.CHARACTER: EntityType.CHARACTER,
    SearchEntityType.WORLD: EntityType.SETTING,
    SearchEntityType.TIMELINE: EntityType.TIMELINE_EVENT,
    SearchEntityType.FORESHADOWING: EntityType.FORESHADOWING,
}

# F14 EntityType → SearchEntityType 反向映射（semantic 命中归类）。
_SEARCH_TYPES: dict[EntityType, SearchEntityType] = {
    EntityType.CHAPTER_CHUNK: SearchEntityType.CHAPTER,
    EntityType.CHARACTER: SearchEntityType.CHARACTER,
    EntityType.SETTING: SearchEntityType.WORLD,
    EntityType.TIMELINE_EVENT: SearchEntityType.TIMELINE,
    EntityType.FORESHADOWING: SearchEntityType.FORESHADOWING,
}


def _parse_uuid(value: str) -> uuid.UUID:
    """容错解析实体 id：UUID 字符串直解；短 id/chunk id 按 int 回退（陷阱 18）。"""
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.UUID(int=int(value))


class SearchService:
    """全文检索编排：词法 FTS5 查询 + semantic RAG 增强 + 索引维护.

    全部依赖经构造注入（deps.py 装配）；数据源 Repository 为只读消费，
    search_repo 是自有补充端口（SearchRepositoryProtocol，F15 audit_repo
    先例），vector_store 可选（F14 VectorStoreProtocol，仅 semantic 模式）。
    """

    def __init__(
        self,
        *,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        outline_repo: OutlineRepositoryProtocol,
        timeline_repo: TimelineRepositoryProtocol,
        foreshadowing_repo: ForeshadowingRepositoryProtocol,
        search_repo: SearchRepositoryProtocol,
        vector_store: VectorStoreProtocol | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._chapter_repo = chapter_repo
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._outline_repo = outline_repo
        self._timeline_repo = timeline_repo
        self._foreshadowing_repo = foreshadowing_repo
        self._search_repo = search_repo
        self._vector_store = vector_store
        self._rebuild_lock = asyncio.Lock()

    async def search(self, query: SearchQuery) -> SearchResponse:
        """执行检索（spec §5.1 管线）.

        ① 逐 project_id 校验项目（None → ProjectNotFoundError 404）
        ② semantic 模式：复用 F14 向量检索（§5.8）；否则词法分支
        ③ 词法：懒索引就绪 → jieba 分词 → MATCH 构造 → FTS5 查询
        """
        for pid in query.project_ids:
            project = await self._project_repo.get(pid.int)
            if project is None:
                raise ProjectNotFoundError(f"Project not found: {pid}")

        if query.mode == SearchMode.SEMANTIC:
            return await self._search_semantic(query)

        await self._ensure_index([pid.int for pid in query.project_ids])
        tokens = tokenize(query.q)
        if not tokens:
            # 分词后无有效词 → 200 空结果（spec §3.3，不 422）。
            return self._empty_response(query)
        match = build_match(tokens)
        types = [t.value for t in query.types] if query.types is not None else None
        total, hits = await self._search_repo.query(
            match,
            [pid.int for pid in query.project_ids],
            types,
            query.limit,
            query.offset,
        )
        return SearchResponse(
            total=total,
            hits=hits,
            query=query.q,
            types=query.types,
            mode=query.mode,
            project_ids=query.project_ids,
        )

    async def rebuild(self, project_ids: list[int] | None = None) -> dict:
        """手动全量重建（跳过脏检测；API/CLI 调用，spec §3.1/M13）.

        project_ids=None → 分页枚举全部项目，合并文档一次重建；
        project_ids=[...] → 逐项目校验存在（None → ProjectNotFoundError）。
        返回 {"rebuilt_at": str, "project_ids": [str] | None}（None = 全部）。
        """
        requested = project_ids
        if requested is not None:
            for pid in requested:
                project = await self._project_repo.get(pid)
                if project is None:
                    raise ProjectNotFoundError(f"Project not found: {pid}")
            target_ids = requested
        else:
            projects = await self._list_all_projects()
            target_ids = [project.id.int for project in projects]

        await self._search_repo.ensure_index()
        documents: list[SearchDocument] = []
        for pid in target_ids:
            documents.extend(await self._collect_project_documents(pid))
        await self._search_repo.rebuild(documents)
        return {
            "rebuilt_at": datetime.now(UTC).isoformat(),
            "project_ids": (
                [str(uuid.UUID(int=pid)) for pid in target_ids] if requested is not None else None
            ),
        }

    async def _ensure_index(self, project_ids: list[int] | None = None) -> None:
        """词法索引懒就绪（spec §5.2/E4/E7）.

        幂等建表 → 脏检测（新鲜返回）→ 双检锁重建；ai_maintenance=true
        时走增量同步（异常 → loguru + 回退全量重建，E13）。
        """
        await self._search_repo.ensure_index()
        if not await self._is_stale():
            return
        async with self._rebuild_lock:
            if not await self._is_stale():
                return
            if await self._search_repo.get_setting("ai_maintenance") == "true":
                try:
                    await self._incremental_sync(project_ids)
                except Exception:
                    logger.exception("搜索索引增量同步失败，回退全量重建")
                    await self._rebuild(project_ids)
            else:
                await self._rebuild(project_ids)

    async def _is_stale(self) -> bool:
        """任一业务表 max(updated_at) 晚于 last_rebuilt_at 则判脏."""
        return await self._search_repo.is_stale(_TABLES)

    async def _rebuild(self, project_ids: list[int] | None = None) -> None:
        """全量收集文档并一次重建（分页循环 limit=50 默认；#211 真删后无软删过滤）."""
        if project_ids is None:
            projects = await self._list_all_projects()
            project_ids = [project.id.int for project in projects]
        documents: list[SearchDocument] = []
        for project_id in project_ids:
            documents.extend(await self._collect_project_documents(project_id))
        await self._search_repo.rebuild(documents)

    async def _incremental_sync(self, project_ids: list[int] | None = None) -> None:
        """AI 自动维护增量同步（简化实现：全量收集 → 删旧插新）."""
        if project_ids is None:
            projects = await self._list_all_projects()
            project_ids = [project.id.int for project in projects]
        documents: list[SearchDocument] = []
        for project_id in project_ids:
            documents.extend(await self._collect_project_documents(project_id))
        await self._search_repo.incremental_sync(documents, [])

    async def _search_semantic(self, query: SearchQuery) -> SearchResponse:
        """semantic 模式（spec §5.8）：向量检索 → SearchHit 映射.

        对每个 project_id 循环调用 retrieve（单 project_id 签名）；
        retrieve 抛异常 → loguru + 200 空结果，不降级 keyword（E12）。
        """
        if self._vector_store is None:
            return self._empty_response(query)
        vector_types = self._map_vector_types(query.types)
        if vector_types is not None and not vector_types:
            # 全部类型无向量映射（如 outline）→ semantic 恒空。
            return self._empty_response(query)
        try:
            hits: list[SearchHit] = []
            for pid in query.project_ids:
                retrieved = await self._vector_store.retrieve(
                    query.q,
                    project_id=str(pid),
                    entity_types=vector_types,
                    top_k=query.limit,
                )
                for entity in retrieved:
                    hits.append(self._map_retrieved(entity, pid))
        except Exception:
            logger.exception("语义检索失败（embedding 不可用），返回空结果")
            hits = []
        return SearchResponse(
            total=len(hits),
            hits=hits,
            query=query.q,
            types=query.types,
            mode=query.mode,
            project_ids=query.project_ids,
        )

    def _map_vector_types(self, types: list[SearchEntityType] | None) -> list[EntityType] | None:
        """SearchEntityType 列表 → F14 EntityType 列表（outline 剔除；None → None）."""
        if types is None:
            return None
        return [_SEMANTIC_TYPES[t] for t in types if t in _SEMANTIC_TYPES]

    def _map_retrieved(self, entity: RetrievedEntity, fallback_pid: uuid.UUID) -> SearchHit:
        """RetrievedEntity → SearchHit 映射（spec §5.8 映射表）.

        CHAPTER_CHUNK 的块 id 形如 "{chapter_id}:{idx}"（非 UUID），entity_id
        优先取 metadata['chapter_id']，缺省回退块 id 前半段；其余类型取
        RetrievedEntity.entity_id。title 依类型取 metadata 键，缺省回退
        content 前 40 字符；project_id 缺省回退本轮查询 pid。
        """
        metadata = entity.metadata
        if entity.entity_type == EntityType.CHAPTER_CHUNK:
            raw_id = str(metadata.get("chapter_id") or entity.entity_id.split(":")[0])
            raw_title = metadata.get("chapter_title") or metadata.get("name") or entity.content[:40]
        elif entity.entity_type == EntityType.TIMELINE_EVENT:
            raw_id = entity.entity_id
            raw_title = metadata.get("title") or metadata.get("name") or entity.content[:40]
        else:
            raw_id = entity.entity_id
            raw_title = metadata.get("name") or entity.content[:40]
        project_id = (
            _parse_uuid(str(metadata["project_id"]))
            if metadata.get("project_id") is not None
            else fallback_pid
        )
        return SearchHit(
            entity_type=_SEARCH_TYPES[entity.entity_type],
            entity_id=_parse_uuid(raw_id),
            project_id=project_id,
            title=str(raw_title),
            snippet=entity.content[:200],
            score=entity.relevance_score,
        )

    async def _collect_project_documents(self, project_id: int) -> list[SearchDocument]:
        """收集单项目 6 类索引文档（spec §6.1：title/body 拼装；#211 真删后无软删过滤）."""
        documents: list[SearchDocument] = []
        documents.extend(await self._collect_chapters(project_id))
        documents.extend(await self._collect_characters(project_id))
        documents.extend(await self._collect_world_settings(project_id))
        documents.extend(await self._collect_outlines(project_id))
        documents.extend(await self._collect_timeline_events(project_id))
        documents.extend(await self._collect_foreshadowings(project_id))
        return documents

    async def _collect_chapters(self, project_id: int) -> list[SearchDocument]:
        """章节文档：title = chapter.title；body = content 全文（spec §6.1）."""
        documents: list[SearchDocument] = []
        async for chapter in self._iter_pages(self._chapter_repo.list_chapters, project_id):
            documents.append(
                SearchDocument(
                    entity_type=SearchEntityType.CHAPTER.value,
                    entity_id=chapter.id.int,
                    project_id=project_id,
                    title=chapter.title,
                    body=prepare_index_text(chapter.title, chapter.content),
                )
            )
        return documents

    async def _collect_characters(self, project_id: int) -> list[SearchDocument]:
        """角色文档：title = name；body = personality + background + goals."""
        documents: list[SearchDocument] = []
        async for character in self._iter_pages(self._character_repo.list, project_id):
            body_text = " ".join(
                part
                for part in (character.personality, character.background, character.goals)
                if part
            )
            documents.append(
                SearchDocument(
                    entity_type=SearchEntityType.CHARACTER.value,
                    entity_id=character.id.int,
                    project_id=project_id,
                    title=character.name,
                    body=prepare_index_text(character.name, body_text),
                )
            )
        return documents

    async def _collect_world_settings(self, project_id: int) -> list[SearchDocument]:
        """世界观文档：title = name；body = content."""
        documents: list[SearchDocument] = []
        async for setting in self._iter_pages(self._world_repo.list, project_id):
            documents.append(
                SearchDocument(
                    entity_type=SearchEntityType.WORLD.value,
                    entity_id=setting.id.int,
                    project_id=project_id,
                    title=setting.name,
                    body=prepare_index_text(setting.name, setting.content),
                )
            )
        return documents

    async def _collect_outlines(self, project_id: int) -> list[SearchDocument]:
        """大纲文档：title = name；body = description + 各情节点 "name: description"."""
        documents: list[SearchDocument] = []
        async for outline in self._iter_pages(self._outline_repo.list, project_id):
            points = await self._outline_repo.list_points(outline.id.int)
            point_text = " ".join(
                f"{point.name}: {point.description}" if point.description else point.name
                for point in points
            )
            body_text = " ".join(part for part in (outline.description, point_text) if part)
            documents.append(
                SearchDocument(
                    entity_type=SearchEntityType.OUTLINE.value,
                    entity_id=outline.id.int,
                    project_id=project_id,
                    title=outline.name,
                    body=prepare_index_text(outline.name, body_text),
                )
            )
        return documents

    async def _collect_timeline_events(self, project_id: int) -> list[SearchDocument]:
        """时间线文档：title = event.title；body = description + time_display（非空时）."""
        documents: list[SearchDocument] = []
        for event in await self._timeline_repo.list_all(project_id):
            body_text = " ".join(part for part in (event.description, event.time_display) if part)
            documents.append(
                SearchDocument(
                    entity_type=SearchEntityType.TIMELINE.value,
                    entity_id=event.id.int,
                    project_id=project_id,
                    title=event.title,
                    body=prepare_index_text(event.title, body_text),
                )
            )
        return documents

    async def _collect_foreshadowings(self, project_id: int) -> list[SearchDocument]:
        """伏笔文档：title = title；body = description + location（非空时）."""
        documents: list[SearchDocument] = []
        async for item in self._iter_pages(self._foreshadowing_repo.list, project_id):
            body_text = " ".join(part for part in (item.description, item.location) if part)
            documents.append(
                SearchDocument(
                    entity_type=SearchEntityType.FORESHADOWING.value,
                    entity_id=item.id.int,
                    project_id=project_id,
                    title=item.title,
                    body=prepare_index_text(item.title, body_text),
                )
            )
        return documents

    async def _list_all_projects(self) -> list[Any]:
        """分页枚举全部项目（limit=50 默认，spec §5.1/M13）."""
        projects: list[Any] = []
        offset = 0
        while True:
            batch, total = await self._project_repo.list_all(offset=offset, limit=_PAGE_SIZE)
            projects.extend(batch)
            offset += len(batch)
            if offset >= total or not batch:
                break
        return projects

    async def _iter_pages(
        self,
        fetcher: Callable[..., Awaitable[tuple[list[Any], int]]],
        project_id: int,
    ) -> AsyncIterator[Any]:
        """分页循环拉取单一数据源（limit=50 默认；#211 真删后无软删过滤）."""
        offset = 0
        while True:
            batch, total = await fetcher(project_id, offset=offset, limit=_PAGE_SIZE)
            for entity in batch:
                yield entity
            offset += len(batch)
            if offset >= total or not batch:
                break

    def _empty_response(self, query: SearchQuery) -> SearchResponse:
        """构造 200 空结果（query/types/mode/project_ids 回显原值）."""
        return SearchResponse(
            total=0,
            hits=[],
            query=query.q,
            types=query.types,
            mode=query.mode,
            project_ids=query.project_ids,
        )
