"""#962 F59-M1 LiteLLM 迁移批 RED 契约（spec §5.1/§9.1 单元层）。

契约（RED 先行，Codex GREEN 按此实现；spec 依据逐用例标注）：
- A. provider→litellm 前缀口径映射（spec §5.1「provider 名口径」）：
  `litellm_provider_prefix(provider, base_url) -> str`——zhipu→zai（litellm 1.99
  provider_list 含 zai 无 zhipu，实证）；deepseek/dashscope 原生同名；ollama 本地
  默认端点→ollama_chat、自定义 http base_url→openai（实证 ollama/ 走原生
  /api/generate 形态、ollama_chat/ 走 chat/completions、openai/ 同）；fake 与
  自定义 OpenAI 兼容 provider→openai。此表是前缀口径（非参数方言表，与
  ADR-051「零方言映射」不冲突）。
- B. langchain_client._get_chat_model → ChatLiteLLM（spec §5.1 表行 1）：
  model 收 provider 全名（现状 parse_model_string 拆开回退为不拆）；api_key/api_base
  字段名（非 openai_api_*）；max_retries/request_timeout 直传 litellm 顶层参数；
  ⚠️禁 num_retries——实证 langchain-litellm 0.7.1 下 tenacity(max_retries) 与
  openai SDK(num_retries) 双层叠加重试（wire 次数 5≠3），只许单层。
- C. _to_chat_response content 列表归一（spec §1.2#9 reasoning_content→thinking
  blocks 实证）：ChatLiteLLM 把 reasoning 注入 content=[thinking,text...]——
  ChatResponse.content 必须提取 text 块拼接（现状 str() 直转泄漏 thinking 文本）。
- D. harness.build_deep_agent → ChatLiteLLM（spec §5.1 表行 2）：全名直传不剥离
  （经 A 口径映射）；temperature=0.2/api_key/base_url 语义保留；deepagents 零改动。
- E. deps._build_store embedding → LiteLLMEmbeddings（spec §5.1 表行 3）：
  embedding 面统一 openai/ 前缀 + api_base（实证 zai/ 在 litellm 1.99 embedding
  端点 unmapped provider；注册表 embedding 模型全部走 OpenAI 兼容端点，#428
  wire 裸 id 契约经 litellm 剥前缀自动保留）。

测试形态与既有文件一致：asyncio_mode=auto；patch 目标 = 被测模块命名空间。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

# ── A. provider→litellm 前缀口径映射 ─────────────────────────────────


class TestLitellmProviderPrefix:
    """spec §5.1「provider 名口径」：一次性前缀口径表（非参数方言表）。"""

    def test_zhipu_maps_to_zai(self) -> None:
        """zhipu→zai（实证 litellm 1.99 provider_list 含 zai 无 zhipu）。"""
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert litellm_provider_prefix("zhipu") == "zai"

    def test_deepseek_native(self) -> None:
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert litellm_provider_prefix("deepseek") == "deepseek"

    def test_dashscope_native(self) -> None:
        """dashscope 原生（spec §5.1：deepseek/dashscope 原生）。"""
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert litellm_provider_prefix("dashscope") == "dashscope"

    def test_openai_native(self) -> None:
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert litellm_provider_prefix("openai") == "openai"

    def test_ollama_local_defaults_to_ollama_chat(self) -> None:
        """ollama 无自定义端点→ollama_chat（实证 ollama/ 走 /api/generate 原生
        形态，与注册表 base_url=localhost:11434/v1 的 OpenAI 兼容语义不符）。"""
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert litellm_provider_prefix("ollama") == "ollama_chat"

    def test_ollama_custom_http_base_url_uses_openai(self) -> None:
        """ollama 注册表带 http base_url（远程/兼容端点）→ openai/ 形态
        （实证 chat/completions 路径，fake/兼容服务端点契约统一）。"""
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert litellm_provider_prefix("ollama", base_url="http://192.168.1.5:11434/v1") == "openai"

    def test_fake_provider_uses_openai(self) -> None:
        """fake（ADR-047 测试缝）走 openai/ 前缀 + api_base（spec §5.1 fake 段）。"""
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert litellm_provider_prefix("fake", base_url="http://127.0.0.1:5999/v1") == "openai"

    def test_custom_openai_compatible_provider_uses_openai(self) -> None:
        """自定义 OpenAI 兼容第三方（不在 litellm provider_list）→ openai/ + api_base
        （spec §5.1：自定义注册 provider litellm 走 openai/ 前缀 + api_base）。"""
        from inkflow.infrastructure.llm.provider_config import litellm_provider_prefix

        assert (
            litellm_provider_prefix("myproxy", base_url="https://gw.corp.internal/v1") == "openai"
        )


# ── B. langchain_client._get_chat_model → ChatLiteLLM ────────────────


def _provider_cfg(
    provider: str = "zhipu",
    api_key: str = "test-key",
    base_url: str | None = "https://open.bigmodel.cn/api/paas/v4/",
    default_model: str = "glm-4.5",
) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
        max_retries=3,
        timeout=30,
    )


class TestGetChatModelLitellm:
    """spec §5.1 表行 1：_get_chat_model 构造 ChatLiteLLM（provider 前缀口径
    + 全名不拆 + api_key/api_base 字段名 + max_retries/request_timeout 顶层，
    无 num_retries）。"""

    def _call(self, client_cls, provider_cfg, **kw):
        with patch("inkflow.infrastructure.llm.langchain_client.ChatLiteLLM") as mock_cls:
            mock_cls.return_value = MagicMock(name="chat-model-instance")
            model = client_cls()._get_chat_model(provider_cfg, **kw)
        return mock_cls, model

    def test_returns_chatlitellm_instance(self) -> None:
        """构造对象 = ChatLiteLLM 返回值（litellm 轨，非 langchain-openai 旧轨）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        mock_cls, model = self._call(LangChainLLMClient, _provider_cfg())
        mock_cls.assert_called_once()
        assert model is mock_cls.return_value

    def test_kwargs_full_model_with_litellm_prefix(self) -> None:
        """model 收 provider 全名（zhipu 注册 provider → 口径映射 zai/glm-4.5；
        现状 parse_model_string 拆开传裸名的形态回退为不拆，spec §5.1 ⚠️ 行）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        mock_cls, _ = self._call(
            LangChainLLMClient,
            _provider_cfg(),
            model_name="glm-4.5",
            temperature=0.7,
            max_tokens=100,
        )
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "zai/glm-4.5"
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_tokens"] == 100

    def test_kwargs_api_key_and_api_base_field_names(self) -> None:
        """key/端点经 ChatLiteLLM 原生字段 api_key/api_base（非 openai_api_*；
        base_url 覆盖语义保留——fake server/自定义端点，spec §5.1）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        mock_cls, _ = self._call(LangChainLLMClient, _provider_cfg())
        kwargs = mock_cls.call_args[1]
        assert kwargs["api_key"] == "test-key"
        assert kwargs["api_base"] == "https://open.bigmodel.cn/api/paas/v4/"
        assert "openai_api_key" not in kwargs
        assert "openai_api_base" not in kwargs

    def test_kwargs_timeout_and_single_retry_layer(self) -> None:
        """request_timeout 顶层（=float(cfg.timeout)，#86/#344 契约值平移）；
        max_retries 直传；⚠️禁 num_retries——实证双层重试叠加（5 次 wire ≠ 3），
        重试语义单层化（tenacity 轨）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        mock_cls, _ = self._call(LangChainLLMClient, _provider_cfg())
        kwargs = mock_cls.call_args[1]
        assert kwargs["request_timeout"] == 30.0
        assert kwargs["max_retries"] == 3
        assert "num_retries" not in kwargs

    def test_empty_optional_kwargs_omitted(self) -> None:
        """无 api_key/base_url/max_tokens → 对应 kwargs 不出现（现状 omission
        语义保留，test_llm_client.py 同款契约平移）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        cfg = _provider_cfg(provider="ollama", api_key="", base_url=None)
        mock_cls, _ = self._call(LangChainLLMClient, cfg)
        kwargs = mock_cls.call_args[1]
        assert "api_key" not in kwargs
        assert "api_base" not in kwargs
        assert "max_tokens" not in kwargs

    def test_client_openai_api_base_override_wins(self) -> None:
        """构造级 openai_api_base 覆盖（连通探测场景）优先级不变：覆盖值 >
        provider_cfg.base_url（现状语义平移，字段名换 api_base）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient(openai_api_base="http://127.0.0.1:9/v1")
        mock_cls, _ = self._call(lambda: client, _provider_cfg())
        assert mock_cls.call_args[1]["api_base"] == "http://127.0.0.1:9/v1"

    def test_model_name_falls_back_to_default_model_full_name(self) -> None:
        """model_name 缺省 → default_model（注册表值为 provider/model 全名形态，
        不二次剥前缀）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        cfg = _provider_cfg(default_model="glm-4.5")
        mock_cls, _ = self._call(LangChainLLMClient, cfg)
        assert mock_cls.call_args[1]["model"] == "zai/glm-4.5"

    def test_prefixed_default_model_not_double_prefixed(self) -> None:
        """default_model 已是 provider/ 全名（_builtin_default_model 返回
        f"{provider}/{model}" 形态）→ 前缀映射作用于首段，禁叠成
        zai/zhipu/glm-4.5（#428 wire 裸名契约的装配侧防线）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        cfg = _provider_cfg(default_model="zhipu/glm-4.5")
        mock_cls, _ = self._call(LangChainLLMClient, cfg)
        assert mock_cls.call_args[1]["model"] == "zai/glm-4.5"

    def test_ollama_registry_base_url_routes_openai_compat(self) -> None:
        """🔴 #962 GREEN 评审补锁：ollama 带注册表 http base_url（内置
        http://localhost:11434/v1 = OpenAI 兼容端点，旧 langchain-openai 轨语义）→
        模型名必须经 base_url 口径走 openai/ 前缀。litellm ollama_chat
        get_complete_url 对 api_base 无条件追加 /api/chat（实证源码），叠上
        /v1 得 /v1/api/chat → 404 本地模型回归。前缀口径必须消费 base_url，
        不得只看 provider 名。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        cfg = _provider_cfg(
            provider="ollama",
            api_key="ollama",
            base_url="http://localhost:11434/v1",
            default_model="qwen2.5",
        )
        mock_cls, _ = self._call(LangChainLLMClient, cfg)
        assert mock_cls.call_args[1]["model"] == "openai/qwen2.5"
        assert mock_cls.call_args[1]["api_base"] == "http://localhost:11434/v1"

    def test_ollama_without_base_url_uses_native_chat(self) -> None:
        """ollama 无 base_url（防御形态）→ ollama_chat/ 原生（litellm 默认
        localhost:11434/api/chat，可用）；api_base 不出现。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        cfg = _provider_cfg(
            provider="ollama", api_key="ollama", base_url=None, default_model="qwen2.5"
        )
        mock_cls, _ = self._call(LangChainLLMClient, cfg)
        assert mock_cls.call_args[1]["model"] == "ollama_chat/qwen2.5"
        assert "api_base" not in mock_cls.call_args[1]


class TestHarnessProfileSafetyRegression:
    """🔴 安全面回归锁（迁移批核心风险，实证 deepagents 0.7.5 源码）：
    HarnessProfile 键按 `ls_provider:identifier` 解析——ChatLiteLLM 的
    ls_provider 恒为 "litellm"（chat_models/litellm.py:1027 硬编码），identifier
    = model 全名。现状 ensure_profile 键 `openai:<裸名>` 在迁移后必不命中 →
    默认 FS 工具（ls/read/write/edit/delete/glob/grep/execute）禁用静默失效。
    迁移必须配套：profile 注册键与 ChatLiteLLM 实例可解析键对齐。

    真实 create_deep_agent 构建（无网络 IO，仅 graph 装配），经
    _harness_profile_for_model 解析断言 excluded_tools 命中。
    """

    def test_profile_resolves_for_chatlitellm_instance(self) -> None:
        from deepagents._models import get_model_identifier, get_model_provider
        from deepagents.profiles.harness.harness_profiles import (
            _harness_profile_for_model,
        )
        from langchain_litellm import ChatLiteLLM

        from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent
        from inkflow.infrastructure.agent.deepagents.profiles import (
            DEFAULT_EXCLUDED_TOOLS,
        )

        build_deep_agent(
            model="zhipu/glm-4.5",
            api_key="sk-test",
            base_url="https://x/v1",
            tools=[],
            system_prompt="p",
        )
        # 用同一模型名构造真实 ChatLiteLLM 实例，走 deepagents 内部解析链
        chat = ChatLiteLLM(model="zai/glm-4.5", api_key="k")
        ident = get_model_identifier(chat)
        prov = get_model_provider(chat)
        profile = _harness_profile_for_model(chat, None)
        assert profile.excluded_tools == DEFAULT_EXCLUDED_TOOLS, (
            f"迁移后 profile 必须对 ChatLiteLLM(ls_provider={prov!r},"
            f"identifier={ident!r}) 命中，否则默认 FS 工具禁用失效（安全面）"
        )


# ── C. chat() 归一：reasoning content-block → 纯文本 ─────────────────


class TestChatResponseContentNormalisation:
    """spec §1.2#9/#727 链路在 ChatLiteLLM 下的归一契约：思考内容
    additional_kwargs['reasoning_content'] 保留给展示链，而 content 被注入
    thinking block 列表时，ChatResponse.content 必须只含 text 块拼接（写作链
    prompt 不泄漏思考过程，用户长篇创作主消费面）。"""

    def test_to_chat_response_extracts_text_from_blocks(self) -> None:
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        msg = AIMessage(
            content=[
                {"type": "thinking", "thinking": "深度思考过程"},
                {"type": "text", "text": "正文答案"},
            ],
            additional_kwargs={"reasoning_content": "深度思考过程"},
            response_metadata={"model_name": "openai/fake-model", "finish_reason": "stop"},
        )
        result = LangChainLLMClient._to_chat_response(msg)
        assert result.content == "正文答案"
        assert "深度思考过程" not in result.content

    def test_to_chat_response_str_content_unchanged(self) -> None:
        """纯 str content（无思考）路径行为不变。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        msg = AIMessage(
            content="普通回答",
            response_metadata={"model_name": "m", "finish_reason": "stop"},
        )
        assert LangChainLLMClient._to_chat_response(msg).content == "普通回答"

    def test_to_chat_response_text_block_content_key_fallback(self) -> None:
        """评审 nit-1（#962）：text 块内容键防御回退——litellm 规范用 text 键，
        但 OpenAI 兼容形态的 content 键不得被静默丢成空串。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        msg = AIMessage(
            content=[{"type": "text", "content": "gamma"}],
            response_metadata={"model_name": "m", "finish_reason": "stop"},
        )
        assert LangChainLLMClient._to_chat_response(msg).content == "gamma"

    def test_content_text_single_dict_block_not_repr(self) -> None:
        """评审 nit-1（#962）：单 dict（未包 list）按 content-part 解析，
        不得 str() repr 泄漏进正文（AIMessage 类型层拒单 dict，防御点在
        _content_text 模块函数本体——stream 块/未来形态兜底）。"""
        from inkflow.infrastructure.llm.langchain_client import _content_text

        assert _content_text({"type": "text", "text": "x"}) == "x"
        assert _content_text({"type": "text", "content": "y"}) == "y"


# ── D. harness.build_deep_agent → ChatLiteLLM ────────────────────────


class TestBuildDeepAgentLitellm:
    """spec §5.1 表行 2：ChatLiteLLM 直传 create_deep_agent（BaseChatModel
    契约，deepagents 零改动）；全名不剥离（经 A 口径映射加前缀）；
    temperature=0.2/api_key/base_url 现状语义保留。"""

    @pytest.fixture
    def harness_patches(self):
        """patch harness 命名空间：ChatLiteLLM + create_deep_agent。"""
        from unittest import mock

        with (
            mock.patch("inkflow.infrastructure.agent.deepagents.harness.ChatLiteLLM") as chat_cls,
            mock.patch(
                "inkflow.infrastructure.agent.deepagents.harness.create_deep_agent",
                return_value=MagicMock(name="agent"),
            ) as create,
        ):
            yield chat_cls, create

    def test_constructs_chatlitellm_with_prefixed_full_name(self, harness_patches) -> None:
        """zhipu/glm-4.5 → ChatLiteLLM(model='zai/glm-4.5', temperature=0.2)
        （现状 _strip_model_prefix 裸名形态回退为不拆，spec §5.1）。"""
        from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent

        chat_cls, create = harness_patches
        build_deep_agent(
            model="zhipu/glm-4.5",
            api_key="sk-test",
            base_url="https://x/v1",
            tools=[],
            system_prompt="p",
        )
        chat_cls.assert_called_once_with(
            model="zai/glm-4.5",
            api_key="sk-test",
            api_base="https://x/v1",
            temperature=0.2,
        )
        assert create.call_args.kwargs["model"] is chat_cls.return_value

    def test_openai_prefixed_model_passthrough(self, harness_patches) -> None:
        """openai/ 全名（fake 场景同款）→ 原样直传不二次处理。"""
        from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent

        chat_cls, _ = harness_patches
        build_deep_agent(
            model="openai/fake-model",
            api_key="k",
            base_url="http://127.0.0.1:1/v1",
            tools=[],
            system_prompt="p",
        )
        assert chat_cls.call_args[1]["model"] == "openai/fake-model"

    def test_model_without_prefix_passthrough(self, harness_patches) -> None:
        """无前缀裸名（parse ValueError 防御路径）→ 原样直传（现状语义平移）。"""
        from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent

        chat_cls, _ = harness_patches
        build_deep_agent(
            model="glm-4.5", api_key="sk", base_url="https://x/v1", tools=[], system_prompt="p"
        )
        assert chat_cls.call_args[1]["model"] == "glm-4.5"


# ── E. deps embedding 装配 → LiteLLMEmbeddings ───────────────────────


def _repo_with_providers(providers: list) -> MagicMock:
    repo = MagicMock()
    repo.list = AsyncMock(return_value=providers)
    return repo


class TestDepsEmbeddingLitellm:
    """spec §5.1 表行 3：_build_store → LiteLLMEmbeddings(model, api_key, api_base)。
    Embeddings Protocol 不变（FakeEmbeddings 注入零改动）；#428 wire 裸 id 契约经
    litellm openai/ 剥前缀自动保留（wire 层在 fake 黑盒用例锁定）。"""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        from inkflow.api import deps

        original = deps._vector_store
        deps._vector_store = None
        yield
        deps._vector_store = original

    async def test_builds_litellm_embeddings_with_prefixed_model(self) -> None:
        from langchain_litellm import LiteLLMEmbeddings

        from inkflow.api import deps
        from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
        from inkflow.infrastructure.llm.key_manager import APIKeyManager

        provider = ProviderConfig(
            name="openai",
            builtin_key="openai",
            base_url="https://api.test.example/v1",
            models=[ProviderModel(id="text-embedding-3-small", type="embedding")],
        )
        fake_store = MagicMock()
        with (
            patch(
                "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
                return_value=_repo_with_providers([provider]),
            ),
            patch.object(APIKeyManager, "load", return_value="sk-test-123"),
            patch(
                "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
                return_value=fake_store,
            ) as mock_vs,
        ):
            store = await deps.get_vector_store()

        assert store is fake_store
        embeddings = mock_vs.call_args.kwargs.get("embeddings") or mock_vs.call_args.args[1]
        assert isinstance(embeddings, LiteLLMEmbeddings)
        # 前缀口径：注册 provider 名经 A 映射（openai→openai）+ '/' + 模型 id 全名
        assert embeddings.model == "openai/text-embedding-3-small"
        assert embeddings.api_base == "https://api.test.example/v1"
        assert embeddings.api_key == "sk-test-123"

    async def test_zhipu_registry_embedding_maps_to_openai_compat(self) -> None:
        """#428 场景迁移形态：zhipu 注册 embedding（zhipu/embedding-3）→
        model 带 OpenAI 兼容前缀（实证 zai/ 在 litellm 1.99 embedding unmapped；
        注册表 embedding 全走 OpenAI 兼容端点 + api_base）。"""
        from langchain_litellm import LiteLLMEmbeddings

        from inkflow.api import deps
        from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
        from inkflow.infrastructure.llm.key_manager import APIKeyManager

        provider = ProviderConfig(
            name="zhipu",
            builtin_key="zhipu",
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            models=[ProviderModel(id="zhipu/embedding-3", type="embedding")],
        )
        with (
            patch(
                "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
                return_value=_repo_with_providers([provider]),
            ),
            patch.object(APIKeyManager, "load", return_value="sk-test-123"),
            patch(
                "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
                return_value=MagicMock(),
            ) as mock_vs,
        ):
            await deps.get_vector_store()

        embeddings = mock_vs.call_args.kwargs.get("embeddings") or mock_vs.call_args.args[1]
        assert isinstance(embeddings, LiteLLMEmbeddings)
        assert embeddings.model == "openai/embedding-3"
        assert embeddings.api_base == "https://open.bigmodel.cn/api/paas/v4/"


# ── F. 错误契约不破（spec §3.3 行 3：迁移不得回归 LLMRequestError 映射）──


class TestErrorContractPreserved:
    """迁移后既有错误语义回归锁：未配置 key → ValueError → LLMRequestError
    （#821 守卫、resolver #935 前置）；调用失败 → LLMRequestError(retries_exhausted)。"""

    async def test_missing_api_key_raises_llm_request_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from inkflow.infrastructure.llm import provider_config as pc
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        # 无任何 key 来源：环境变量清掉、内建/存储回退全空
        monkeypatch.delenv("INKFLOW_NONEXISTENTPROV_API_KEY", raising=False)
        monkeypatch.setattr(pc, "_BUILTIN_PROVIDERS", {})
        monkeypatch.setattr(pc, "_load_stored_key", lambda *_a, **_k: None)

        client = LangChainLLMClient()
        with pytest.raises(LLMRequestError):
            await client.chat(
                [ChatMessage(role="user", content="hi")],
                model="nonexistentprov/some-model",
            )

    async def test_call_failure_wrapped_as_llm_request_error(self) -> None:
        """ChatLiteLLM.ainvoke 抛任意异常 → LLMRequestError 包装（既有映射不变，
        异常上下文含 provider/model，spec §3.3 行 3）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        broken = MagicMock()
        broken.ainvoke = AsyncMock(side_effect=RuntimeError("upstream 400"))
        client._get_chat_model = MagicMock(return_value=broken)
        cfg = _provider_cfg()
        with (
            patch(
                "inkflow.infrastructure.llm.langchain_client.get_provider_config",
                return_value=cfg,
            ),
            pytest.raises(LLMRequestError) as ei,
        ):
            await client.chat([ChatMessage(role="user", content="hi")], model="zhipu/glm-4.5")
        assert ei.value.provider == "zhipu"
