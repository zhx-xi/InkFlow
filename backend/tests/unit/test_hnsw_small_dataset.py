"""RED 契约（#468）：hnsw sync_threshold=3 对小数据集（<3 条/集合）无效——retrieve 必须命中。

缺陷背景（0.10.0-rc6 实证 2026-08-18）：`_get_collection` 设 `hnsw:sync_threshold=3`，
但场景 A 数据量 <3 条/集合（character=2、setting=1 等）→ 未达 sync 阈值 →
link_lists.bin 空（0 字节）→ retrieve 报 `Nothing found on disk` 稳定 500。

本契约：真实 chromadb 轨（FakeEmbeddings + tmp 目录）——单集合 1 条/2 条 index 后
立即 retrieve 必须命中（无 Nothing found on disk）。修复后全部 PASS。

⚠️ RED 期形态：当前 sync_threshold=3，单集合 1-2 条 index 后 retrieve 抛
chromadb InternalError → 断言 FAIL（干净 RED）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from inkflow.domain.ports.vector_store import EntityType, IndexableEntity
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore


class _FakeEmbeddings:
    """维度 384 的确定性 FakeEmbeddings（镜像 test_langchain_vector_store.py）。"""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for ch in text:
            vec[ord(ch) % self.dimension] += 1.0
        return vec


def _make_entity(entity_id: str, entity_type: EntityType, project_id: str, content: str):
    return IndexableEntity(
        id=entity_id,
        entity_type=entity_type,
        project_id=project_id,
        content=content,
        metadata={"project_id": project_id},
    )


@pytest.mark.asyncio
async def test_small_dataset_single_entity_retrieve(tmp_path: Path) -> None:
    """单集合 1 条 → index → retrieve 必须命中（#468 sync_threshold=3 边界）。"""
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=_FakeEmbeddings())
    entity = _make_entity("e1", EntityType.CHARACTER, "p1", "主角李青莲")
    await store.index(entity)

    results = await store.retrieve(
        "李青莲", project_id="p1", entity_types=[EntityType.CHARACTER], top_k=5
    )
    assert len(results) >= 1, f"单条 index 后 retrieve 空（sync_threshold=3 未落盘）: {results}"


@pytest.mark.asyncio
async def test_small_dataset_two_entities_retrieve(tmp_path: Path) -> None:
    """单集合 2 条 → index_batch → retrieve 必须命中（<3 条/集合边界）。"""
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=_FakeEmbeddings())
    entities = [
        _make_entity("e1", EntityType.CHARACTER, "p1", "主角李青莲"),
        _make_entity("e2", EntityType.CHARACTER, "p1", "配角苏挽月"),
    ]
    await store.index_batch(entities)

    results = await store.retrieve(
        "李青莲", project_id="p1", entity_types=[EntityType.CHARACTER], top_k=5
    )
    assert len(results) >= 1, f"2 条 index 后 retrieve 空（sync_threshold=3 未落盘）: {results}"


@pytest.mark.asyncio
async def test_multi_collection_small_retrieve(tmp_path: Path) -> None:
    """多集合各 <3 条 → 合并 retrieve 必须命中（rc6 场景 A 形态复现）。"""
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=_FakeEmbeddings())
    entities = [
        _make_entity("c1", EntityType.CHARACTER, "p1", "主角李青莲"),
        _make_entity("s1", EntityType.SETTING, "p1", "蜀山剑派"),
        _make_entity("f1", EntityType.FORESHADOWING, "p1", "青铜剑匣"),
    ]
    await store.index_batch(entities)

    for q in ("李青莲", "蜀山", "剑匣"):
        results = await store.retrieve(
            q,
            project_id="p1",
            entity_types=[EntityType.CHARACTER, EntityType.SETTING, EntityType.FORESHADOWING],
            top_k=5,
        )
        assert len(results) >= 1, f"query={q} retrieve 空（小数据集未落盘）: {results}"


@pytest.mark.asyncio
async def test_recreate_then_small_dataset_retrieve(tmp_path: Path) -> None:
    """recreate_collections（reindex 路径）后小数据集 retrieve 必须命中（rc6 A36 复现）。"""
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=_FakeEmbeddings())
    entities = [
        _make_entity("c1", EntityType.CHARACTER, "p1", "主角李青莲"),
        _make_entity("s1", EntityType.SETTING, "p1", "蜀山剑派"),
    ]
    await store.index_batch(entities)

    # rc6 reindex 路径：recreate → 重新 index → retrieve
    await store.recreate_collections([EntityType.CHARACTER, EntityType.SETTING])
    await store.index_batch(entities)

    # 跨进程模拟：重建 store 实例（新 PersistentClient 读磁盘段）
    store2 = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=_FakeEmbeddings())
    results = await store2.retrieve(
        "李青莲",
        project_id="p1",
        entity_types=[EntityType.CHARACTER, EntityType.SETTING],
        top_k=5,
    )
    assert len(results) >= 1, f"recreate 后新实例 retrieve 空（段未落盘）: {results}"
