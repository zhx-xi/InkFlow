"""#1563 RED 契约：hnsw 段卡死 → 读侧「空写 nudge」自愈。

缺陷（0.17.0-rc2 打包产物受控复现；脚本级确定性复现 + 二分定位）
------------------------------------------------------------------
`reindex` 成功返回后**首个** `retrieve` 恒 500；第二调 200。

实测根因（`chroma.sqlite3` 的 `segments`/`max_seq_id`）：
**一次「别的 collection 的写」（`reindex` 的 commit-last 指纹写 `inkflow_meta` 恒为最后一次写）
会让本 collection 的 `METADATA.max_seq_id` 领先 `VECTOR.max_seq_id` 且不再自动追赶**；
带 `where` 的读 plan 需要两段一致 → 抛
`Error executing plan: Internal error: Error finding id`。

关键实验结论（见 PR body 动作矩阵，每项独立复现）：

| 动作 | 结果 |
|------|------|
| 只等待 / 只读 / 重复读 | ❌ **永久 FAIL（≥60s 不恢复）** |
| `count()` + 无 where 探针 query | ❌ FAIL（= 写侧旧自检为何失灵） |
| 再写一次 `inkflow_meta` | ❌ FAIL |
| **对本 collection 再做一次写**（`upsert` 同实体 / **仅元数据 `update`**） | ✅ 立即 OK |

→ 故修复 = **读侧捕获 `InternalError` 后对本 collection 做一次「元数据 no-op 空写」触发 pending
log apply，再重试真实查询**（有界），并把失败文案改为指引「重试一次」。

RED 形态（main@d8dae36e）：`_retrieve_sync` 只做「count + 固定次数重试」，**从不写** →
本文件契约 1/2/4 FAIL；契约 3（文案）因旧文案为「建议重建索引后重试」亦 FAIL。
全部用例确定性：patch `query`/`update` 行为，不依赖真实 hnsw 落盘时序。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import chromadb
import pytest
from langchain_core.embeddings import Embeddings

from inkflow.domain.ports.extraction_errors import VectorStoreError
from inkflow.domain.ports.vector_store import EntityType, IndexableEntity
from inkflow.infrastructure.rag import langchain_vector_store as lvs_module
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore

# 「别的 collection 写完 → 本段 pending log 未 apply」时读 plan 的报错
_STALE = "Error executing plan: Internal error: Error finding id"


class FakeEmbeddings(Embeddings):
    """确定性伪 Embedding — 384 维字符袋向量（与同目录既有用例一致）。"""

    dimension = 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for ch in text:
            vec[ord(ch) % self.dimension] += 1.0
        return vec


def make_entity(entity_id: str, project_id: str, content: str) -> IndexableEntity:
    """构造测试实体（metadata 空 → chroma 侧 metadata = {project_id}）。"""
    return IndexableEntity(
        id=entity_id,
        entity_type=EntityType.CHARACTER,
        project_id=project_id,
        content=content,
        metadata={},
    )


@pytest.fixture
def store(tmp_path: Path) -> LangChainVectorStore:
    return LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())


class _StuckUntilWrite:
    """模拟 #1563 卡死：写发生前 query 恒抛 InternalError（= pending log 未 apply）。

    记录所有 `update` 调用的参数，供契约 2 校验「空写」形态。
    """

    def __init__(self, collection: Any) -> None:
        self.collection = collection
        self.written = False
        self.update_calls: list[dict[str, Any]] = []
        self.query_calls = 0

    def install(self) -> None:
        real_update = self.collection.update
        real_query = self.collection.query
        outer = self

        def spy_update(*args: Any, **kwargs: Any) -> Any:
            outer.update_calls.append(kwargs)
            outer.written = True
            return real_update(*args, **kwargs)

        def gated_query(*args: Any, **kwargs: Any) -> Any:
            outer.query_calls += 1
            if not outer.written:
                raise chromadb.errors.InternalError(_STALE)
            return real_query(*args, **kwargs)

        patch.object(self.collection, "update", side_effect=spy_update).start()
        patch.object(self.collection, "query", side_effect=gated_query).start()


# ── 契约 1（根因断言）：段卡死时首读必须靠「本 collection 空写」自愈并返回命中 ──


async def test_retrieve_heals_stuck_segment_via_write_and_returns(
    store: LangChainVectorStore,
) -> None:
    """RED：main 只 count + 重试（从不写）→ 6 次重试全败 → 抛 VectorStoreError → FAIL。

    GREEN 义务：首次 InternalError 后对本 collection 做一次空写（触发 pending log apply），
    再重试真实查询并返回命中。
    """
    await store.index_batch([make_entity("c1", "p1", "苹果")])
    collection = store._collections[EntityType.CHARACTER]
    stuck = _StuckUntilWrite(collection)
    try:
        stuck.install()
        results = await store.retrieve("苹果", project_id="p1", min_score=0.01)
    finally:
        patch.stopall()

    assert [r.entity_id for r in results] == ["c1"], (
        f"段卡死时首读未自愈（{results}）——义务：空写触发 apply 后重试必须返回命中"
    )
    assert stuck.update_calls, "未对本 collection 发出任何写——无法触发 pending log apply"


# ── 契约 2（空写形态）：必须是「元数据 no-op」，不得改写 document/embedding ──


async def test_heal_write_is_metadata_noop(
    store: LangChainVectorStore,
) -> None:
    """自愈写必须是**元数据原样回写**的空写——禁止改数据面语义（不得重写向量/文档）。"""
    await store.index_batch([make_entity("c1", "p1", "苹果")])
    collection = store._collections[EntityType.CHARACTER]
    stuck = _StuckUntilWrite(collection)
    try:
        stuck.install()
        await store.retrieve("苹果", project_id="p1", min_score=0.01)
    finally:
        patch.stopall()

    assert stuck.update_calls, "未发起自愈写"
    call = stuck.update_calls[0]
    assert call.get("ids") == ["c1"], f"自愈写应针对该 collection 现存 id: {call}"
    assert call.get("metadatas") == [{"project_id": "p1"}], (
        f"自愈写必须原样回写 metadata（no-op），实际 {call.get('metadatas')}"
    )
    assert "documents" not in call and "embeddings" not in call, (
        f"自愈写不得触碰 document/embedding（改数据面语义）: {sorted(call)}"
    )


# ── 契约 3（C 文案）：仍失败时指引「重试一次」，不得误导重建索引 ──


async def test_failure_message_points_to_retry_not_reindex(
    store: LangChainVectorStore,
) -> None:
    """RED：旧文案「（…），建议重建索引后重试」→ FAIL（重建无效，重试一次即过）。"""
    await store.index_batch([make_entity("c1", "p1", "苹果")])
    collection = store._collections[EntityType.CHARACTER]
    with (
        patch.object(
            collection,
            "query",
            side_effect=chromadb.errors.InternalError(_STALE),
        ),
        pytest.raises(VectorStoreError) as exc_info,
    ):
        await store.retrieve("苹果", project_id="p1", min_score=0.01)

    message = str(exc_info.value)
    assert "重试一次" in message, f"文案未指引重试一次: {message}"
    assert "重建索引" not in message, f"文案仍在误导重建索引: {message}"
    assert "hnsw" in message, f"应保留 hnsw 诊断标识: {message}"


# ── 契约 4（有界）：自愈写次数必须有界，不得无界重试 ──


async def test_heal_write_is_bounded(store: LangChainVectorStore) -> None:
    """段永久卡死时自愈写次数必须封顶（禁无界重试/无界写）。"""
    await store.index_batch([make_entity("c1", "p1", "苹果")])
    collection = store._collections[EntityType.CHARACTER]
    writes = 0
    real_update = collection.update

    def counting_update(*args: Any, **kwargs: Any) -> Any:
        nonlocal writes
        writes += 1
        return real_update(*args, **kwargs)

    with (
        patch.object(collection, "update", side_effect=counting_update),
        patch.object(collection, "query", side_effect=chromadb.errors.InternalError(_STALE)),
        pytest.raises(VectorStoreError),
    ):
        await store.retrieve("苹果", project_id="p1", min_score=0.01)

    assert writes >= 1, "段卡死却零自愈写（契约前提：必须尝试写侧自愈）"
    assert writes <= lvs_module._SEGMENT_HEAL_MAX_WRITES, (
        f"自愈写 {writes} 次超出上限 {lvs_module._SEGMENT_HEAL_MAX_WRITES}——禁无界重试"
    )
