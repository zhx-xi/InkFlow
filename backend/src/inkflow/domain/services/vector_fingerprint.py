"""RAG 向量指纹纯函数服务 — 构建 / 序列化 / 比对 / 状态归一（#276 G1）.

全部函数为纯函数（仅标准库 + pydantic），无 I/O 无状态:
- build_fingerprint: 配置 dict → 规范化指纹（base_url 去尾斜杠、
  chunking 缺省键补默认值）;
- fingerprint_to_json / fingerprint_from_json: 字段序固定的无损 roundtrip;
- compare_fingerprints: configured vs indexed 逐字段比对，产出 stale 判定
  与原因（schema_old 优先级最高）;
- normalize_status: 状态机归一（unknown → stale、reindexing 超时 → stale）.

⚠️ normalize_status 签名含 indexed_at（父侧契约修正 2026-08-12）: reindexing
超时判定必须显式携带 indexed_at——仅 (status, now) 无法区分进行中 / 过期，
两用例断言冲突（见测试 docstring）。

依据: docs/qa-rag-consistency-report.md §2.1/§2.3/§3.3; Issue #276 范围 2。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

from datetime import UTC, datetime

from inkflow.domain.models.vector_fingerprint import (
    CHUNKER_VERSION,
    DEFAULT_CHUNK_MODE,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP_RATIO,
    REINDEXING_TIMEOUT,
    SCHEMA_VERSION,
    ChunkingFingerprint,
    EmbeddingFingerprint,
    VectorFingerprint,
)


def build_fingerprint(
    embedding: dict,
    chunking: dict,
    *,
    schema_version: int = SCHEMA_VERSION,
    dimension: int | None = None,
    indexed_at: str | None = None,
    status: str = "fresh",
) -> VectorFingerprint:
    """配置 dict → 规范化指纹（确定性：同输入两次结果逐字段一致）.

    Args:
        embedding: 键 provider / model_id / base_url（base_url 去尾部斜杠）.
        chunking: 键 mode / chunk_size / overlap_ratio / chunker_version，
            缺省键补默认值（fixed / 500 / 0.0 / 1）.
        schema_version: 指纹 schema 版本（默认当前 SCHEMA_VERSION）.
        dimension: embedding 维度；None = 未 embed 过.
        indexed_at: 最近一次索引时间（ISO 8601 字符串，可空）.
        status: 状态机初始值（默认 fresh）.
    """
    emb = EmbeddingFingerprint(
        provider=embedding["provider"],
        model_id=embedding["model_id"],
        base_url=embedding["base_url"].rstrip("/"),
        dimension=dimension,
    )
    chunk = ChunkingFingerprint(
        mode=chunking.get("mode", DEFAULT_CHUNK_MODE),
        chunk_size=chunking.get("chunk_size", DEFAULT_CHUNK_SIZE),
        overlap_ratio=chunking.get("overlap_ratio", DEFAULT_OVERLAP_RATIO),
        chunker_version=chunking.get("chunker_version", CHUNKER_VERSION),
    )
    return VectorFingerprint(
        schema_version=schema_version,
        embedding=emb,
        chunking=chunk,
        indexed_at=indexed_at,
        status=status,
    )


def fingerprint_to_json(fp: VectorFingerprint) -> str:
    """指纹 → JSON 字符串（字段序固定: schema_version / embedding /
    chunking / indexed_at / status，幂等）.
    """
    return fp.model_dump_json()


def fingerprint_from_json(raw: str) -> VectorFingerprint:
    """JSON 字符串 → 指纹（与 fingerprint_to_json 无损 roundtrip）."""
    return VectorFingerprint.model_validate_json(raw)


def compare_fingerprints(
    configured: VectorFingerprint,
    indexed: VectorFingerprint | None,
) -> tuple[bool, str | None]:
    """configured 与 indexed 指纹比对 → (stale, reason).

    规则（优先级 schema_old > model_changed > chunking_changed）:
    - indexed 为 None（无指纹）→ (True, "unknown");
    - indexed.schema_version < configured.schema_version → "schema_old";
    - model_id 或 base_url 不同 → "model_changed";
    - chunking 任一字段不同 → "chunking_changed";
    - 一致 → (False, None)。dimension 不参与比对（由装配层单独判 mismatch）.
    """
    if indexed is None:
        return True, "unknown"
    if indexed.schema_version < configured.schema_version:
        return True, "schema_old"
    if (
        indexed.embedding.model_id != configured.embedding.model_id
        or indexed.embedding.base_url != configured.embedding.base_url
    ):
        return True, "model_changed"
    if indexed.chunking != configured.chunking:
        return True, "chunking_changed"
    return False, None


def normalize_status(
    status: str,
    *,
    now: datetime | None = None,
    indexed_at: str | None = None,
) -> str:
    """状态机归一（unknown 视同 stale；reindexing 超时 24h → stale）.

    Args:
        status: 原始状态值（fresh / stale / unknown / reindexing）.
        now: 当前时间（缺省 datetime.now(UTC)）.
        indexed_at: 最近一次索引时间（ISO 8601 字符串）; reindexing 超时
            判定必须显式携带——None = 视为进行中，不误判过期.
    """
    if status == "fresh":
        return "fresh"
    if status == "stale":
        return "stale"
    if status == "unknown":
        return "stale"
    if status == "reindexing":
        if indexed_at is None:
            return "reindexing"
        current = now if now is not None else datetime.now(UTC)
        started = datetime.fromisoformat(indexed_at)
        if current - started > REINDEXING_TIMEOUT:
            return "stale"
        return "reindexing"
    return status
