"""#1404 契约：批量索引 embedding 单请求 input 上限（64 条，zhipu embedding-3）。

契约源: specs/f14-extraction/spec.md §5.6（批量索引分片）+ §7 边界情况。

缺陷背景: zhipu embedding-3 单请求 input 上限 64 条，超限 → 400 code 1214
（「input数组最大不得超过64条」）。批量路径把整组实体一次性提交（无分片）→
实体总数 > 64 的项目「重建索引」100% 失败（重建中断、指纹停在 reindexing、
不提交 fresh）；单条路径（`_index_sync` 逐条 embed）不受影响。

修复（方案 A）: ``_index_batch_sync`` 内按 provider 上限分片循环 ``embed_documents``
后合并，再一次性 upsert（语义不变、幂等保持）。

RED 形态: 整批一次提交 → 调用次数断言（ceil(n/64)）FAIL。

形态（镜像 ``test_empty_string_guard_929.py`` 的 mock 环境）: 本文件全部用
mock chroma + mock embeddings，且 patch 一律走 ``with patch(...)`` 上下文
（零磁盘 I/O、退出即恢复）——分片只影响 embedding 调用侧；计数/行为断言若走
真实 chroma，会与同目录兄弟用例的 #873/#1011 hnsw 段竞态互相干扰（实测同跑必红）。

拆分由来: 原拟追加进 ``test_langchain_vector_store.py``，但该文件 742 行 + 本段
会超 ``ci_cd/check_file_length.py`` 的 900 行护栏（CI lint-backend 硬门禁），
故独立成文件并镜像复制所需 fixtures/helpers（自包含，零跨模块耦合）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.embeddings import Embeddings
from loguru import logger

from inkflow.domain.ports.vector_store import EntityType, IndexableEntity
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore

EMBED_REQUEST_LIMIT_1404 = 64  # zhipu embedding-3 单请求 input 条数上限


class FakeEmbeddings(Embeddings):
    """确定性伪 Embedding — 384 维字符袋向量（对齐 BGE 输出维度）。

    镜像 ``test_langchain_vector_store.py`` 的同名 class（独立文件自包含）。
    """

    dimension = 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量生成确定性向量。"""
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """生成查询向量（与 embed_documents 同规则）。"""
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        """字符袋向量: 每个字符按 ord(ch) % dimension 累加计数。"""
        vec = [0.0] * self.dimension
        for ch in text:
            vec[ord(ch) % self.dimension] += 1.0
        return vec


class _ChunkLimitedEmbeddings(FakeEmbeddings):
    """模拟 zhipu embedding-3 上游硬约束：单请求 input 超过 64 条即拒绝（400 code 1214）。

    用真实异常形态（硬拒绝而非降级）证明链路不再把整组实体一次提交 ——
    若实现回退成整批提交，本用例必 FAIL（比计数 spy 更贴「400 不再发生」语义）。
    """

    max_inputs = EMBED_REQUEST_LIMIT_1404

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if len(texts) > self.max_inputs:
            raise RuntimeError(
                f"模拟 provider 400 code 1214：input 数组 {len(texts)} 条超过上限 {self.max_inputs}"
            )
        return super().embed_documents(texts)


def make_entity(
    entity_id: str,
    entity_type: EntityType,
    project_id: str,
    content: str,
    **metadata: str | int | float,
) -> IndexableEntity:
    """构造测试实体（镜像 ``test_langchain_vector_store.py`` 的同名 helper）。"""
    return IndexableEntity(
        id=entity_id,
        entity_type=entity_type,
        project_id=project_id,
        content=content,
        metadata=metadata,
    )


def _default_mock_embeddings() -> MagicMock:
    """MagicMock embeddings：embed_documents 每次返回与入参等长的 8 维向量。"""
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1] * 8
    embeddings.embed_documents.side_effect = lambda texts: [[0.1] * 8 for _ in texts]
    return embeddings


