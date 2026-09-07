"""#1011 写侧 hnsw 落盘自检 RED 契约 + 既有行为守护.

缺陷背景（#1011，已终裁）
-------------------------
v0.13.0-rc6 打包产物冷启动全新库：reindex 成功 → 立即 retrieve 首调 500。stack trace 证明
服务层自愈确实执行，但 store 层写后落盘窗口（≈2s 双保险合计）追不上冷启动 hnsw 段落盘
（实测 ≈26s 才就绪）。

修复方案：infrastructure/rag/langchain_vector_store.py 写侧（_index_sync /
_index_batch_sync）将在 upsert 后调用新私有方法 ``_ensure_hnsw_flushed(collection)``：
内部循环 collection.count() + collection.query 探针，捕 chromadb.errors.InternalError
有界退避重试，确保 hnsw 段落盘后才返回。

本文件覆盖该修复的 RED 契约 + 既有行为守护：

RED 阶段（main@ 写路径无 _ensure_hnsw_flushed 调用点）：
- test_index_batch_invokes_ensure_hnsw_flushed  FAIL（spy 计数 0 → 无调用点）
- test_index_sync_invokes_ensure_hnsw_flushed    FAIL（同理）

守护（现有行为，防 flush 改动回归）：
- test_index_batch_then_retrieve_immediately_returns  PASS（现有 count() 触发落盘）

spy 说明（raising=False）：_ensure_hnsw_flushed 当前不存在 → monkeypatch.setattr(...,
raising=False) 会静默补上该方法，但因 _index_sync / _index_batch_sync 代码体无调用点 →
计数恒 0 → 断言 FAIL = 干净 RED 信号；GREEN 义务即补调用点后转绿。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.embeddings import Embeddings

from inkflow.domain.ports.vector_store import EntityType, IndexableEntity
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore


class FakeEmbeddings(Embeddings):
    """确定性伪 Embedding — 384 维字符袋向量（对齐 BGE 输出维度）。

    同文本 query/doc 余弦相似度 = 1.0；共享字符越多相似度越高、无共享字符 = 0，
    与 tests/unit/infrastructure/rag/test_langchain_vector_store.py:32 的定义一致
    （复制到本文件，避免跨测试模块 import 脆弱）。
    """

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


@pytest.fixture
def store(tmp_path: Path) -> LangChainVectorStore:
    """临时 chroma 持久化目录的向量存储实例（persist_dir = tmp_path / "chroma"）。"""
    return LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())


def make_entity(
    entity_id: str,
    entity_type: EntityType,
    project_id: str,
    content: str,
) -> IndexableEntity:
    """构造测试实体（metadata 走空字典，检索只依赖 project_id + content）。"""
    return IndexableEntity(
        id=entity_id,
        entity_type=entity_type,
        project_id=project_id,
        content=content,
        metadata={},
    )


# ── RED 契约：写路径调用 _ensure_hnsw_flushed ──


async def test_index_batch_invokes_ensure_hnsw_flushed(store, monkeypatch):
    """契约 1：index_batch 写 1 实体后 _ensure_hnsw_flushed 被调用 ≥1 次。

    RED：方法不存在（raising=False 静默补上）+ 写路径无调用点 → 计数 0 → FAIL。
    GREEN 义务：_index_batch_sync 每类型组 upsert 后调用 self._ensure_hnsw_flushed(collection)。
    """
    calls: list = []

    def fake_flush(self, collection):
        calls.append(collection)

    monkeypatch.setattr(LangChainVectorStore, "_ensure_hnsw_flushed", fake_flush, raising=False)

    await store.index_batch([make_entity("c1", EntityType.CHARACTER, "p1", "苹果")])

    assert (
        len(calls) >= 1
    ), "index_batch 写后未调用 _ensure_hnsw_flushed（RED：方法不存在/无调用点）"


async def test_index_sync_invokes_ensure_hnsw_flushed(store, monkeypatch):
    """契约 2：_index_sync 单实体路径同样调用 _ensure_hnsw_flushed。

    RED：同契约 1，单实体 index 后计数 0 → FAIL。
    GREEN 义务：_index_sync 在 collection.upsert 后调用 self._ensure_hnsw_flushed(collection)。
    """
    calls: list = []

    def fake_flush(self, collection):
        calls.append(collection)

    monkeypatch.setattr(LangChainVectorStore, "_ensure_hnsw_flushed", fake_flush, raising=False)

    await store.index(make_entity("c1", EntityType.CHARACTER, "p1", "苹果"))

    assert len(calls) >= 1, "index 单实体写后未调用 _ensure_hnsw_flushed（RED）"


# ── 守护：写后立即可检索（现有行为，防 flush 改动回归）──


async def test_index_batch_then_retrieve_immediately_returns(store):
    """守护：真实 chroma（tmp_path）下 index_batch → 立即 retrieve 可查到结果。

    现有 _index_batch_sync 在 upsert 后调用 collection.count() 触发 WAL→段落盘，保证
    写后立即检索可命中；本用例守护该既有行为，防止未来 flush 桥/_ensure_hnsw_flushed
    改动把「写后立即可查」改坏。
    """
    await store.index_batch([make_entity("c1", EntityType.CHARACTER, "p1", "苹果")])
    results = await store.retrieve("苹果", project_id="p1", min_score=0.01)
    assert [r.entity_id for r in results] == ["c1"]


async def test_ensure_hnsw_flushed_non_internal_error_not_propagated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m2（PR #1023 评审）：探针 query 抛非 InternalError（连接/元数据异常）不得
    传播出写路径——upsert 已成功时自检只能降级（warning），禁硬失败。

    GREEN 义务：_ensure_hnsw_flushed 最外层 except Exception 兜底 → logger.warning
    + return，不上抛。RED（main@a966f47 仅捕 InternalError）：ValueError 传播 →
    本用例 FAIL。
    """
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())
    await store.index(make_entity("c1", EntityType.CHARACTER, "p1", "苹果"))

    class _BoomCollection:
        """count 正常、query 抛非 InternalError（模拟 chroma 连接/元数据异常）。"""

        name = "inkflow_character"

        def count(self) -> int:
            return 1

        def query(self, **kwargs: object) -> dict:
            raise ValueError("connection metadata exploded")

    with store._lock:  # 调用方持锁契约（#468）
        store._ensure_hnsw_flushed(_BoomCollection())  # type: ignore[arg-type]
        # m2 GREEN：不得抛；异常传播即 FAIL（pytest 自动判）


