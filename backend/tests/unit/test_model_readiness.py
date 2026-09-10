"""F60 首启模型就绪判据单元测试（RED 契约 — #934 §2.1/§9.1）。

被测：`inkflow.domain.services.model_readiness.compute_readiness` — 纯函数，
零 I/O，判定「是否已具备可解析 chat 模型 + 有效 key」。

判据（spec §2.1，唯一真相）：
    存在 provider 同时满足
      (1) provider.name ∈ saved_provider_names（key_saved 语义）
      (2) 该 provider.models 中至少一个 type == "chat"

RED：模块尚不存在 → import 失败（预期）。

契约来源：specs/f60-first-run-guide/spec.md §2.1 / §3.1 / §9.1
"""

from __future__ import annotations

from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
from inkflow.domain.services.model_readiness import compute_readiness

# ---------------------------------------------------------------------------
# 构造器：仅填判据相关字段（id/时间戳与判据无关）
# ---------------------------------------------------------------------------


def _pc(name: str, models: list[ProviderModel]) -> ProviderConfig:
    """构造一个 ProviderConfig（判据只读 name + models[].type）。"""
    return ProviderConfig(id=1, name=name, models=models)


def _chat(model_id: str = "gpt-4o") -> ProviderModel:
    return ProviderModel(id=model_id, type="chat")


def _embedding(model_id: str = "embedding-3") -> ProviderModel:
    return ProviderModel(id=model_id, type="embedding")


# ---------------------------------------------------------------------------
# 空注册表 → no_provider（N1 真·全新安装）
# ---------------------------------------------------------------------------


def test_empty_registry_not_ready_no_provider() -> None:
    """空注册表 → ready=False, reason='no_provider'（真·全新安装）。"""
    result = compute_readiness([], set())
    assert result.ready is False
    assert result.reason == "no_provider"
    assert result.has_chat_model is False
    assert result.has_embedding_model is False


def test_provider_registered_without_key_still_no_key() -> None:
    """有 provider 含 chat 模型但无 key → no_key（#821 空 key 守卫语义）。"""
    result = compute_readiness([_pc("openai", [_chat()])], set())
    assert result.ready is False
    assert result.reason == "no_key"
    assert result.has_chat_model is False  # 无 key 不算「可用 chat 模型」


# ---------------------------------------------------------------------------
# #929 精确缺陷形态：只有 embedding 模型（有 key）→ 必须不 ready
# ---------------------------------------------------------------------------


def test_only_embedding_model_with_key_not_ready_929_regression() -> None:
    """#929 回归锚：唯一 provider 只配 embedding 模型 + 有 key → ready=False。

    这是 zhipu embedding-3 被当 chat 装配的精确配置形态——判据必须显式筛 type。
    """
    result = compute_readiness([_pc("zhipu", [_embedding("embedding-3")])], {"zhipu"})
    assert result.ready is False
    assert result.reason == "no_chat_model"
    assert result.has_chat_model is False
    assert result.has_embedding_model is True  # embedding 侧仍可见（RAG 可用）


# ---------------------------------------------------------------------------
# 就绪正路径
# ---------------------------------------------------------------------------


def test_chat_model_with_key_is_ready() -> None:
    """有 chat 模型 + key → ready=True, reason='ready'。"""
    result = compute_readiness([_pc("deepseek", [_chat("deepseek-chat")])], {"deepseek"})
    assert result.ready is True
    assert result.reason == "ready"
    assert result.has_chat_model is True


def test_ready_implies_reason_ready() -> None:
    """ready=True ⟺ reason='ready'（不变量，GUI 按 reason 定位起始步骤）。"""
    result = compute_readiness([_pc("openai", [_chat()])], {"openai"})
    assert result.ready is (result.reason == "ready")


# ---------------------------------------------------------------------------
# 多 provider 混合：存在即就绪
# ---------------------------------------------------------------------------


