"""LangChain Chroma 向量存储 — ``VectorStoreProtocol`` 的 ADR-013 首次落地实现。

设计要点（spec §5.6 / ADR-013）:
- 每 ``EntityType`` 一个 collection（collection 名 = ``f"inkflow_{entity_type.value}"``，
  对齐 ``config.vector_store_collections``）
- 项目隔离 = ``metadata.project_id`` 过滤（所有查询 always 带
  ``where={"project_id": project_id}``，Protocol 强制）
- embeddings 由构造注入（生产 ``OpenAIEmbeddings``——API embedding，模型来自
  ProviderConfig 注册表 type="embedding" 条目，spec f19 §5.4；测试
  ``FakeEmbeddings``）——懒加载
- chromadb 同步 API 全部用 ``asyncio.to_thread`` 包装（不阻塞事件循环）
- 距离度量 cosine；``relevance_score = 1 - distance``
- 懒初始化: 首次调用时创建 ``PersistentClient`` + ``get_or_create_collection``
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import chromadb
from langchain_core.embeddings import Embeddings
from loguru import logger

from inkflow.domain.ports.vector_store import (
    EntityType,
    IndexableEntity,
    RetrievedEntity,
)

# chromadb 元数据值类型（含 bool，bool 是 int 子类，运行时兼容领域契约）
_Metadata = dict[str, str | int | float | bool]


class LangChainVectorStore:
    """VectorStoreProtocol 实现 — LangChain Chroma + 本地 Embedding（ADR-013）。

    - 每 EntityType 一个 collection（collection 名 = f"inkflow_{entity_type.value}"）
    - 项目隔离 = metadata.project_id 过滤（查询 always 带 project_id）
    - embeddings 由构造注入（生产 OpenAIEmbeddings——API embedding，模型来自
      ProviderConfig 注册表 type="embedding" 条目；测试 FakeEmbeddings）——懒加载
    - chromadb 同步 API 用 asyncio.to_thread 包装（不阻塞事件循环）
    - 距离度量 cosine；relevance_score = 1 - distance
    """

    _META_COLLECTION = "inkflow_meta"
    """指纹专用 collection 名（与向量数据同库同生命周期，不参与语义检索）。"""

    _FP_ID_PREFIX = "fp:"
    """指纹 doc id 前缀（id = fp:{project_id}，per-project 隔离）。"""

    def __init__(self, persist_dir: Path, embeddings: Embeddings) -> None:
        """初始化向量存储。

        Args:
            persist_dir: chromadb 持久化目录（PersistentClient path）。
            embeddings: LangChain Embeddings 实例（embed_documents/embed_query）。
        """
        self._persist_dir = persist_dir
        self._embeddings = embeddings
        self._client: chromadb.ClientAPI | None = None
        self._collections: dict[EntityType, chromadb.Collection] = {}
        self._meta_collection: chromadb.Collection | None = None
        self.embedding_dimension: int | None = None
        """当前 embeddings 实测维度缓存（probe_embedding_dimension 懒填充）。"""

    # ── VectorStoreProtocol 实现 ──

    async def index(self, entity: IndexableEntity) -> None:
        """索引一个实体到向量库（同 id 二次索引覆盖，upsert 幂等）。"""
        await asyncio.to_thread(self._index_sync, entity)

    async def index_batch(self, entities: list[IndexableEntity]) -> None:
        """批量索引实体（按类型分组后逐 collection upsert）。"""
        await asyncio.to_thread(self._index_batch_sync, entities)

    async def retrieve(
        self,
        query: str,
        *,
        project_id: str,
        entity_types: list[EntityType] | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[RetrievedEntity]:
        """语义检索与查询最相关的实体。

        Args:
            query: 查询文本（如当前章节的内容片段）。
            project_id: 限定在指定项目内检索（where 过滤）。
            entity_types: 限定实体类型，None 表示检索全部 5 种类型。
            top_k: 返回结果数量上限（合并后截断）。
            min_score: 最低相关度阈值（0-1），过滤低相关结果。

        Returns:
            按 relevance_score 降序排列的检索结果列表（无结果时为空列表）。
        """
        return await asyncio.to_thread(
            self._retrieve_sync,
            query,
            project_id=project_id,
            entity_types=entity_types,
            top_k=top_k,
            min_score=min_score,
        )

    async def delete(self, entity_id: str, entity_type: EntityType) -> None:
        """从向量库中删除指定实体（id 不存在时为 no-op）。"""
        await asyncio.to_thread(self._delete_sync, entity_id, entity_type)

    async def delete_project(self, project_id: str) -> int:
        """删除指定项目的所有向量数据（遍历全部 collection），返回删除总数。"""
        return await asyncio.to_thread(self._delete_project_sync, project_id)

    async def read_fingerprint(self, project_id: str) -> dict | None:
        """读取项目索引指纹（inkflow_meta collection，同库同生命周期）。"""
        return await asyncio.to_thread(self._read_fingerprint_sync, project_id)

    async def write_fingerprint(self, project_id: str, fingerprint: dict, status: str) -> None:
        """写入/覆盖项目索引指纹（status 合并进指纹 dict，commit-last 提交点）。"""
        await asyncio.to_thread(self._write_fingerprint_sync, project_id, fingerprint, status)

    async def probe_collection_dimension(self, project_id: str) -> int:
        """探测项目现存向量的维度（空库/无向量 → 0）。"""
        return await asyncio.to_thread(self._probe_collection_dimension_sync, project_id)

    async def probe_embedding_dimension(self) -> int:
        """探测当前 embeddings 实测维度（结果缓存到 self.embedding_dimension）。"""
        return await asyncio.to_thread(self._probe_embedding_dimension_sync)

    async def delete_stale(
        self,
        project_id: str,
        source_ids: set[str],
        entity_types: list[EntityType] | None = None,
    ) -> int:
        """差集删除: collection 现存 id - 源侧 id = 待删 id（幽灵/孤儿向量）。"""
        return await asyncio.to_thread(
            self._delete_stale_sync, project_id, source_ids, entity_types
        )

    async def recreate_collections(self, entity_types: list[EntityType] | None = None) -> Path:
        """备份持久化目录并删除重建集合（维度不匹配时调用），返回备份路径。"""
        return await asyncio.to_thread(self._recreate_collections_sync, entity_types)

    # ── 私有: chromadb 同步操作（由 asyncio.to_thread 包装调用）──

    def _get_collection(self, entity_type: EntityType) -> chromadb.Collection:
        """懒初始化: 首次调用创建 PersistentClient 并 get_or_create 目标 collection。"""
        if entity_type not in self._collections:
            if self._client is None:
                self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._collections[entity_type] = self._client.get_or_create_collection(
                name=f"inkflow_{entity_type.value}",
                # hnsw:sync_threshold=3：chromadb 1.x HNSW 默认 WAL-only（<1000 条不落盘），
                # 小批量写入后 query 会走 rust from_disk 加载失败（"Nothing found on disk"，
                # CI 慢磁盘偶发，issue #4212/#7463）。
                # 阈值 3 = 写入即落盘（validator 要求 >2），本项目写入频率低，
                # 性能影响可忽略；且崩溃恢复更安全。
                metadata={"hnsw:space": "cosine", "hnsw:sync_threshold": 3},
            )
        return self._collections[entity_type]

    @staticmethod
    def _to_chroma_metadata(entity: IndexableEntity) -> _Metadata:
        """附加 project_id 到实体 metadata（检索过滤键，spec §5.6）。"""
        return {**entity.metadata, "project_id": entity.project_id}

    def _index_sync(self, entity: IndexableEntity) -> None:
        """同步索引单个实体（upsert，同 id 覆盖）。"""
        collection = self._get_collection(entity.entity_type)
        embedding = self._embeddings.embed_documents([entity.content])[0]
        collection.upsert(
            ids=[entity.id],
            documents=[entity.content],
            metadatas=[self._to_chroma_metadata(entity)],
            # chroma stub 对 embeddings 类型过严（实际运行时接受 list[list[float]]）
            embeddings=cast(Any, [embedding]),
        )

    def _index_batch_sync(self, entities: list[IndexableEntity]) -> None:
        """同步批量索引: 按类型分组，每 collection 一次 upsert。"""
        by_type: dict[EntityType, list[IndexableEntity]] = {}
        for entity in entities:
            by_type.setdefault(entity.entity_type, []).append(entity)
        for entity_type, group in by_type.items():
            collection = self._get_collection(entity_type)
            embeddings = self._embeddings.embed_documents([e.content for e in group])
            collection.upsert(
                ids=[e.id for e in group],
                documents=[e.content for e in group],
                metadatas=[self._to_chroma_metadata(e) for e in group],
                # chroma stub 对 embeddings 类型过严（实际运行时接受 list[list[float]]）
                embeddings=cast(Any, embeddings),
            )

    def _retrieve_sync(
        self,
        query: str,
        *,
        project_id: str,
        entity_types: list[EntityType] | None,
        top_k: int,
        min_score: float,
    ) -> list[RetrievedEntity]:
        """同步检索: 每类型查对应 collection（where project_id），合并排序截断。"""
        types = list(entity_types) if entity_types else list(EntityType)
        query_embedding = self._embeddings.embed_query(query)
        merged: list[RetrievedEntity] = []
        for entity_type in types:
            collection = self._get_collection(entity_type)
            result = collection.query(
                # chroma stub 对 query_embeddings 类型过严（实际运行时接受 list[list[float]]）
                query_embeddings=cast(Any, [query_embedding]),
                n_results=top_k,
                where={"project_id": project_id},
                include=["documents", "metadatas", "distances"],
            )
            ids = result["ids"]
            if not ids or not ids[0]:
                continue
            documents = result["documents"] or []
            metadatas = result["metadatas"] or []
            distances = result["distances"] or []
            for entity_id, document, metadata, distance in zip(
                ids[0], documents[0], metadatas[0], distances[0], strict=True
            ):
                score = 1.0 - distance
                if score < min_score:
                    continue
                merged.append(
                    RetrievedEntity(
                        entity_id=entity_id,
                        entity_type=entity_type,
                        content=document or "",
                        relevance_score=score,
                        metadata=cast(dict[str, str | int | float], metadata or {}),
                    )
                )
        merged.sort(key=lambda item: item.relevance_score, reverse=True)
        return merged[:top_k]

    def _delete_sync(self, entity_id: str, entity_type: EntityType) -> None:
        """同步删除单个实体（id 不存在时 chroma no-op）。"""
        collection = self._get_collection(entity_type)
        collection.delete(ids=[entity_id])

    def _delete_project_sync(self, project_id: str) -> int:
        """同步删除项目全部向量: 遍历 5 个 collection，按 project_id 计数删除。"""
        total = 0
        for entity_type in EntityType:
            collection = self._get_collection(entity_type)
            fetched = collection.get(where={"project_id": project_id})
            ids = fetched["ids"]
            if ids:
                collection.delete(ids=ids)
                total += len(ids)
        return total

    def _get_meta_collection(self) -> chromadb.Collection:
        """懒初始化: 获取/创建 inkflow_meta collection（指纹存储，无检索语义）。"""
        if self._meta_collection is None:
            if self._client is None:
                self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._meta_collection = self._client.get_or_create_collection(
                name=self._META_COLLECTION
            )
        return self._meta_collection

    def _read_fingerprint_sync(self, project_id: str) -> dict | None:
        """同步读取项目指纹: get by id → json.loads(document)；无 doc → None。"""
        collection = self._get_meta_collection()
        result = collection.get(ids=[f"{self._FP_ID_PREFIX}{project_id}"])
        documents = result.get("documents") or []
        if not result["ids"] or not documents or not documents[0]:
            return None
        raw = documents[0]
        if not isinstance(raw, str):
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None

    def _write_fingerprint_sync(self, project_id: str, fingerprint: dict, status: str) -> None:
        """同步写入/覆盖项目指纹（显式 1 维占位向量，meta 不参与语义检索）。"""
        doc = dict(fingerprint)
        doc["status"] = status
        collection = self._get_meta_collection()
        collection.upsert(
            ids=[f"{self._FP_ID_PREFIX}{project_id}"],
            documents=[json.dumps(doc, ensure_ascii=False)],
            # chroma stub 对 embeddings 类型过严（实际运行时接受 list[list[float]]）
            embeddings=cast(Any, [[0.0]]),
        )

    def _probe_collection_dimension_sync(self, project_id: str) -> int:
        """同步探测现存向量维度: 逐 collection 取首条向量长度，全部为空 → 0。

        ⚠️ 不按 project_id 过滤（2026-08-12 真实冒烟修正）: collection 维度
        是库级不变量（chroma 建库时固定）——本项目无向量但 collection 被
        其他项目数据锁定维度时，per-project 探测会误报 0 → 跳过重建 →
        upsert 撞旧维度崩（InvalidArgumentError 384 vs 768 实证）。
        """
        for entity_type in EntityType:
            collection = self._get_collection(entity_type)
            result = collection.get(
                include=["embeddings"],
                limit=1,
            )
            ids = result["ids"]
            if not ids:
                continue
            embeddings = result.get("embeddings")
            if embeddings is not None and len(embeddings) > 0:
                # get 返回形状为 (N, dim)，embeddings[0] 即首条向量
                return len(embeddings[0])
        return 0

    def _probe_embedding_dimension_sync(self) -> int:
        """同步探测 embeddings 实测维度（一次性缓存到实例属性，避免重复 embed）。"""
        if self.embedding_dimension is None:
            self.embedding_dimension = len(self._embeddings.embed_query(""))
        return self.embedding_dimension

    def _delete_stale_sync(
        self,
        project_id: str,
        source_ids: set[str],
        entity_types: list[EntityType] | None,
    ) -> int:
        """同步差集删除: 每 collection 现存 id 减源侧 id 后删除，返回删除总数。"""
        types = list(entity_types) if entity_types else list(EntityType)
        total = 0
        for entity_type in types:
            collection = self._get_collection(entity_type)
            ids = collection.get(where={"project_id": project_id})["ids"]
            orphans = [entity_id for entity_id in ids if entity_id not in source_ids]
            if orphans:
                collection.delete(ids=orphans)
                total += len(orphans)
        return total

    def _recreate_collections_sync(self, entity_types: list[EntityType] | None) -> Path:
        """同步重建: 备份持久化目录 → 删除重建实体 collection → 返回备份路径。"""
        types = list(entity_types) if entity_types else list(EntityType)
        backup_path = self._persist_dir
        if self._persist_dir.is_dir():
            # 备份目录名带唯一后缀：同秒两次重建（双向维度切换）会撞名
            # （2026-08-12 真实冒烟 FileExistsError 实证）
            base = f"{self._persist_dir}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            backup_path = Path(base)
            suffix = 1
            while backup_path.exists():
                backup_path = Path(f"{base}-{suffix}")
                suffix += 1
            shutil.copytree(str(self._persist_dir), str(backup_path))
            logger.info("向量集合重建前备份完成: {} -> {}", self._persist_dir, backup_path)
        if self._client is not None:
            existing = {collection.name for collection in self._client.list_collections()}
            for entity_type in types:
                # 必须先清缓存再删除，避免缓存引用已删除的旧 collection
                self._collections.pop(entity_type, None)
                name = f"inkflow_{entity_type.value}"
                if name in existing:
                    self._client.delete_collection(name=name)
        for entity_type in types:
            self._get_collection(entity_type)
        return backup_path