def _build_mock_chroma() -> tuple[MagicMock, dict[str, MagicMock]]:
    """构造 mock chromadb client（预注册 meta + 5 类 collection）。"""
    client = MagicMock()
    collections: dict[str, MagicMock] = {}

    def get_or_create(name: str, **kwargs: object) -> MagicMock:
        if name not in collections:
            collection = MagicMock()
            collection.name = name
            collection.get.return_value = {"ids": [], "documents": None, "embeddings": None}
            collections[name] = collection
        return collections[name]

    client.get_or_create_collection.side_effect = get_or_create
    client.list_collections.return_value = []
    client.get_or_create_collection("inkflow_meta")
    for entity_type in EntityType:
        client.get_or_create_collection(f"inkflow_{entity_type.value}")
    return client, collections


@contextmanager
def mock_store_ctx(
    tmp_path: Path, embeddings: Any = None
) -> Iterator[tuple[LangChainVectorStore, dict[str, MagicMock], Any]]:
    """with 上下文：mock chroma 的 store（退出即恢复 patch，零磁盘）。"""
    emb = embeddings if embeddings is not None else _default_mock_embeddings()
    client, collections = _build_mock_chroma()
    with patch(
        "inkflow.infrastructure.rag.langchain_vector_store.chromadb.PersistentClient",
        return_value=client,
    ):
        store = LangChainVectorStore(persist_dir=tmp_path, embeddings=emb)
        store._client = client
        yield store, collections, emb


def _entities_1404(
    count: int, entity_type: EntityType = EntityType.CHARACTER
) -> list[IndexableEntity]:
    """构造 count 条实体（content 唯一，便于按 id/文本对齐核对）。"""
    prefix = "角色" if entity_type is EntityType.CHARACTER else "设定"
    return [
        make_entity(
            f"{entity_type.value[0]}{i}",
            entity_type,
            "p1",
            f"{prefix}{i}的档案正文-{i}",
        )
        for i in range(count)
    ]


def _embed_batches_1404(embeddings: Any) -> list[list[str]]:
    """按调用顺序取出 embed_documents 的每次入参。"""
    return [call.args[0] for call in embeddings.embed_documents.call_args_list]


def _upserted_docs_1404(collection: MagicMock) -> dict[str, str]:
    """累计该 collection 所有 upsert 调用的 (id → document) 映射。"""
    docs: dict[str, str] = {}
    for call in collection.upsert.call_args_list:
        docs.update(dict(zip(call.kwargs["ids"], call.kwargs["documents"], strict=True)))
    return docs


@pytest.mark.parametrize(
    ("count", "expected_calls"),
    [
        (1, 1),
        (64, 1),  # 恰好上限 → 不分片（off-by-one 守护）
        (65, 2),
        (128, 2),
        (129, 3),
        (150, 3),
    ],
)
async def test_index_batch_embeds_in_chunks_of_provider_limit(
    tmp_path: Path, count: int, expected_calls: int
) -> None:
    """#1404: index_batch 按 64 条上限分片调用 embed_documents（每次入参 ≤ 64）。"""
    entities = _entities_1404(count)
    with mock_store_ctx(tmp_path) as (store, collections, embeddings):
        await store.index_batch(entities)

    batches = _embed_batches_1404(embeddings)
    assert len(batches) == expected_calls, (
        f"#1404: {count} 条实体应分 {expected_calls} 次 embed（每次 ≤ 64 条），"
        f"实际 {len(batches)} 次（整批一次提交即触发 zhipu 400 code 1214）"
    )
    for batch in batches:
        assert len(batch) <= EMBED_REQUEST_LIMIT_1404, (
            f"#1404: 单次 embed_documents 入参 {len(batch)} 条超过 provider 上限 64"
        )
    # 分片展开后不丢不重、顺序保持（= 有效实体顺序）
    assert [doc for batch in batches for doc in batch] == [e.content for e in entities]
    # 合并后仍一次性 upsert（语义不变：每类型一次写入）
    upsert = collections[f"inkflow_{EntityType.CHARACTER.value}"].upsert
    assert upsert.call_count == 1
    assert len(upsert.call_args.kwargs["embeddings"]) == count


