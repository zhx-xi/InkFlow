"""RAG 向量指纹纯函数契约（#276 S2c，QA 报告 §4.1-B 契约 6-9）。

被测模块（本文件是整模块 RED：两个模块均不存在 → 顶部 import 收集期
ModuleNotFoundError，exit 2）：

- ``inkflow.domain.models.vector_fingerprint``：
  - ``VectorFingerprintStatus``（StrEnum，成员字面量: fresh / stale / unknown /
    reindexing——断言用字符串字面量，不依赖枚举导入形态）
  - ``EmbeddingFingerprint``（pydantic: provider: str, model_id: str,
    base_url: str, dimension: int | None）
  - ``ChunkingFingerprint``（pydantic: mode: str, chunk_size: int,
    overlap_ratio: float, chunker_version: int）
  - ``VectorFingerprint``（pydantic: schema_version: int,
    embedding: EmbeddingFingerprint, chunking: ChunkingFingerprint,
    indexed_at: str | None = None, status: str = "fresh"）
  - 模块级常量：``SCHEMA_VERSION``（int，当前 = 1）、``CHUNKER_VERSION``
    （int，当前 = 1）、``DEFAULT_CHUNK_SIZE``（int，当前 = 500）、
    ``DEFAULT_CHUNK_MODE``（str，当前 = "fixed"）、``DEFAULT_OVERLAP_RATIO``
    （float，当前 = 0.0）、``REINDEXING_TIMEOUT``（timedelta，当前 = 24h）

- ``inkflow.domain.services.vector_fingerprint``（纯函数，仅标准库 +
  pydantic，domain 层零框架依赖）：
  - ``build_fingerprint(embedding: dict, chunking: dict, *,
    schema_version: int = SCHEMA_VERSION, dimension: int | None = None,
    indexed_at: str | None = None, status: str = "fresh") -> VectorFingerprint``
    —— 确定性：同输入两次结果逐字段一致；embedding["base_url"] 归一化
    （去尾部斜杠），chunking 缺省键补默认值；dimension 参数为 None 时
    embedding.dimension = None
  - ``fingerprint_to_json(fp: VectorFingerprint) -> str`` —— 字段序固定
    （schema_version, embedding, chunking, indexed_at, status）的 JSON
  - ``fingerprint_from_json(raw: str) -> VectorFingerprint`` —— 无损 roundtrip
  - ``compare_fingerprints(configured: VectorFingerprint,
    indexed: VectorFingerprint | None) -> tuple[bool, str | None]`` ——
    indexed 为 None → (True, "unknown")；逐字段比对（model_id / base_url /
    chunking 全字段 / schema_version），不一致 → (True, reason)，一致 →
    (False, None)。reason 字面量: "unknown" / "model_changed" /
    "chunking_changed" / "schema_old"。优先级: schema_old > model_changed >
    chunking_changed（schema 旧最先报）。dimension 字段**不参与**比对
    （由装配层单独算 dimension_mismatch）
  - ``normalize_status(status: str, *, now: datetime | None = None,
    indexed_at: str | None = None) -> str``
    —— fresh → "fresh"；stale → "stale"；unknown → "stale"（unknown 视同
    stale，存量用户升级后首次即见提示）；reindexing → indexed_at 有值且与
    now（缺省当前 UTC）差 > REINDEXING_TIMEOUT → "stale"（崩溃后防永久
    卡死），否则（无 indexed_at 或未超时）→ "reindexing"。⚠️ 父侧修正
    （2026-08-12）：签名补 indexed_at 参数——reindexing 超时判定必须
    显式携带 indexed_at（原签名仅 (status, now) 无法区分进行中/过期，
    两用例断言冲突）

设计依据: design/qa-rag-consistency-report.md §2.1（指纹内容与幂等性）/
§2.3（状态机与超时阈值）/ §3.3（schema_version 前向检查）;
Issue #276 范围 2。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from inkflow.domain.models.vector_fingerprint import (
    SCHEMA_VERSION,
    ChunkingFingerprint,
    EmbeddingFingerprint,
    VectorFingerprint,
)
from inkflow.domain.services.vector_fingerprint import (
    build_fingerprint,
    compare_fingerprints,
    fingerprint_from_json,
    fingerprint_to_json,
    normalize_status,
)


def _embedding(**overrides: object) -> dict:
    """构造 embedding 配置 dict（build_fingerprint 输入形态）。"""
    defaults: dict[str, object] = {
        "provider": "openai",
        "model_id": "text-embedding-3-small",
        "base_url": "https://api.test.example/v1",
    }
    defaults.update(overrides)
    return defaults


def _chunking(**overrides: object) -> dict:
    """构造 chunking 配置 dict（build_fingerprint 输入形态）。"""
    defaults: dict[str, object] = {
        "mode": "fixed",
        "chunk_size": 500,
        "overlap_ratio": 0.0,
        "chunker_version": 1,
    }
    defaults.update(overrides)
    return defaults


# ── 契约 6: 确定性 + base_url 归一化 ──────────────────────────────


def test_build_fingerprint_is_deterministic() -> None:
    """契约6: 同配置两次生成指纹逐字段完全一致（字段序固定、幂等）。"""
    emb = _embedding()
    chunk = _chunking()
    fp1 = build_fingerprint(emb, chunk, dimension=384)
    fp2 = build_fingerprint(emb, chunk, dimension=384)
    assert fp1 == fp2
    assert fp1.schema_version == fp2.schema_version
    assert fp1.embedding == fp2.embedding
    assert fp1.chunking == fp2.chunking
    assert fp1.indexed_at == fp2.indexed_at
    assert fp1.status == fp2.status


def test_build_fingerprint_normalizes_base_url_trailing_slash() -> None:
    """契约6: base_url 归一化——尾部斜杠去除，同端点不同写法指纹一致。"""
    fp_with = build_fingerprint(
        _embedding(base_url="https://api.test.example/v1/"),
        _chunking(),
        dimension=384,
    )
    fp_without = build_fingerprint(
        _embedding(base_url="https://api.test.example/v1"),
        _chunking(),
        dimension=384,
    )
    assert fp_with.embedding.base_url == "https://api.test.example/v1"
    assert fp_with == fp_without


def test_build_fingerprint_fills_default_chunking_keys() -> None:
    """契约6: chunking 缺省键补默认值；dimension 参数 None → embedding.dimension None。"""
    fp = build_fingerprint(_embedding(), {}, dimension=None)
    assert fp.chunking.mode == "fixed"
    assert fp.chunking.chunk_size == 500
    assert fp.chunking.overlap_ratio == 0.0
    # #278 M4 升级: CHUNKER_VERSION 1→2（对话/LLM 真规则算法改版，spec §5.6.5）
    assert fp.chunking.chunker_version == 2
    assert fp.embedding.dimension is None
    assert fp.schema_version == 1
    assert fp.status == "fresh"


# ── 契约 7: 敏感性 ────────────────────────────────────────────────


def test_fingerprint_sensitive_to_model_id() -> None:
    """契约7: model_id 变更 → 指纹不同（换模型必须触发 stale）。"""
    fp_a = build_fingerprint(_embedding(model_id="text-embedding-3-small"), _chunking())
    fp_b = build_fingerprint(_embedding(model_id="text-embedding-3-large"), _chunking())
    assert fp_a != fp_b
    assert fp_a.embedding.model_id != fp_b.embedding.model_id


def test_fingerprint_sensitive_to_base_url() -> None:
    """契约7: base_url 变更 → 指纹不同（同模型不同服务商向量空间不同）。"""
    fp_a = build_fingerprint(_embedding(), _chunking())
    fp_b = build_fingerprint(
        _embedding(base_url="https://other.example.com/v1"),
        _chunking(),
    )
    assert fp_a != fp_b


def test_fingerprint_sensitive_to_dimension() -> None:
    """契约7: dimension 变更 → 指纹不同（维度不匹配独立可判）。"""
    fp_384 = build_fingerprint(_embedding(), _chunking(), dimension=384)
    fp_768 = build_fingerprint(_embedding(), _chunking(), dimension=768)
    assert fp_384 != fp_768


def test_fingerprint_sensitive_to_chunking_mode() -> None:
    """契约7: chunking.mode 变更 → 指纹不同。"""
    fp_fixed = build_fingerprint(_embedding(), _chunking(mode="fixed"))
    fp_para = build_fingerprint(_embedding(), _chunking(mode="paragraph"))
    assert fp_fixed != fp_para


def test_fingerprint_sensitive_to_chunker_version() -> None:
    """契约7: chunker_version bump → 指纹不同（切片算法改版手动 +1）。"""
    fp_v1 = build_fingerprint(_embedding(), _chunking(chunker_version=1))
    fp_v2 = build_fingerprint(_embedding(), _chunking(chunker_version=2))
    assert fp_v1 != fp_v2


# ── 契约 8: 序列化 roundtrip ──────────────────────────────────────


def test_fingerprint_json_roundtrip_preserves_all_fields() -> None:
    """契约8: dict → JSON → dict 无损（fingerprint_to_json/from_json 往返相等）。"""
    fp = build_fingerprint(
        _embedding(),
        _chunking(),
        dimension=384,
        indexed_at="2026-08-12T08:00:00Z",
        status="fresh",
    )
    raw = fingerprint_to_json(fp)
    restored = fingerprint_from_json(raw)
    assert restored == fp
    assert restored.embedding == fp.embedding
    assert restored.chunking == fp.chunking
    assert restored.indexed_at == fp.indexed_at
    assert restored.status == fp.status


def test_fingerprint_json_roundtrip_with_null_dimension() -> None:
    """契约8: dimension=None（未 embed 过）序列化往返不丢 None。"""
    fp = build_fingerprint(_embedding(), _chunking(), dimension=None)
    restored = fingerprint_from_json(fingerprint_to_json(fp))
    assert restored.embedding.dimension is None


# ── 契约 9: 状态机 ────────────────────────────────────────────────


def test_normalize_status_unknown_is_stale() -> None:
    """契约9: unknown（无指纹）视同 stale——存量用户升级后首次即见提示。"""
    assert normalize_status("unknown") == "stale"


def test_normalize_status_fresh_and_stale_pass_through() -> None:
    """契约9: fresh/stale 原样透传。"""
    assert normalize_status("fresh") == "fresh"
    assert normalize_status("stale") == "stale"


async def test_normalize_status_unknown_status_passthrough() -> None:
    """契约8补充: 未知状态值直接返回（兜底分支——coverage 补强 2026-08-12）。"""
    assert normalize_status("weird-status") == "weird-status"
    assert normalize_status("fresh") == "fresh"
    assert normalize_status("stale") == "stale"


def test_normalize_status_reindexing_within_timeout_keeps_reindexing() -> None:
    """契约9: reindexing 未超时（< 24h）保持 reindexing（进行中）。"""
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)
    recent = (now - timedelta(hours=1)).isoformat()
    # 无 indexed_at 信息 → 视为进行中（不误判过期）
    assert normalize_status("reindexing", now=now) == "reindexing"
    assert normalize_status("reindexing", now=now) == normalize_status("reindexing")
    # indexed_at 存在且距今 < 24h → reindexing
    fp = build_fingerprint(_embedding(), _chunking(), indexed_at=recent, status="reindexing")
    assert normalize_status(fp.status, now=now, indexed_at=fp.indexed_at) == "reindexing"


def test_normalize_status_reindexing_timed_out_becomes_stale() -> None:
    """契约9: reindexing 超时（≥ 24h，崩溃/失败残留）→ stale 防永久卡死。"""
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)
    stale_at = (now - timedelta(hours=25)).isoformat()
    fp = build_fingerprint(_embedding(), _chunking(), indexed_at=stale_at, status="reindexing")
    assert normalize_status(fp.status, now=now, indexed_at=fp.indexed_at) == "stale"


# ── 契约 9（续）: compare 比对 ────────────────────────────────────


def test_compare_fingerprints_none_indexed_is_unknown() -> None:
    """契约9: indexed 为 None（无指纹）→ stale=True + reason="unknown"。"""
    configured = build_fingerprint(_embedding(), _chunking())
    stale, reason = compare_fingerprints(configured, None)
    assert stale is True
    assert reason == "unknown"


def test_compare_fingerprints_identical_is_fresh() -> None:
    """契约9: 指纹一致 → stale=False + reason=None（fresh）。"""
    configured = build_fingerprint(_embedding(), _chunking(), dimension=384)
    indexed = build_fingerprint(_embedding(), _chunking(), dimension=384)
    stale, reason = compare_fingerprints(configured, indexed)
    assert stale is False
    assert reason is None


def test_compare_fingerprints_model_changed() -> None:
    """契约9: model_id 变更 → stale=True + reason="model_changed"。"""
    configured = build_fingerprint(_embedding(model_id="text-embedding-3-large"), _chunking())
    indexed = build_fingerprint(_embedding(model_id="text-embedding-3-small"), _chunking())
    stale, reason = compare_fingerprints(configured, indexed)
    assert stale is True
    assert reason == "model_changed"


def test_compare_fingerprints_base_url_changed_is_model_changed() -> None:
    """契约9: base_url 变更归入 model_changed（模型服务端点 = 模型身份一部分）。"""
    configured = build_fingerprint(_embedding(base_url="https://new.example.com/v1"), _chunking())
    indexed = build_fingerprint(_embedding(), _chunking())
    stale, reason = compare_fingerprints(configured, indexed)
    assert stale is True
    assert reason == "model_changed"


def test_compare_fingerprints_chunking_changed() -> None:
    """契约9: chunking 参数变更 → stale=True + reason="chunking_changed"。"""
    configured = build_fingerprint(_embedding(), _chunking(chunk_size=300))
    indexed = build_fingerprint(_embedding(), _chunking())
    stale, reason = compare_fingerprints(configured, indexed)
    assert stale is True
    assert reason == "chunking_changed"


def test_compare_fingerprints_schema_old() -> None:
    """契约9: indexed.schema_version 低于当前 → stale=True + reason="schema_old"。"""
    configured = build_fingerprint(_embedding(), _chunking(), schema_version=1)
    indexed = build_fingerprint(_embedding(), _chunking(), schema_version=0)
    stale, reason = compare_fingerprints(configured, indexed)
    assert stale is True
    assert reason == "schema_old"


def test_compare_fingerprints_schema_old_takes_priority() -> None:
    """契约9: schema 旧 + 模型也变 → reason 报 schema_old（优先级最高）。"""
    configured = build_fingerprint(_embedding(model_id="new-model"), _chunking(), schema_version=1)
    indexed = build_fingerprint(_embedding(model_id="old-model"), _chunking(), schema_version=0)
    stale, reason = compare_fingerprints(configured, indexed)
    assert stale is True
    assert reason == "schema_old"


def test_compare_fingerprints_dimension_not_compared() -> None:
    """契约9: dimension 不参与比对——同模型维度差异由装配层单独判 mismatch。"""
    configured = build_fingerprint(_embedding(), _chunking(), dimension=768)
    indexed = build_fingerprint(_embedding(), _chunking(), dimension=384)
    stale, reason = compare_fingerprints(configured, indexed)
    assert stale is False
    assert reason is None


# ── 契约辅助: 数据模型字段契约（docstring 钉死的签名落地检查）──


def test_fingerprint_model_field_shapes() -> None:
    """数据模型字段形态：嵌套 EmbeddingFingerprint/ChunkingFingerprint 可独立构造。"""
    emb = EmbeddingFingerprint(
        provider="openai", model_id="m", base_url="https://x/v1", dimension=384
    )
    chunk = ChunkingFingerprint(mode="fixed", chunk_size=500, overlap_ratio=0.0, chunker_version=1)
    fp = VectorFingerprint(schema_version=1, embedding=emb, chunking=chunk)
    assert fp.embedding.dimension == 384
    assert fp.chunking.mode == "fixed"
    assert SCHEMA_VERSION >= 1  # 当前 schema 版本号存在且 ≥ 1
