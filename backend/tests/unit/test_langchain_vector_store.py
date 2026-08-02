"""LangChainVectorStore RAG 基础设施单元测试 — FakeEmbeddings + 真实 chroma（tmp 目录）.

覆盖 spec §9「RAG（真实 chroma + FakeEmbeddings，tmp 目录）」全部场景:
index upsert 幂等（同 id 二次 index 覆盖）/ index_batch 全量入库 /
retrieve 按 project_id where 过滤（跨项目不可见）/ entity_types 过滤
（多 collection 查询合并）/ cosine 分数 = 1 - distance（FakeEmbeddings
固定向量可断言排序）/ min_score 过滤 / top_k 截断 / delete 单实体 /
delete_project 返回删除数 / 空库 retrieve → 空列表 / FakeEmbeddings
维度一致性（size=384，与 BGE 输出维度同）/ metadata（含 project_id）透传。

依据: specs/f14-extraction-service/spec.md §5.6/§9; ADR-013。
"""

from __future__ import annotations

from pathlib import Path

import chromadb
import pytest
from langchain_core.embeddings import Embeddings

from inkflow.domain.ports.vector_store import (
    EntityType,
    IndexableEntity,
    RetrievedEntity,
)
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore


class FakeEmbeddings(Embeddings):
    """确定性伪 Embedding — 384 维字符袋向量（对齐 BGE 输出维度）。

    同文本 query/doc 余弦相似度 = 1.0；共享字符越多相似度越高、
    无共享字符 = 0，保证测试可断言分数与排序（spec §9: cosine 分数 = 1 - distance）。
    """

    dimension = 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量生成确定性向量。"""
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """生成查询向量（与 embed_documents 同规则，保证可排序差异）。"""
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        """字符袋向量: 每个字符按 ord(ch) % dimension 累加计数。"""
        vec = [0.0] * self.dimension
        for ch in text:
            vec[ord(ch) % self.dimension] += 1.0
        return vec


@pytest.fixture
def store(tmp_path: Path) -> LangChainVectorStore:
    """临时 chroma 持久化目录的向量存储实例（persist_dir = tmp_path / "chroma"）。"""
    return LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())


def make_entity(
    entity_id: str,
    entity_type: EntityType,
    project_id: str,
    content: str,
    **metadata: str | int | float,
) -> IndexableEntity:
    """构造测试实体。"""
    return IndexableEntity(
        id=entity_id,
        entity_type=entity_type,
        project_id=project_id,
        content=content,
        metadata=metadata,
    )


# ── FakeEmbeddings 维度一致性 ──


def test_fake_embeddings_dimension_and_determinism() -> None:
    """FakeEmbeddings 维度固定 384（与 BGE 输出维度同）且结果确定。"""
    embeddings = FakeEmbeddings()
    query = embeddings.embed_query("苹果")
    documents = embeddings.embed_documents(["苹果", "苹果", "香蕉"])
    assert len(query) == 384
    assert all(len(doc) == 384 for doc in documents)
    assert documents[0] == documents[1]  # 同文本确定性
    assert embeddings.embed_query("苹果") == query  # query/doc 同规则


# ── index / index_batch ──


async def test_index_upsert_same_id_overwrites(store: LangChainVectorStore) -> None:
    """index: 同 id 二次 index 覆盖（Chroma upsert 幂等，不产生重复）。"""
    await store.index(make_entity("c1", EntityType.CHARACTER, "p1", "苹果"))
    await store.index(make_entity("c1", EntityType.CHARACTER, "p1", "香蕉", name="新"))
    results = await store.retrieve("苹果", project_id="p1")
    assert len(results) == 1
    assert results[0].entity_id == "c1"
    assert results[0].content == "香蕉"  # 内容被覆盖
    assert results[0].metadata["name"] == "新"  # 元数据被覆盖


async def test_index_batch_stores_all(store: LangChainVectorStore) -> None:
    """index_batch: 全部入库，跨类型可检索。"""
    await store.index_batch(
        [
            make_entity("c1", EntityType.CHARACTER, "p1", "苹果"),
            make_entity("c2", EntityType.CHARACTER, "p1", "香蕉"),
            make_entity("s1", EntityType.SETTING, "p1", "苹果"),
        ]
    )
    # min_score=0.01 排除无共享字符的零分结果（score 0.0 ≥ 默认 min_score 0.0 会保留）
    results = await store.retrieve("苹果", project_id="p1", min_score=0.01)
    assert {r.entity_id for r in results} == {"c1", "s1"}
    results2 = await store.retrieve("香蕉", project_id="p1", min_score=0.01)
    assert [r.entity_id for r in results2] == ["c2"]


# ── retrieve: 项目隔离 / 类型过滤 / 分数 / 过滤 / 截断 ──


async def test_retrieve_filters_by_project_id(store: LangChainVectorStore) -> None:
    """retrieve: 按 project_id where 过滤，跨项目不可见。"""
    await store.index_batch(
        [
            make_entity("c1", EntityType.CHARACTER, "p1", "苹果"),
            make_entity("c2", EntityType.CHARACTER, "p2", "苹果"),
        ]
    )
    results_p1 = await store.retrieve("苹果", project_id="p1")
    assert [r.entity_id for r in results_p1] == ["c1"]
    results_p2 = await store.retrieve("苹果", project_id="p2")
    assert [r.entity_id for r in results_p2] == ["c2"]


async def test_retrieve_entity_types_filter(store: LangChainVectorStore) -> None:
    """retrieve: entity_types 过滤（多 collection 查询合并）。"""
    await store.index_batch(
        [
            make_entity("c1", EntityType.CHARACTER, "p1", "苹果"),
            make_entity("s1", EntityType.SETTING, "p1", "苹果"),
            make_entity("f1", EntityType.FORESHADOWING, "p1", "苹果"),
        ]
    )
    # None → 全部类型合并
    all_results = await store.retrieve("苹果", project_id="p1")
    assert {r.entity_id for r in all_results} == {"c1", "s1", "f1"}
    # 单类型 → 仅该类型
    char_results = await store.retrieve(
        "苹果", project_id="p1", entity_types=[EntityType.CHARACTER]
    )
    assert [r.entity_id for r in char_results] == ["c1"]
    # 多类型 → 合并
    multi_results = await store.retrieve(
        "苹果",
        project_id="p1",
        entity_types=[EntityType.CHARACTER, EntityType.SETTING],
    )
    assert {r.entity_id for r in multi_results} == {"c1", "s1"}


async def test_retrieve_cosine_score(store: LangChainVectorStore) -> None:
    """retrieve: cosine 分数 = 1 - distance，可断言排序与分数。"""
    await store.index_batch(
        [
            make_entity("c1", EntityType.CHARACTER, "p1", "苹果"),  # 与查询相同 → 1.0
            make_entity("c2", EntityType.CHARACTER, "p1", "苹果是红色的水果"),  # 共享字符 → (0,1)
            make_entity("c3", EntityType.CHARACTER, "p1", "龙卷风摧毁停车场"),  # 无共享字符 → 0
        ]
    )
    results = await store.retrieve("苹果", project_id="p1", top_k=3)
    by_id = {r.entity_id: r.relevance_score for r in results}
    assert by_id["c1"] == pytest.approx(1.0)
    assert 0.0 < by_id["c2"] < 1.0
    assert by_id["c3"] == pytest.approx(0.0)
    # 合并后按 relevance_score 降序
    scores = [r.relevance_score for r in results]
    assert scores == sorted(scores, reverse=True)


async def test_retrieve_min_score_filter(store: LangChainVectorStore) -> None:
    """retrieve: score < min_score 的结果被过滤。"""
    await store.index_batch(
        [
            make_entity("c1", EntityType.CHARACTER, "p1", "苹果"),
            make_entity("c2", EntityType.CHARACTER, "p1", "香蕉"),  # 与查询无共享字符 → 0
        ]
    )
    results = await store.retrieve("苹果", project_id="p1", min_score=0.5)
    assert [r.entity_id for r in results] == ["c1"]


async def test_retrieve_top_k_truncation(store: LangChainVectorStore) -> None:
    """retrieve: top_k 截断返回数量。"""
    await store.index_batch(
        [make_entity(f"c{i}", EntityType.CHARACTER, "p1", f"苹果{i}") for i in range(5)]
    )
    results = await store.retrieve("苹果", project_id="p1", top_k=2)
    assert len(results) == 2
    scores = [r.relevance_score for r in results]
    assert scores == sorted(scores, reverse=True)


async def test_retrieve_empty_store_returns_empty_list(store: LangChainVectorStore) -> None:
    """空库 retrieve → 空列表（正常路径，非错误）。"""
    assert await store.retrieve("苹果", project_id="p1") == []
    assert await store.retrieve("苹果", project_id="p1", entity_types=[EntityType.CHARACTER]) == []


# ── delete / delete_project ──


async def test_delete_single_entity(store: LangChainVectorStore) -> None:
    """delete: 删除单实体，不影响同类型其他实体与其他类型。"""
    await store.index_batch(
        [
            make_entity("c1", EntityType.CHARACTER, "p1", "苹果"),
            make_entity("c2", EntityType.CHARACTER, "p1", "苹果"),
            make_entity("s1", EntityType.SETTING, "p1", "苹果"),
        ]
    )
    await store.delete("c1", EntityType.CHARACTER)
    results = await store.retrieve("苹果", project_id="p1")
    assert {r.entity_id for r in results} == {"c2", "s1"}
    # 删除不存在的 id 为 no-op（不抛异常）
    await store.delete("no-such-id", EntityType.CHARACTER)


async def test_delete_project_returns_count(store: LangChainVectorStore) -> None:
    """delete_project: 遍历全部 collection 删除并返回删除总数。"""
    await store.index_batch(
        [
            make_entity("c1", EntityType.CHARACTER, "p1", "苹果"),
            make_entity("c2", EntityType.CHARACTER, "p1", "香蕉"),
            make_entity("s1", EntityType.SETTING, "p1", "苹果"),
            make_entity("c3", EntityType.CHARACTER, "p2", "苹果"),  # 另一项目保留
        ]
    )
    deleted = await store.delete_project("p1")
    assert deleted == 3
    assert await store.retrieve("苹果", project_id="p1") == []
    results_p2 = await store.retrieve("苹果", project_id="p2")
    assert [r.entity_id for r in results_p2] == ["c3"]
    # 无数据项目 → 0
    assert await store.delete_project("no-such-project") == 0


# ── 存储结构 / 持久化 / metadata ──


async def test_collection_per_entity_type(tmp_path: Path) -> None:
    """每 EntityType 一个 collection，collection 名 = f"inkflow_{entity_type.value}"。"""
    vector_store = LangChainVectorStore(
        persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings()
    )
    await vector_store.index(make_entity("c1", EntityType.CHARACTER, "p1", "苹果"))
    await vector_store.index(make_entity("s1", EntityType.SETTING, "p1", "香蕉"))
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    names = {collection.name for collection in client.list_collections()}
    assert names == {"inkflow_character", "inkflow_setting"}


async def test_persist_across_instances(tmp_path: Path) -> None:
    """数据持久化: 新实例打开同一目录仍可检索。"""
    store1 = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())
    await store1.index(make_entity("c1", EntityType.CHARACTER, "p1", "苹果"))
    store2 = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())
    results = await store2.retrieve("苹果", project_id="p1")
    assert [r.entity_id for r in results] == ["c1"]


async def test_metadata_preserved_with_project_id(store: LangChainVectorStore) -> None:
    """metadata 透传并自动附带 project_id（spec §5.6 timeline_event 投影键）。"""
    await store.index(
        make_entity(
            "e1",
            EntityType.TIMELINE_EVENT,
            "p1",
            "事件：登基\n时间：三年 春",
            title="登基",
            timeline_flag="MAIN",
            chapter_id="ch1",
        )
    )
    results = await store.retrieve("登基", project_id="p1")
    assert len(results) == 1
    assert isinstance(results[0], RetrievedEntity)
    metadata = results[0].metadata
    assert metadata["project_id"] == "p1"  # 自动附带（检索过滤键）
    assert metadata["chapter_id"] == "ch1"  # 用户 metadata 透传
    assert metadata["title"] == "登基"
    assert metadata["timeline_flag"] == "MAIN"
