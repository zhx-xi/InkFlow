"""S3d RAG 向量一致性集成旅程（issue #869 非功能补测第四批）：embedding 切换 / 切片变更.

既有 RAG 测试形态（rag-vector-consistency 技能「既有测试套件自检」条目点名的四个
集成旅程缺口）：服务层全 mock（test_extraction_reindex_protocol.py）+ 向量库层
单点（test_langchain_vector_store.py）都锁不住状态依赖断言——「换模型后检索向量
真被重写」「异维重建后可检索」「chunk_size 变更后幽灵块真消失」「中途失败指纹
不 fresh」。本文件用 FakeEmbeddings 双实例 + **真实 chroma tmp 目录** 跑端到端旅程。

D4 embedding 切换：
  同维 1536→1536：A 索引 fresh → 真实存储指纹 vs configured B 比对 stale
  (model_changed)（compare_fingerprints 走 read_fingerprint 真读回）→ reindex B
  collections_recreated=False → collection 原始向量确已被 B 重写（PersistentClient
  直读对比 A-era 快照）→ 检索可解释命中。
  异维 1536→768：probe 异维 → recreate_collections → collections_recreated=True
  + 备份目录生成 → 重建后检索成功。
D5 切片参数变更：FIXED 档 chunk_size 200→1000（块数收缩）→ reindex 差集删除
  真清幽灵块（旧 id 从 list_entities 消失、检索命中 ⊆ 新 id 集）；reindex 中途
  失败（章节仓储抛错）→ commit-last 语义：指纹停留 reindexing 非 fresh →
  修复重跑恢复 fresh。

依据: specs/f14-extraction/spec.md §5.6/§9; design/qa-rag-consistency-report.md
契约 17-20（本协议 mock 版的服务级真实延伸）; issue #276/#277/#869。
"""

from __future__ import annotations

import pathlib
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import chromadb
import pytest
from langchain_core.embeddings import Embeddings

from inkflow.domain.models.vector_fingerprint import VectorFingerprint
from inkflow.domain.ports.vector_store import EntityType
from inkflow.domain.services._chunking import ChunkingConfig, ChunkingMode
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.domain.services.vector_fingerprint import (
    build_fingerprint,
    compare_fingerprints,
)
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000053dd")


class BagEmbeddings(Embeddings):
    """模型可辨的字符袋向量（dimension 可配、model 加盐 → 同文本不同模型向量不同）。

    位置无关 + 确定性：同模型下 query 文本含 document 字符 → 余弦相似度高，
    检索命中可断言；A/B 模型对同一文本产出不同向量，供「原始向量真被重写」断言。
    """

    def __init__(self, dimension: int, model: str) -> None:
        self.dimension = dimension
        self.model = model

    def _embed(self, text: str) -> list[float]:
        salt = sum(ord(ch) for ch in self.model)
        vec = [0.0] * self.dimension
        for ch in text:
            vec[(ord(ch) + salt) % self.dimension] += 1.0
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def configured_fp(model_id: str, dimension: int, chunk_size: int) -> dict:
    """configured 指纹 dict（fingerprint_provider 返回形态，走真实 build_fingerprint）。"""
    fp = build_fingerprint(
        {"provider": "fake", "model_id": model_id, "base_url": "https://x.test/v1"},
        {"mode": "fixed", "chunk_size": chunk_size, "overlap_ratio": 0.0},
        dimension=dimension,
    )
    return fp.model_dump()


def _fp_from_stored(stored: dict) -> VectorFingerprint:
    """read_fingerprint 返回的 dict → VectorFingerprint（比对输入还原）。"""
    return VectorFingerprint.model_validate(stored)


def _long_chapter() -> str:
    """构造跨多 FIXED 块的长章节（句号边界密集，块数随 chunk_size 显著变化）。"""
    return "".join(f"第{i}段，蜀山掌门玄明御剑而行，宁晚在旁参悟剑意。" for i in range(40))


def make_service(
    store: LangChainVectorStore,
    fingerprint: dict,
    *,
    chunk_size: int,
    chapters: list,
) -> ExtractionService:
    """装配真实 vector_store + 分页 mock 仓储的 ExtractionService（仅 CHAPTER_CHUNK 旅程）。"""
    ch_repo = AsyncMock()
    ch_repo.list_chapters = AsyncMock(return_value=(chapters, len(chapters)))
    return ExtractionService(
        project_repo=AsyncMock(),
        chapter_repo=ch_repo,
        run_repo=AsyncMock(),
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=MagicMock(),
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        character_repo=None,
        world_repo=None,
        timeline_repo=None,
        foreshadowing_repo=None,
        vector_store=store,
        fingerprint_provider=AsyncMock(return_value=fingerprint),
        chunking=ChunkingConfig(mode=ChunkingMode.FIXED, chunk_size=chunk_size, overlap_ratio=0.0),
    )


