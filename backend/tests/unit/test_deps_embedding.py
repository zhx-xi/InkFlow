"""F19 B+ 装配改造：get_vector_store API embedding 契约测试（spec §5.3 E1-E4）。

依据: specs/f19-packaging/spec.md §5.2（async 装配链决策 🔴3）/ §5.3（E1-E4
契约表）/ §5.4（选型规则与数据源）/ §5.5（边界表 B1-B6）。

契约（RED 先行，Codex GREEN 按此实现）:
- E1 未配置 embedding 模型 → get_vector_store() 抛 RAGUnavailableError
  （消息含「未配置 embedding 模型」）
- E2 配置 embedding 模型 → 构造 OpenAIEmbeddings（model/base_url/api_key 透传，
  api_key 来自 APIKeyManager.load(provider.name) 返回值）
- E3 已配置 → get_vector_store() 正常返回 store（懒加载单例：两次调用同一对象）
- E4 仅有 chat 类型模型（无 embedding）不被消费 → 仍抛 RAGUnavailableError

注入点（spec §5.4 数据源，已核实）:
- SQLiteProviderConfigRepository（provider_config_repo 模块；deps.py 顶部已
  import 到模块命名空间）——mock repo.list() 返回 ProviderConfig 列表
- APIKeyManager.load（key_manager 模块，实例方法）——mock 返回值即 api_key
- LangChainVectorStore（langchain_vector_store 模块）——patch 构造避免真实
  chroma 持久化 I/O（test_api_deps.py 同款先例）
- OpenAIEmbeddings 不 mock：装配层只构造对象、不发网络请求（spec §5.3 无
  网络约束），断言真实实例属性（model / openai_api_base / openai_api_key）

测试形态: async def + pytest-asyncio（pyproject asyncio_mode="auto"，
tests/unit/ 既有 async 测试同款），直接 await 装配函数断言。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_openai import OpenAIEmbeddings

from inkflow.api import deps
from inkflow.core.config import config
from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
from inkflow.domain.ports.extraction_errors import RAGUnavailableError
from inkflow.infrastructure.llm.key_manager import APIKeyManager


def _repo_with_providers(providers: list[ProviderConfig]) -> MagicMock:
    """构造 mock 仓储（ProviderConfigRepositoryProtocol 形状）：list() 返回给定 providers。"""
    repo = MagicMock()
    repo.list = AsyncMock(return_value=providers)
    return repo


def _embedding_provider() -> ProviderConfig:
    """含 embedding 模型的 provider（spec §5.2 示意形态：base_url + embedding 条目）。"""
    return ProviderConfig(
        name="openai",
        builtin_key="openai",
        base_url="https://api.test.example/v1",
        models=[ProviderModel(id="text-embedding-3-small", type="embedding")],
    )


@pytest.fixture(autouse=True)
def _reset_vector_store_singleton() -> None:
    """每个用例前后重置 deps._vector_store 模块级单例，隔离懒加载状态（test_api_deps.py 同款）。"""
    original = deps._vector_store
    deps._vector_store = None
    yield
    deps._vector_store = original


# ── E1: 未配置 embedding 模型 → RAGUnavailableError ───────────────


async def test_get_vector_store_without_embedding_model_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E1: 注册表无 embedding 且无本地 BGE 兜底 → get_vector_store 抛 RAGUnavailableError。

    #276 契约升级（用户拍板 2026-08-12）：config.embedding_model 本地 BGE
    保留为「未配置 API embedding」时的离线 fallback——本用例显式清空
    config.embedding_model 后语义与 E1 原始契约一致（消息含
    「未配置 embedding 模型」，500 RAG 前缀语义，spec §5.5 B1 边界）。
    """
    # Arrange: 空注册表（B1 边界：无任何 provider）+ 无本地 BGE fallback
    repo = _repo_with_providers([])
    monkeypatch.setattr(config, "embedding_model", "")

    # Act & Assert: 抛 RAGUnavailableError（500 RAG 前缀语义）
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        pytest.raises(RAGUnavailableError, match="未配置 embedding 模型"),
    ):
        await deps.get_vector_store()

    # 装配确实查询了注册表（而非静默跳过）
    repo.list.assert_awaited_once()
    # 初始化失败后单例保持 None（下次调用可重试，同 test_api_deps.py 先例）
    assert deps._vector_store is None


# ── E4: chat 类型模型不被消费 → 仍报 E1 ───────────────────────────


