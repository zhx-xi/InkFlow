"""#1011 评审 M2/m1 追加契约：重试链延迟预算（最坏路径不冲 30s 客户端超时）.

背景（PR #1023 只读评审 M2/m1 采纳项）：仓库既有客户端默认 30s
（infrastructure/http/client.py:65 _default_timeout=30.0）。本 PR 修复引入的
新延迟必须封顶，否则「自愈链生效」变成「客户端先超时」：
- 写侧 _ensure_hnsw_flushed 现预算 0.5×2^n（0.5/1/2/4/8 ≈15.5s/类型）× 5 类型
  = reindex 最坏 +77s（评审 m1 成本面：慢盘上 reindex 自身先超时）；
- 读侧 max_attempts=7 × 0.5s 步长 = 3s/类型（评审 M2 链：首 retrieve + 自愈
  reindex + 第二 retrieve 叠加挤压 30s）。

GREEN 义务（父侧裁决）：
- 读侧步长恢复 #873 原口径 0.25s（单次 retrieve 每类型重试累计 ≤1.5s）；
- 写侧自检单条 sleep ≤1s 且每类型累计 ≤4s（reindex 最坏 +20s，配合读侧/自愈
  仍在 30s 客户端口径内）。
RED 形态（main@a966f47）：读侧步长 0.5s（3s/类型）→ 断言 FAIL；写侧指数退避
最高 8s/条、累计 15.5s → 断言 FAIL。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
import pytest
from langchain_core.embeddings import Embeddings

from inkflow.domain.ports.extraction_errors import VectorStoreError
from inkflow.domain.ports.vector_store import EntityType, IndexableEntity
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore


class FakeEmbeddings(Embeddings):
    """确定性伪 Embedding — 384 维字符袋向量（与同目录 1011 文件一致）。"""

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


def make_entity(
    entity_id: str,
    entity_type: EntityType,
    project_id: str,
    content: str,
) -> IndexableEntity:
    """构造测试实体。"""
    return IndexableEntity(
        id=entity_id,
        entity_type=entity_type,
        project_id=project_id,
        content=content,
        metadata={},
    )


# ── 契约 1（M2）：读侧单次 retrieve 调用（全类型合计）重试预算 ≤1.5s ──


async def test_retrieve_retry_chain_within_873_scale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2：hnsw 段持续未就绪 → 单次 retrieve 全部类型累计 sleep ≤1.5s、步长 ≤0.25s。

    RED：main 现 0.5s×6×5 类型 = 15s（步长 0.5）→ FAIL。GREEN：重试改**调用级
    共享 deadline**（全类型合计 ≤1.5s，步长恢复 #873 的 0.25s 口径）——自愈链
    retrieve1(≤1.5) + reindex(~26s 实测) + retrieve2(≤1.5) ≈ 29s，守在 30s
    客户端口径内（reindex 走 CLI 300s 轨不受挤压）。
    """
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())
    await store.index_batch(
        [make_entity(f"c{i}", EntityType.CHARACTER, "p1", f"内容{i}") for i in range(3)]
    )

    sleeps: list[float] = []
    monkeypatch.setattr(
        "inkflow.infrastructure.rag.langchain_vector_store.time.sleep",
        lambda s: sleeps.append(s),
    )

    def always_fail(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise chromadb.errors.InternalError(
            "Error executing plan: Internal error: "
            "Error creating hnsw segment reader: Nothing found on disk"
        )

    monkeypatch.setattr(chromadb.Collection, "query", always_fail)
    with pytest.raises(VectorStoreError):
        await store.retrieve("内容", project_id="p1")

    assert sleeps, "未触发任何重试 sleep（契约前提：首查失败必须走重试链）"
    assert all(s <= 0.25 + 1e-9 for s in sleeps), (
        f"读侧重试步长出现 >0.25s（现值 {sleeps}）——M2 义务：恢复 #873 原口径"
    )
    assert sum(sleeps) <= 1.5 + 1e-9, (
        f"单类型重试累计 sleep {sum(sleeps):.2f}s >1.5s——M2 义务：自愈链总延迟"
        "守在 30s 客户端超时内"
    )


# ── 契约 2（m1）：写侧自检等待预算封顶（单条 ≤1s、每类型累计 ≤4s）──


async def test_flush_self_check_wait_budget_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m1：落盘自检对持续未就绪的段等待必须封顶——单条 sleep ≤1s 且每类型
    累计 ≤4s（否则 reindex 5 类型最坏 +77s，慢盘上 reindex 自身先超 30s）。

    RED：main 现指数退避 0.5/1/2/4/8 = 15.5s/类型 → FAIL。
    GREEN：改线性小额退避（如 0.5×8 或 1×4），预算 ≤4s。
    """
    store = LangChainVectorStore(persist_dir=tmp_path / "chroma", embeddings=FakeEmbeddings())

    sleeps: list[float] = []
    monkeypatch.setattr(
        "inkflow.infrastructure.rag.langchain_vector_store.time.sleep",
        lambda s: sleeps.append(s),
    )

    class _NeverReadyCollection:
        """count 正常、query 恒抛 InternalError（模拟段始终未就绪，耗尽预算）。"""

        name = "inkflow_character"

        def count(self) -> int:
            return 1

        def query(self, **kwargs: Any) -> dict:
            raise chromadb.errors.InternalError("Nothing found on disk (test)")

    store._probe_embedding = [0.1] * 384
    with store._lock:  # 调用方持锁契约（#468）
        store._ensure_hnsw_flushed(_NeverReadyCollection())  # type: ignore[arg-type]

    assert sleeps, "段持续未就绪却零等待（契约前提：预算内必须等待）"
    assert all(s <= 1.0 + 1e-9 for s in sleeps), (
        f"自检出现 >1s 单条 sleep（现值 {sleeps}）——m1 义务：小额封顶退避"
    )
    assert sum(sleeps) <= 4.0 + 1e-9, (
        f"自检等待累计 {sum(sleeps):.2f}s >4s/类型——m1 义务：reindex 最坏延迟"
        "配合自愈仍守客户端超时"
    )
    # 预算耗尽不得上抛（写已成功，禁硬失败）——本调用能返回即隐含该契约，
    # m2 契约（test_vector_write_flush_1011.py）另有独立异常类型锁。
