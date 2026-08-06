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


async def test_get_vector_store_without_embedding_model_raises() -> None:
    """E1: repo.list() 无任何 provider → get_vector_store 抛 RAGUnavailableError。

    消息含「未配置 embedding 模型」（500 RAG 前缀语义，spec §5.5 B1 边界）。
    """
    # Arrange: 空注册表（B1 边界：无任何 provider）
    repo = _repo_with_providers([])

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


async def test_get_vector_store_ignores_chat_only_models() -> None:
    """E4: 仅有 chat 类型模型（无 embedding 条目）不被消费 → 仍抛 RAGUnavailableError。"""
    # Arrange: 注册表只有 chat 模型（B6 边界：内置 provider 无 embedding）
    chat_only = ProviderConfig(
        name="openai",
        builtin_key="openai",
        base_url="https://api.test.example/v1",
        models=[ProviderModel(id="gpt-4o", type="chat")],
    )
    repo = _repo_with_providers([chat_only])

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


# ── E2: 配置 embedding 模型 → OpenAIEmbeddings 透传 ───────────────


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
