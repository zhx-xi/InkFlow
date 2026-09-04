"""RAG 向量指纹领域模型 — 索引配置指纹快照与状态机（#276 G1）.

VectorFingerprint 是 embedding 配置 + chunking 配置的规范化快照:
- 用于「索引是否过期」的确定性判定（compare_fingerprints 纯函数消费）;
- 字段声明序固定，保证序列化幂等（fingerprint_to_json 直接依赖声明序）;
- status 状态机: fresh / stale / unknown / reindexing（unknown 视同 stale）.

依据: design/qa-rag-consistency-report.md §2.1（指纹内容与幂等性）/
§2.3（状态机与超时阈值）/ §3.3（schema_version 前向检查）; Issue #276 范围 2。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel

SCHEMA_VERSION = 1
CHUNKER_VERSION = 2
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_MODE = "fixed"
DEFAULT_OVERLAP_RATIO = 0.0
REINDEXING_TIMEOUT = timedelta(hours=24)


class VectorFingerprintStatus(StrEnum):
    """索引指纹状态机成员（成员值 = 名称小写）.

    Attributes:
        FRESH: 索引与当前配置一致.
        STALE: 配置变更 / 超时 / 无指纹，需要重索引.
        UNKNOWN: 无指纹记录（视同 stale）.
        REINDEXING: 重索引进行中（超时 24h 自动视为 stale）.
    """

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    REINDEXING = "reindexing"


class EmbeddingFingerprint(BaseModel):
    """embedding 配置指纹（比对键: model_id / base_url; dimension 不参与比对）.

    Attributes:
        provider: 提供商名（如 openai / zhipu / ollama）.
        model_id: 模型 ID（同模型不同 base_url 向量空间不同，均参与比对）.
        base_url: OpenAI 兼容端点（已归一化去尾部斜杠）.
        dimension: 向量维度（None = 未 embed 过；由装配层单独判 mismatch）.
    """

    provider: str
    model_id: str
    base_url: str
    dimension: int | None = None


class ChunkingFingerprint(BaseModel):
    """chunking 配置指纹（全部字段参与比对）.

    Attributes:
        mode: 切片模式（fixed / paragraph ...）.
        chunk_size: 切片大小（字符数）.
        overlap_ratio: 重叠比例（固定切片模式生效）.
        chunker_version: 切片算法版本（改版手动 +1，强制触发 stale）.
    """

    mode: str
    chunk_size: int
    overlap_ratio: float
    chunker_version: int


class VectorFingerprint(BaseModel):
    """索引配置指纹快照（字段声明序 = 序列化字段序）.

    Attributes:
        schema_version: 指纹 schema 版本（前向检查用，见 SCHEMA_VERSION）.
        embedding: embedding 配置指纹.
        chunking: chunking 配置指纹.
        indexed_at: 最近一次索引时间（ISO 8601 字符串，可空）.
        status: 状态机值（fresh/stale/unknown/reindexing）.
    """

    schema_version: int
    embedding: EmbeddingFingerprint
    chunking: ChunkingFingerprint
    indexed_at: str | None = None
    status: str = "fresh"