def chapter_ns(chapter_id: int, title: str, content: str) -> SimpleNamespace:
    """reindex 消费的章节最小面（id/title/content/order_index/volume_id）。"""
    return SimpleNamespace(
        id=chapter_id, title=title, content=content, order_index=float(chapter_id), volume_id=None
    )


@pytest.fixture
def store_dir() -> pathlib.Path:
    """真实 chroma 持久化 tmp 目录（绝不触碰用户数据目录）。"""
    return pathlib.Path(tempfile.mkdtemp()) / "chroma"


def _raw_collection_vectors(db_dir: pathlib.Path, ids: list[str]) -> dict[str, list[float]]:
    """PersistentClient 直读 CHAPTER_CHUNK collection 的原始向量（独立实例验证持久化）。"""
    client = chromadb.PersistentClient(path=str(db_dir))
    col = client.get_collection("inkflow_chapter_chunk")
    got = col.get(ids=ids, include=["embeddings"])
    embeddings = got["embeddings"]
    return {
        entity_id: [float(x) for x in vec]
        for entity_id, vec in zip(got["ids"], embeddings, strict=True)
    }


async def test_d4_same_dim_model_switch_stale_then_reindex(store_dir: pathlib.Path) -> None:
    """D4 同维切换：A 索引 → 真实指纹比对 stale(model_changed) → B reindex 重写向量。"""
    chapters = [chapter_ns(1, "第一章", _long_chapter())]

    # ① 模型 A（1536）全量索引 → 指纹 fresh/model-A
    store_a = LangChainVectorStore(store_dir, BagEmbeddings(1536, "model-A"))
    svc_a = make_service(
        store_a, configured_fp("model-A", 1536, 200), chunk_size=200, chapters=chapters
    )
    result_a = await svc_a.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    assert result_a.indexed > 1  # 多块，为后续断言铺路
    fp_a = await store_a.read_fingerprint(str(PID))
    assert fp_a is not None and fp_a["status"] == "fresh"
    assert fp_a["embedding"]["model_id"] == "model-A"
    old_ids = sorted(
        eid for eid, _ in await store_a.list_entities(str(PID), EntityType.CHAPTER_CHUNK)
    )
    a_era = _raw_collection_vectors(store_dir, old_ids)

    # ② 配置改 B（同维 1536）：真实存储指纹 vs configured → stale(model_changed)
    configured_b = build_fingerprint(
        {"provider": "fake", "model_id": "model-B", "base_url": "https://x.test/v1"},
        {"mode": "fixed", "chunk_size": 200, "overlap_ratio": 0.0},
        dimension=1536,
    )
    stale, reason = compare_fingerprints(configured_b, _fp_from_stored(fp_a))
    assert stale is True and reason == "model_changed"

    # ③ 新实例挂模型 B reindex → 不 recreate（同维）、指纹翻 fresh/model-B
    store_b = LangChainVectorStore(store_dir, BagEmbeddings(1536, "model-B"))
    svc_b = make_service(
        store_b, configured_fp("model-B", 1536, 200), chunk_size=200, chapters=chapters
    )
    result_b = await svc_b.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    assert result_b.collections_recreated is False
    fp_b = await store_b.read_fingerprint(str(PID))
    assert fp_b is not None and fp_b["status"] == "fresh"
    assert fp_b["embedding"]["model_id"] == "model-B"

    # ④ 原始向量确已重写（非仅指纹翻转）：同 id 向量 B-era ≠ A-era
    b_era = _raw_collection_vectors(store_dir, old_ids)
    assert set(b_era) == set(a_era)
    assert any(b_era[i] != a_era[i] for i in old_ids)

    # ⑤ B 实例检索命中且可解释（query 含 document 字符 → 高分）
    hits = await store_b.retrieve(
        "玄明御剑而行",
        project_id=str(PID),
        entity_types=[EntityType.CHAPTER_CHUNK],
        top_k=3,
        min_score=0.01,
    )
    assert hits and hits[0].entity_id in set(old_ids)
    assert hits[0].relevance_score > 0.5