def test_mixed_providers_one_complete_is_ready() -> None:
    """多 provider 混合——只要一个满足全部条件即就绪。"""
    providers = [
        _pc("zhipu", [_embedding()]),  # 有 key 但只 embedding
        _pc("openai", [_chat()]),  # 无 key
        _pc("deepseek", [_chat("deepseek-chat")]),  # 有 key + chat ← 这条兜住
    ]
    result = compute_readiness(providers, {"zhipu", "deepseek"})
    assert result.ready is True
    assert result.reason == "ready"


def test_key_on_wrong_provider_does_not_help() -> None:
    """key 与 chat 模型必须在同一 provider 上才算就绪（跨 provider 不串用）。"""
    providers = [
        _pc("openai", [_chat()]),  # 有 chat 无 key
        _pc("zhipu", [_embedding()]),  # 有 key 无 chat
    ]
    result = compute_readiness(providers, {"zhipu"})
    assert result.ready is False
    assert result.reason == "no_key"


# ---------------------------------------------------------------------------
# has_embedding_model 独立判定
# ---------------------------------------------------------------------------


def test_has_embedding_model_independent_of_chat() -> None:
    """embedding 存在性与 chat 就绪性彼此独立（N2 / RAG 置灰判据）。"""
    # 有 chat + key（就绪），但无 embedding
    ready_no_embed = compute_readiness([_pc("deepseek", [_chat()])], {"deepseek"})
    assert ready_no_embed.ready is True
    assert ready_no_embed.has_embedding_model is False

    # 有 chat + embedding + key
    with_embed = compute_readiness(
        [_pc("deepseek", [_chat("deepseek-chat"), _embedding("embed-1")])],
        {"deepseek"},
    )
    assert with_embed.ready is True
    assert with_embed.has_embedding_model is True


def test_embedding_model_without_key_not_counted() -> None:
    """embedding 无 key → has_embedding_model=False（同 key_saved 语义）。"""
    result = compute_readiness([_pc("zhipu", [_embedding()])], set())
    assert result.has_embedding_model is False


# ---------------------------------------------------------------------------
# 防御：provider 无模型条目
# ---------------------------------------------------------------------------


def test_provider_with_no_models_not_ready() -> None:
    """provider 已注册 + 有 key 但 models 为空 → no_chat_model（防御）。"""
    result = compute_readiness([_pc("openai", [])], {"openai"})
    assert result.ready is False
    assert result.reason == "no_chat_model"


# ---------------------------------------------------------------------------
# reason 优先级：no_provider > no_chat_model > no_key
# ---------------------------------------------------------------------------


def test_reason_priority_no_chat_model_over_no_key() -> None:
    """reason 优先级：注册表**全无** chat 模型（不论 key）→ no_chat_model。

    语义：用户连模型都没配齐时，先引导配模型（步骤 1），而非先补 key。
    反例见下方 test_reason_priority_no_key_when_chat_exists_elsewhere。
    """
    providers = [
        _pc("zhipu", [_embedding()]),  # 有 key 无 chat
        _pc("openai", [_embedding("text-embedding-3")]),  # 无 key 也无 chat
    ]
    result = compute_readiness(providers, {"zhipu"})
    assert result.reason == "no_chat_model"


def test_reason_priority_no_key_when_chat_exists_elsewhere() -> None:
    """注册表**存在** chat 模型（但该 provider 无 key）→ no_key（不是 no_chat_model）。

    no_chat_model 判据 = 全注册表无任何 chat 条目，与 key 无关；只要某处
    配了 chat 模型，缺的是 key → 引导补 key。
    """
    providers = [
        _pc("zhipu", [_embedding()]),  # 有 key 无 chat
        _pc("openai", [_chat()]),  # 有 chat 无 key ← 决定 reason
    ]
    result = compute_readiness(providers, {"zhipu"})
    assert result.ready is False
    assert result.reason == "no_key"