async def test_ensure_hnsw_flushed_real_invocation(tmp_path):
    """#1011 + func-cov：真实（非 spy）_ensure_hnsw_flushed 全执行路径覆盖。

    1. 探针缺失（_probe_embedding=None）→ 防御 WARNING 静默返回（不上抛）；
    2. index_batch 写后持锁直调（快盘上首轮探针 query 即成功）——真实函数体被执行，
       锁死 func-cov「new uncalled」误判面（RED spy 用例替换了真实现，真函数从未跑）。
    """
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())
    with store._lock:  # _get_collection 契约：调用方须持锁（#468，单线程测试亦守纪律）
        collection = store._get_collection(EntityType.CHARACTER)

    # 路径 1：无探针向量 → 静默 return（禁抛异常打断写路径）
    store._probe_embedding = None
    store._ensure_hnsw_flushed(collection)  # 不抛即通过（防御分支）

    # 路径 2：写入后真实自检 → 立即返回（快盘首轮成功）
    await store.index(make_entity("c1", EntityType.CHARACTER, "p1", "苹果"))
    assert store._probe_embedding is not None  # 写路径已暂存探针
    store._ensure_hnsw_flushed(collection)
    # 自检通过后立读必命中（与既有守护同源行为）
    results = await store.retrieve("苹果", project_id="p1", min_score=0.01)
    assert [r.entity_id for r in results] == ["c1"]