async def test_get_vector_store_ignores_chat_only_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E4: 仅有 chat 类型模型（无 embedding 条目）不被消费 → 走 BGE fallback 语义。

    #276 契约升级：chat-only 注册表不构成「API embedding 已配置」——
    显式清空 config.embedding_model 后仍抛 RAGUnavailableError（B6 边界：
    内置 provider 无 embedding 不被消费）。
    """
    # Arrange: 注册表只有 chat 模型（B6 边界：内置 provider 无 embedding）+ 无 BGE
    chat_only = ProviderConfig(
        name="openai",
        builtin_key="openai",
        base_url="https://api.test.example/v1",
        models=[ProviderModel(id="gpt-4o", type="chat")],
    )
    repo = _repo_with_providers([chat_only])
    monkeypatch.setattr(config, "embedding_model", "")

    # Act & Assert: 选型规则只认 type="embedding"，chat 模型不参与装配
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        pytest.raises(RAGUnavailableError, match="未配置 embedding 模型"),
    ):
        await deps.get_vector_store()

    repo.list.assert_awaited_once()


# ── E1-upgrade 移除: 本地 BGE fallback（#330 拍板 D1=b）────────────


async def test_get_vector_store_without_embedding_raises_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#330 RED: 注册表空 + config.embedding_model 有值（旧默认非空）→ 抛「未配置」。

    D1=b 拍板（2026-08-13）：移除本地 BGE fallback——0.8.0 主路径 = API
    embedding；「未配置 embedding」必须明确报错，不得静默回退 local
    （打包版无 torch/sentence-transformers，fallback 必 500）。
    RED 形态：当前实现走 local fallback 返回 store → pytest.raises FAIL。
    """
    # Arrange: 空注册表 + embedding_model 保持默认非空（旧 fallback 触发条件）
    repo = _repo_with_providers([])
    monkeypatch.setattr(config, "embedding_model", "BAAI/bge-small-zh-v1.5")
    fake_bge = MagicMock()

    # Act & Assert: 未配置 embedding → 必须抛「未配置」（非返回 local store）
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch(
            "langchain_community.embeddings.HuggingFaceBgeEmbeddings",
            return_value=fake_bge,
        ),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=MagicMock(),
        ),
        pytest.raises(RAGUnavailableError, match="未配置 embedding 模型"),
    ):
        await deps.get_vector_store()

    repo.list.assert_awaited_once()
    assert deps._vector_store is None