async def test_d4_cross_dim_switch_recreates_collections(store_dir: pathlib.Path) -> None:
    """D4 异维切换：1536 索引 → 768 reindex → recreate 重建成功 + 备份目录 + 检索。"""
    chapters = [chapter_ns(1, "第一章", _long_chapter())]
    store_a = LangChainVectorStore(store_dir, BagEmbeddings(1536, "model-A"))
    svc_a = make_service(
        store_a, configured_fp("model-A", 1536, 200), chunk_size=200, chapters=chapters
    )
    await svc_a.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    assert await store_a.probe_collection_dimension(str(PID)) == 1536

    store_c = LangChainVectorStore(store_dir, BagEmbeddings(768, "model-C"))
    svc_c = make_service(
        store_c, configured_fp("model-C", 768, 200), chunk_size=200, chapters=chapters
    )
    result = await svc_c.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    assert result.collections_recreated is True
    assert await store_c.probe_collection_dimension(str(PID)) == 768
    fp = await store_c.read_fingerprint(str(PID))
    assert fp is not None and fp["status"] == "fresh"
    assert fp["embedding"]["dimension"] == 768

    hits = await store_c.retrieve(
        "宁晚在旁参悟剑意",
        project_id=str(PID),
        entity_types=[EntityType.CHAPTER_CHUNK],
        top_k=3,
        min_score=0.01,
    )
    assert hits  # 异维重建后可检索（旧向量已弃）
    # 重建前备份目录已生成（recreate 的 copytree 留痕，tmp 根下 chroma.bak-*）
    backups = [p for p in store_dir.parent.iterdir() if p.name.startswith("chroma.bak-")]
    assert backups, "异维重建必须保留备份目录"


async def test_d5_chunk_size_change_clears_ghost_chunks(store_dir: pathlib.Path) -> None:
    """D5 切片变更：chunk_size 200（多块）→ 1000（少块）→ 差集删除幽灵块，旧块检不到。"""
    chapters = [chapter_ns(1, "第一章", _long_chapter())]
    store = LangChainVectorStore(store_dir, BagEmbeddings(1536, "model-A"))

    svc_small = make_service(
        store, configured_fp("model-A", 1536, 200), chunk_size=200, chapters=chapters
    )
    res_small = await svc_small.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    before = {eid for eid, _ in await store.list_entities(str(PID), EntityType.CHAPTER_CHUNK)}
    assert res_small.indexed == len(before) and len(before) >= 4

    # 配置切片变更（真实存储指纹比对 → chunking_changed）
    stored = await store.read_fingerprint(str(PID))
    assert stored is not None
    configured_big = build_fingerprint(
        {"provider": "fake", "model_id": "model-A", "base_url": "https://x.test/v1"},
        {"mode": "fixed", "chunk_size": 1000, "overlap_ratio": 0.0},
        dimension=1536,
    )
    stale, reason = compare_fingerprints(configured_big, _fp_from_stored(stored))
    assert stale is True and reason == "chunking_changed"

    svc_big = make_service(
        store, configured_fp("model-A", 1536, 1000), chunk_size=1000, chapters=chapters
    )
    res_big = await svc_big.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    after = {eid for eid, _ in await store.list_entities(str(PID), EntityType.CHAPTER_CHUNK)}

    # 幽灵块清除：块数收缩、旧 id 大量消失（纯 upsert 不清理 = 结构性缺陷的实证反面）
    assert res_big.indexed < res_small.indexed
    ghosts = before - after
    assert ghosts, "chunk_size 增大后旧细粒度块必须被差集删除（幽灵块）"
    assert res_big.indexed == len(after)

    # 检索命中 ⊆ 新块 id（旧幽灵块检不到）
    hits = await store.retrieve(
        "玄明御剑而行",
        project_id=str(PID),
        entity_types=[EntityType.CHAPTER_CHUNK],
        top_k=10,
        min_score=0.01,
    )
    assert hits
    assert all(h.entity_id in after for h in hits)


async def test_d5_reindex_failure_not_committed_fresh_then_retry(
    store_dir: pathlib.Path,
) -> None:
    """D5 reindex 中途失败：commit-last → 指纹停留 reindexing（非 fresh）→ 修复重跑 fresh。"""
    chapters = [chapter_ns(1, "第一章", _long_chapter())]
    store = LangChainVectorStore(store_dir, BagEmbeddings(1536, "model-A"))

    svc = make_service(
        store, configured_fp("model-A", 1536, 200), chunk_size=200, chapters=chapters
    )
    # 先建立 fresh 基线
    await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    fp = await store.read_fingerprint(str(PID))
    assert fp is not None and fp["status"] == "fresh"
    baseline = await store.list_entities(str(PID), EntityType.CHAPTER_CHUNK)
    assert baseline

    # 注入中途失败：章节源侧拉取抛错（模拟 DB/网络半程故障）
    svc._chapter_repo.list_chapters = AsyncMock(side_effect=RuntimeError("db down mid-reindex"))
    with pytest.raises(RuntimeError, match="db down mid-reindex"):
        await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    fp = await store.read_fingerprint(str(PID))
    assert fp is not None
    # commit-last 铁律：失败不得留下 fresh（假成功比失败更危险）
    assert fp["status"] != "fresh"

    # 修复 → 重跑成功，指纹回 fresh，数据完整
    svc2 = make_service(
        store, configured_fp("model-A", 1536, 200), chunk_size=200, chapters=chapters
    )
    await svc2.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    fp = await store.read_fingerprint(str(PID))
    assert fp is not None and fp["status"] == "fresh"
    entities = await store.list_entities(str(PID), EntityType.CHAPTER_CHUNK)
    assert len(entities) == len(baseline)
