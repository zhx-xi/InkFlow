"""#929 RED 契约：向量层空串守卫（#328 家族根治，issue 修复方向 1）。

缺陷背景：zhipu embedding API 拒绝空 prompt（400 1213「未正常接收到prompt内容」）。
#328 只修了维度探测点（`_probe_embedding_dimension_sync` 用 "0" 占位），同文件其余
embed 调用无防护：`:196 _index_sync embed_documents([entity.content])`（content
空白 → 空串入批）、`:217 _index_batch_sync`（同批量）、`:242 _retrieve_sync
embed_query(query)`（query 空白直打）。

用户拍板（A 确定性降级）：空白输入 → **跳过 embed + 降级语义**（retrieve → []，
index → 该实体 no-op 跳过 + warning），**绝不阻断调用方**（reindex 继续、生成继续）。

探针实证（.hermes/tmp_repro_c.py）：OpenAIEmbeddings(embed_query("")) → zhipu
BadRequestError 400 1213（同款指纹）；非空 → 成功 dim 2048。

【R】= 当前必 FAIL；【G】= 回归守护。
形态：纯 mock chroma + mock embeddings（镜像 test_vector_store_protocol_coverage.py
mock_env——计数断言用 MagicMock embeddings，不触发真实网络）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from inkflow.domain.ports.vector_store import EntityType, IndexableEntity
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore

PROJECT = "p-929"


@pytest.fixture
def mock_env(tmp_path: Path):
    """mock chroma + mock embeddings（embed_documents/embed_query 为 MagicMock）。"""
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1] * 8
    embeddings.embed_documents.return_value = [[0.1] * 8, [0.2] * 8, [0.3] * 8]
    client = MagicMock()
    collections: dict[str, MagicMock] = {}

    def get_or_create(name: str, **kwargs):
        if name not in collections:
            c = MagicMock()
            c.name = name
            c.get.return_value = {"ids": [], "documents": None, "embeddings": None}
            collections[name] = c
        return collections[name]

    client.get_or_create_collection.side_effect = get_or_create
    client.list_collections.return_value = []
    client.get_or_create_collection("inkflow_meta")
    for et in EntityType:
        client.get_or_create_collection(f"inkflow_{et.value}")

    with patch(
        "inkflow.infrastructure.rag.langchain_vector_store.chromadb.PersistentClient",
        return_value=client,
    ):
        store = LangChainVectorStore(persist_dir=tmp_path, embeddings=embeddings)
        store._client = client
        yield store, client, collections, embeddings


def _entity(eid: str, content: str, et: EntityType = EntityType.CHARACTER) -> IndexableEntity:
    return IndexableEntity(
        id=eid, entity_type=et, project_id=PROJECT, content=content, metadata={"name": eid}
    )


class TestRetrieveEmptyQueryGuard:
    """空/空白 query → 跳过 embed_query + 返回 []（确定性降级，不 400 不抛）。"""

    async def test_r1_retrieve_empty_query_skips_embed(self, mock_env) -> None:
        store, _client, _collections, emb = mock_env
        result = await store.retrieve("", project_id=PROJECT)
        assert result == [], "#929 空 query 必须确定性降级为空结果"
        emb.embed_query.assert_not_called()

    async def test_r2_retrieve_whitespace_query_skips_embed(self, mock_env) -> None:
        store, _client, _collections, emb = mock_env
        result = await store.retrieve("   \n\t ", project_id=PROJECT)
        assert result == []
        emb.embed_query.assert_not_called()

    async def test_g1_retrieve_nonempty_still_embeds(self, mock_env) -> None:
        """【G】守护：非空 query 正常走 embed（守卫勿误伤主路径）。"""
        store, _client, collections, emb = mock_env
        coll = collections[f"inkflow_{EntityType.CHARACTER.value}"]
        coll.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        result = await store.retrieve("林晚的身世", project_id=PROJECT)
        assert result == []
        emb.embed_query.assert_called_once_with("林晚的身世")


class TestIndexEmptyContentGuard:
    """空白 content 实体 → 跳过 embed + 不写 chroma（no-op + warning）。"""

    async def test_r3_index_single_empty_content_noop(self, mock_env) -> None:
        store, _client, collections, emb = mock_env
        await store.index(_entity("e-blank", ""))
        emb.embed_documents.assert_not_called()
        coll = collections[f"inkflow_{EntityType.CHARACTER.value}"]
        coll.upsert.assert_not_called()

    async def test_r4_index_whitespace_content_noop(self, mock_env) -> None:
        store, _client, collections, emb = mock_env
        await store.index(_entity("e-ws", "  \t \n "))
        emb.embed_documents.assert_not_called()
        collections[f"inkflow_{EntityType.CHARACTER.value}"].upsert.assert_not_called()

    async def test_r5_batch_mixed_filters_blank_keeps_valid(self, mock_env) -> None:
        """混合批：空白实体被过滤（逐条 warning），合法实体正常 embed+upsert。

        终判据 = embed_documents 入参列表**不含任何空白串**（issue 契约测试要求）。
        """
        store, _client, collections, emb = mock_env
        emb.embed_documents.return_value = [[0.1] * 8, [0.2] * 8]
        entities = [
            _entity("ok-1", "角色甲：蜀山掌门"),
            _entity("blank-1", "   "),
            _entity("ok-2", "角色乙：师妹宁晚"),
        ]
        await store.index_batch(entities)
        assert emb.embed_documents.call_count == 1
        docs_arg = emb.embed_documents.call_args.args[0]
        assert all(isinstance(d, str) and d.strip() for d in docs_arg), (
            f"#929: embed_documents 入参含空白串（zhipu 400 家族路径）：{docs_arg!r}"
        )
        assert [d for d in docs_arg] == ["角色甲：蜀山掌门", "角色乙：师妹宁晚"]
        coll = collections[f"inkflow_{EntityType.CHARACTER.value}"]
        upsert_ids = coll.upsert.call_args.kwargs["ids"]
        assert upsert_ids == ["ok-1", "ok-2"], "空白实体不得写入 chroma"

    async def test_r6_batch_all_blank_zero_embed_no_raise(self, mock_env) -> None:
        """全空白批 → embed_documents 零调用、不上抛（reindex 继续 = 降级不中断）。"""
        store, _client, collections, emb = mock_env
        await store.index_batch([_entity("b1", ""), _entity("b2", " \n ")])
        emb.embed_documents.assert_not_called()
        collections[f"inkflow_{EntityType.CHARACTER.value}"].upsert.assert_not_called()

    async def test_g2_batch_valid_only_unchanged(self, mock_env) -> None:
        """【G】守护：全合法批行为零变化（一次 embed + 一次 upsert）。"""
        store, _client, collections, emb = mock_env
        emb.embed_documents.return_value = [[0.1] * 8, [0.2] * 8]
        await store.index_batch([_entity("v1", "甲设定"), _entity("v2", "乙设定")])
        emb.embed_documents.assert_called_once()
        assert emb.embed_documents.call_args.args[0] == ["甲设定", "乙设定"]
        coll = collections[f"inkflow_{EntityType.CHARACTER.value}"]
        assert coll.upsert.call_args.kwargs["ids"] == ["v1", "v2"]