async def test_index_batch_survives_provider_input_limit(tmp_path: Path) -> None:
    """#1404: provider 硬拒绝 > 64 条 input 时 index_batch 仍全量入库、不抛异常。"""
    entities = _entities_1404(150)
    with mock_store_ctx(tmp_path, _ChunkLimitedEmbeddings()) as (store, collections, _):
        await store.index_batch(entities)
    stored = _upserted_docs_1404(collections[f"inkflow_{EntityType.CHARACTER.value}"])
    assert stored == {e.id: e.content for e in entities}


async def test_index_batch_chunked_result_matches_per_entity(tmp_path: Path) -> None:
    """#1404: 分片批量索引写入内容与逐条 index 一致（按 id 对齐，顺序无关）。"""
    entities = [
        *_entities_1404(70),  # 超 64 → 触发分片
        *_entities_1404(30, EntityType.SETTING),
    ]
    with (
        mock_store_ctx(tmp_path) as (store_a, collections_a, _),
        mock_store_ctx(tmp_path) as (store_b, collections_b, _),
    ):
        await store_a.index_batch(entities)
        for entity in entities:
            await store_b.index(entity)

    for entity_type in (EntityType.CHARACTER, EntityType.SETTING):
        expected = {e.id: e.content for e in entities if e.entity_type is entity_type}
        key = f"inkflow_{entity_type.value}"
        batch_side = _upserted_docs_1404(collections_a[key])
        single_side = _upserted_docs_1404(collections_b[key])
        assert batch_side == single_side, (
            f"#1404: {entity_type.value} 分片批量写入内容与逐条索引不一致"
        )
        assert batch_side == expected
        # 分片侧每类型仅一次 upsert（幂等语义保持）；逐条侧为 N 次覆盖写
        assert collections_a[key].upsert.call_count == 1


async def test_index_batch_chunking_preserves_empty_content_guard_929(tmp_path: Path) -> None:
    """#1404 回归: #929 空串守卫在分片路径下行为不变。

    空白 content 逐条 warning + 跳过（不进任何分片入参、不写 chroma）；
    分片只作用于过滤后的有效实体（70 条 → ceil(70/64) = 2 次）。
    """
    entities = _entities_1404(70)
    entities.insert(3, make_entity("blank-1", EntityType.CHARACTER, "p1", "   "))
    entities.insert(40, make_entity("blank-2", EntityType.CHARACTER, "p1", ""))
    warnings: list[str] = []
    sink_id = logger.add(
        lambda message: warnings.append(message.record["message"]), level="WARNING"
    )
    try:
        with mock_store_ctx(tmp_path) as (store, collections, embeddings):
            await store.index_batch(entities)
    finally:
        logger.remove(sink_id)

    batches = _embed_batches_1404(embeddings)
    assert len(batches) == 2, "#1404: 70 条有效实体应分 2 次 embed"
    flattened = [doc for batch in batches for doc in batch]
    assert len(flattened) == 70
    assert all(doc.strip() for doc in flattened), "#929: 分片入参不得含空白串"
    assert any("blank-1" in msg for msg in warnings), "#929: 空白实体应逐条 warning（含 id）"
    assert any("blank-2" in msg for msg in warnings), "#929: 空白实体应逐条 warning（含 id）"

    # 空白实体不写 chroma，有效实体一次 upsert 全量写入
    upsert = collections[f"inkflow_{EntityType.CHARACTER.value}"].upsert
    upsert_ids = upsert.call_args.kwargs["ids"]
    assert upsert.call_count == 1
    assert len(upsert_ids) == 70
    assert "blank-1" not in upsert_ids and "blank-2" not in upsert_ids
