"""#276 向量存储新方法 mock 覆盖测试（coverage 补强 2026-08-12）。

背景：test_langchain_vector_store.py 被 CI coverage-backend 排除（chromadb
与 coverage 同进程冲突，F14 先例）→ G2 新增方法（指纹/探测/差集/重建）在
cov 口径内零覆盖，拉低覆盖率门禁（line 98.14 < 98.5）。本文件用纯 mock
chroma（不触发真实 chromadb C 扩展）覆盖这些方法，可进 cov 口径。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from inkflow.domain.ports.vector_store import EntityType
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore


@pytest.fixture
def mock_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """mock chroma 客户端：get_or_create_collection 按名缓存 collection。"""
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
    # 预创建全部 collection（含 meta）——测试无需先触发方法调用即可访问
    client.get_or_create_collection("inkflow_meta")
    for et in EntityType:
        client.get_or_create_collection(f"inkflow_{et.value}")

    with patch(
        "inkflow.infrastructure.rag.langchain_vector_store.chromadb.PersistentClient",
        return_value=client,
    ):
        store = LangChainVectorStore(persist_dir=tmp_path, embeddings=MagicMock())
        # __init__ 懒加载——手动注入 mock client（不触发真实 chroma）
        store._client = client
        yield store, client, collections, tmp_path


# ── 指纹读写（meta collection）──


async def test_read_fingerprint_no_doc_returns_none(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    assert await store.read_fingerprint("p1") is None
    meta = _collections["inkflow_meta"]
    meta.get.assert_called_once_with(ids=["fp:p1"])


async def test_read_fingerprint_parses_json_doc(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    meta = _collections["inkflow_meta"]
    fp = {"schema_version": 1, "status": "fresh"}
    meta.get.return_value = {"ids": ["fp:p1"], "documents": [json.dumps(fp)]}
    assert await store.read_fingerprint("p1") == fp


async def test_read_fingerprint_non_str_doc_returns_none(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    meta = _collections["inkflow_meta"]
    meta.get.return_value = {"ids": ["fp:p1"], "documents": [123]}
    assert await store.read_fingerprint("p1") is None


async def test_read_fingerprint_empty_documents_returns_none(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    meta = _collections["inkflow_meta"]
    meta.get.return_value = {"ids": ["fp:p1"], "documents": []}
    assert await store.read_fingerprint("p1") is None


async def test_write_fingerprint_merges_status(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    meta = _collections["inkflow_meta"]
    await store.write_fingerprint("p1", {"schema_version": 1}, "reindexing")
    meta.upsert.assert_called_once()
    kwargs = meta.upsert.call_args.kwargs
    assert kwargs["ids"] == ["fp:p1"]
    assert json.loads(kwargs["documents"][0])["status"] == "reindexing"
    assert json.loads(kwargs["documents"][0])["schema_version"] == 1


# ── 维度探测 ──


async def test_probe_collection_dimension_all_empty_returns_zero(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    assert await store.probe_collection_dimension("p1") == 0


async def test_probe_collection_dimension_returns_first_vector_len(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    char_coll = _collections[f"inkflow_{EntityType.CHARACTER.value}"]
    char_coll.get.return_value = {
        "ids": ["c1"],
        "embeddings": [[0.1] * 384],
    }
    assert await store.probe_collection_dimension("p1") == 384


async def test_probe_collection_dimension_skips_embeddingless(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    char_coll = _collections[f"inkflow_{EntityType.CHARACTER.value}"]
    char_coll.get.return_value = {"ids": ["c1"], "embeddings": None}
    assert await store.probe_collection_dimension("p1") == 0


async def test_probe_embedding_dimension_caches(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    store._embeddings.embed_query.return_value = [0.5] * 768
    assert await store.probe_embedding_dimension() == 768
    assert await store.probe_embedding_dimension() == 768
    store._embeddings.embed_query.assert_called_once()


# ── 差集删除 ──


async def test_delete_stale_removes_orphans(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    char_coll = _collections[f"inkflow_{EntityType.CHARACTER.value}"]
    char_coll.get.return_value = {"ids": ["keep-1", "ghost-1", "ghost-2"]}
    total = await store.delete_stale("p1", {"keep-1"}, entity_types=[EntityType.CHARACTER])
    assert total == 2
    char_coll.delete.assert_called_once_with(ids=["ghost-1", "ghost-2"])


async def test_delete_stale_no_orphans_no_delete_call(mock_env) -> None:
    store, _client, _collections, _ = mock_env
    char_coll = _collections[f"inkflow_{EntityType.CHARACTER.value}"]
    char_coll.get.return_value = {"ids": ["keep-1"]}
    total = await store.delete_stale("p1", {"keep-1"}, entity_types=[EntityType.CHARACTER])
    assert total == 0
    char_coll.delete.assert_not_called()


# ── 重建（备份 + 删除 + 重建）──


async def test_recreate_collections_backs_up_and_rebuilds(mock_env) -> None:
    store, _client, _collections, tmp_path = mock_env
    (tmp_path / "chroma.sqlite3").write_text("x", encoding="utf-8")
    _client.list_collections.return_value = [
        SimpleNamespace(name=f"inkflow_{EntityType.CHARACTER.value}")
    ]
    backup = await store.recreate_collections(entity_types=[EntityType.CHARACTER])
    assert backup.is_dir()
    assert backup.name.startswith(f"{tmp_path.name}.bak-")
    # 删除旧 collection + 重建（get_or_create_collection 再次调用）
    _client.delete_collection.assert_called_once_with(name=f"inkflow_{EntityType.CHARACTER.value}")
    assert _client.get_or_create_collection.call_count >= 2


async def test_recreate_collections_unique_backup_suffix(mock_env) -> None:
    store, _client, _collections, tmp_path = mock_env
    (tmp_path / "chroma.sqlite3").write_text("x", encoding="utf-8")
    # 预建同秒备份目录 → 触发唯一后缀分支
    first = Path(f"{tmp_path}.bak-20260812000000")
    first.mkdir()
    try:
        store._persist_dir = tmp_path
        with patch("inkflow.infrastructure.rag.langchain_vector_store.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260812000000"
            backup = await store.recreate_collections(entity_types=[])
    finally:
        import shutil

        shutil.rmtree(first, ignore_errors=True)
    assert str(backup).endswith("-1")
    assert backup.is_dir()