async def test_get_vector_store_bge_fallback_removed_raises_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#330 RED: 注册表空 + embedding_model 非空 → 抛「未配置」（错误消息不得是
    「RAG 向量库不可用」——旧 fallback 构造失败路径已删除）."""
    # Arrange: 空注册表 + embedding_model 有值（触发旧 local 分支）
    repo = _repo_with_providers([])
    monkeypatch.setattr(config, "embedding_model", "BAAI/bge-large-zh-v1.5")

    # Act & Assert: 未配置 → RAGUnavailableError 消息含「未配置 embedding 模型」
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        pytest.raises(RAGUnavailableError, match="未配置 embedding 模型"),
    ):
        await deps.get_vector_store()

    assert deps._vector_store is None


async def test_get_vector_store_constructs_openai_embeddings() -> None:
    """E2: 配置 embedding 模型 → OpenAIEmbeddings 收到 model/base_url。

    api_key 来自 APIKeyManager.load(provider.name)（spec §5.4 选型规则）。
    """
    # Arrange: 注册表含 embedding 模型 provider
    provider = _embedding_provider()
    repo = _repo_with_providers([provider])
    fake_store = MagicMock()

    # Act: 装配 get_vector_store（LangChainVectorStore patch 避免真实 chroma I/O）
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123") as mock_load,
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=fake_store,
        ) as mock_vs,
    ):
        store = await deps.get_vector_store()

    # Assert: store 正常返回；key 按 provider.name 读取
    assert store is fake_store
    mock_load.assert_called_once_with("openai")

    # Assert: OpenAIEmbeddings 构造参数透传（真实实例属性，非内部状态）
    call = mock_vs.call_args
    embeddings = call.kwargs.get("embeddings") or call.args[1]
    assert isinstance(embeddings, OpenAIEmbeddings)
    assert embeddings.model == "text-embedding-3-small"
    assert embeddings.openai_api_base == "https://api.test.example/v1"
    assert embeddings.openai_api_key.get_secret_value() == "sk-test-123"


# ── E3: 懒加载单例 ───────────────────────────────────────────────


async def test_get_vector_store_lazy_singleton_returns_same_store() -> None:
    """E3: 已配置 → 两次调用返回同一 store 实例（懒加载单例，LangChainVectorStore 仅构造一次）。"""
    # Arrange: 注册表含 embedding 模型 provider
    repo = _repo_with_providers([_embedding_provider()])
    fake_store = MagicMock()

    # Act: 连续两次装配
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123"),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=fake_store,
        ) as mock_vs,
    ):
        first = await deps.get_vector_store()
        second = await deps.get_vector_store()

    # Assert: 同一实例；底层 store 仅构造一次（懒加载语义不变，spec §5.2）
    assert first is fake_store
    assert second is fake_store
    assert first is second
    mock_vs.assert_called_once()


# ── E5: refresh_vector_store 单例刷新（#276 契约 14，QA 报告 §4.1-D）──
# 新增 deps 函数: refresh_vector_store() -> VectorStoreProtocol
# —— 用当前配置重建 store；成功 → 原子替换 deps._vector_store 并返回新实例；
# 失败 → 保留旧实例 + RAGUnavailableError 上抛（不允许半替换/静默回退）。
# RED 形态: refresh_vector_store 不存在 → AttributeError，新用例 FAIL。


async def test_refresh_vector_store_replaces_singleton() -> None:
    """E5: 配置变更后 refresh → 返回新实例且 deps._vector_store 已替换。

    核心断言: refresh 返回的实例与旧单例不同（is 不相等），且模块级
    _vector_store 指向新实例——reindex 前刷新后必然用新模型。
    """
    # Arrange: 两次构造返回不同 store（第一次懒加载旧、第二次刷新新）
    repo = _repo_with_providers([_embedding_provider()])
    old_store, new_store = MagicMock(), MagicMock()

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123"),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            side_effect=[old_store, new_store],
        ) as mock_vs,
    ):
        first = await deps.get_vector_store()
        assert first is old_store

        # Act: 刷新单例（重新走选型 + 构造）
        refreshed = await deps.refresh_vector_store()

    # Assert: 新实例已替换模块级单例；底层构造了两次
    assert refreshed is new_store
    assert deps._vector_store is new_store
    assert mock_vs.call_count == 2


async def test_refresh_vector_store_failure_keeps_old_singleton() -> None:
    """E5: 刷新失败（构造抛错）→ 保留旧实例 + RAGUnavailableError 上抛。

    防「重新向量化按钮用旧模型重写旧向量」假成功（P0-2）——失败必须
    中止 reindex，不允许静默回退旧实例。
    """
    # Arrange: 首次构造成功（旧单例），刷新时构造抛错
    repo = _repo_with_providers([_embedding_provider()])
    old_store = MagicMock()

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123"),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            side_effect=[old_store, RuntimeError("embedding load failed")],
        ),
    ):
        first = await deps.get_vector_store()
        assert first is old_store

        # Act & Assert: 刷新失败 → RAGUnavailableError（RAG 向量库不可用前缀）
        with pytest.raises(RAGUnavailableError, match="RAG 向量库不可用"):
            await deps.refresh_vector_store()

    # Assert: 单例仍为旧实例（未半替换）
    assert deps._vector_store is old_store


# ── E6: get_vector_status 状态接线（#276 契约 15，QA 报告 §4.1-D）──
# 新增 deps 函数: get_vector_status(project_id: str) -> dict
# —— 返回 {configured_fp: dict|None, indexed_fp: dict|None, stale: bool,
# reason: str|None, dimension_mismatch: bool}：
#   * 未配置 embedding → 200 语义 {configured_fp: None, indexed_fp: None,
#     stale: False, reason: "no_embedding", dimension_mismatch: False}
#   * configured_fp.dimension 来自 store.embedding_dimension（运行时实测，
#     未 embed 过 = None）；indexed_fp 来自 store.read_fingerprint
#   * stale/reason 由 compare_fingerprints（dimension 不参与比对）
#   * dimension_mismatch = configured.dimension 已知 且 indexed.dimension
#     存在且不同（独立字段，GUI「维度不兼容」文案）
# RED 形态: get_vector_status 不存在 → AttributeError，新用例 FAIL。


async def test_get_vector_status_no_fingerprint_is_unknown() -> None:
    """E6: 无指纹（存量用户升级）→ stale=True + reason="unknown"。"""
    repo = _repo_with_providers([_embedding_provider()])
    fake_store = MagicMock()
    fake_store.read_fingerprint = AsyncMock(return_value=None)
    fake_store.probe_collection_dimension = AsyncMock(return_value=0)
    fake_store.embedding_dimension = 384

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123"),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=fake_store,
        ),
    ):
        status = await deps.get_vector_status("p1")

    assert status["stale"] is True
    assert status["reason"] == "unknown"
    assert status["dimension_mismatch"] is False
    assert status["indexed_fp"] is None
    assert status["configured_fp"] is not None
    assert status["configured_fp"]["embedding"]["model_id"] == "text-embedding-3-small"


async def test_get_vector_status_fresh_when_fingerprint_matches() -> None:
    """E6: 指纹一致 → stale=False + reason=None（fresh，GUI 绿色匹配态）。"""
    repo = _repo_with_providers([_embedding_provider()])
    fake_store = MagicMock()
    fake_store.embedding_dimension = 384
    fake_store.read_fingerprint = AsyncMock(
        return_value={
            "schema_version": 1,
            "embedding": {
                "provider": "openai",
                "model_id": "text-embedding-3-small",
                "base_url": "https://api.test.example/v1",
                "dimension": 384,
            },
            "chunking": {
                "mode": "fixed",
                "chunk_size": 500,
                "overlap_ratio": 0.0,
                "chunker_version": 1,
            },
            "indexed_at": "2026-08-12T08:00:00Z",
            "status": "fresh",
        }
    )

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123"),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=fake_store,
        ),
    ):
        status = await deps.get_vector_status("p1")

    assert status["stale"] is False
    assert status["reason"] is None
    assert status["dimension_mismatch"] is False
    assert status["indexed_fp"]["status"] == "fresh"


async def test_get_vector_status_dimension_mismatch_independent() -> None:
    """E6: 同模型但维度不同 → dimension_mismatch=True（compare 不含维度的独立判据）。"""
    repo = _repo_with_providers([_embedding_provider()])
    fake_store = MagicMock()
    fake_store.embedding_dimension = 768  # 当前模型实测维度（配置侧）
    fake_store.read_fingerprint = AsyncMock(
        return_value={
            "schema_version": 1,
            "embedding": {
                "provider": "openai",
                "model_id": "text-embedding-3-small",
                "base_url": "https://api.test.example/v1",
                "dimension": 384,  # 已索引指纹记录 384
            },
            "chunking": {
                "mode": "fixed",
                "chunk_size": 500,
                "overlap_ratio": 0.0,
                "chunker_version": 1,
            },
            "indexed_at": "2026-08-12T08:00:00Z",
            "status": "fresh",
        }
    )

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123"),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=fake_store,
        ),
    ):
        status = await deps.get_vector_status("p1")

    assert status["dimension_mismatch"] is True
    # dimension 不参与 stale 比对（同模型同端点）→ 不误报 stale
    assert status["stale"] is False


async def test_get_vector_status_no_embedding_configured() -> None:
    """E6: 未配置任何 embedding → 200 语义 no_embedding（不抛错，GUI 显示未配置态）。"""
    repo = _repo_with_providers([])

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch(
            "langchain_community.embeddings.HuggingFaceBgeEmbeddings",
            side_effect=RuntimeError("no local model"),
        ),
    ):
        status = await deps.get_vector_status("p1")

    assert status["configured_fp"] is None
    assert status["indexed_fp"] is None
    assert status["stale"] is False
    assert status["reason"] == "no_embedding"
    assert status["dimension_mismatch"] is False


async def test_get_extraction_service_fingerprint_provider_passes_dimension() -> None:
    """E7: get_extraction_service 注入的 fingerprint_provider 透传 store 实测维度。

    coverage 补强（2026-08-12）：deps.py 523-528 _fingerprint_provider 闭包。
    """
    repo = _repo_with_providers([_embedding_provider()])
    fake_store = MagicMock()
    fake_store.embedding_dimension = 768

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch.object(APIKeyManager, "load", return_value="sk-test-123"),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=fake_store,
        ),
    ):
        svc = await deps.get_extraction_service(MagicMock())
        fp = await svc._fingerprint_provider()  # type: ignore[attr-defined]  # 测试直接调用注入闭包

    assert fp is not None
    assert fp["embedding"]["dimension"] == 768
    assert fp["embedding"]["model_id"] == "text-embedding-3-small"
    assert fp["embedding"]["base_url"] == "https://api.test.example/v1"


async def test_build_configured_fingerprint_returns_none_without_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E8: 无 embedding 配置（repo 空 + config.embedding_model 空）→ None（不抛）。

    coverage 补强（2026-08-12）：deps.py 789-790 RAGUnavailableError → None。
    build_configured_fingerprint 只 resolve 选型（不构造 embeddings）——
    resolve 抛错路径 = 注册表无 embedding 且 config.embedding_model 为空。
    """
    repo = _repo_with_providers([])
    from inkflow.core.config import config as core_config

    monkeypatch.setattr(core_config, "embedding_model", "")

    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
    ):
        fp = await deps.build_configured_fingerprint(dimension=None)

    assert fp is None
