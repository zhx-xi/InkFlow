"""LangChain Chroma 向量存储 — ``VectorStoreProtocol`` 的 ADR-013 首次落地实现。

设计要点（spec §5.6 / ADR-013）:
- 每 ``EntityType`` 一个 collection（collection 名 = ``f"inkflow_{entity_type.value}"``，
  对齐 ``config.vector_store_collections``）
- 项目隔离 = ``metadata.project_id`` 过滤（所有查询 always 带
  ``where={"project_id": project_id}``，Protocol 强制）
- embeddings 由构造注入（生产 ``HuggingFaceBgeEmbeddings(BAAI/bge-small-zh-v1.5)``，
  测试 ``FakeEmbeddings``）——BGE 模型首次使用需联网下载 ~100MB，懒加载
- chromadb 同步 API 全部用 ``asyncio.to_thread`` 包装（不阻塞事件循环）
- 距离度量 cosine；``relevance_score = 1 - distance``
- 懒初始化: 首次调用时创建 ``PersistentClient`` + ``get_or_create_collection``
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import chromadb
from langchain_core.embeddings import Embeddings

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
    - embeddings 由构造注入（生产 HuggingFaceBgeEmbeddings(BAAI/bge-small-zh-v1.5)，
      测试 FakeEmbeddings）——BGE 模型首次使用需联网下载 ~100MB，懒加载
    - chromadb 同步 API 用 asyncio.to_thread 包装（不阻塞事件循环）
    - 距离度量 cosine；relevance_score = 1 - distance
    """

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
