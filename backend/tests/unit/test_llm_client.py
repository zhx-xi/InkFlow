"""LangChainLLMClient 单元测试 — Mock ChatOpenAI，不发起真实 LLM 调用。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from inkflow.core.config import config
from inkflow.domain.ports.llm_client import ChatMessage, ChatResponse, StreamEvent
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig


# Helper: convert list to async generator
async def _async_iter(items):
    for item in items:
        yield item


def _fake_provider_config(provider: str = "openai") -> LLMProviderConfig:
    # #344: simulate real assembly path -- get_provider_config builds
    # LLMProviderConfig with timeout=config.llm_request_timeout
    return LLMProviderConfig(
        provider=provider,
        api_key="test-key",
        default_model="gpt-4o",
        max_retries=1,
        timeout=config.llm_request_timeout,
    )


class TestLangChainLLMClient:
    """LangChainLLMClient Mock 测试套件。"""

    @pytest.fixture
    def chat_messages(self) -> list[ChatMessage]:
        return [
            ChatMessage(role="system", content="你是一个助手"),
            ChatMessage(role="user", content="你好"),
        ]

    @pytest.fixture
    def mock_chat_model(self):
        """Mock ChatOpenAI，返回预设 AIMessage。"""
        mock = AsyncMock()
        mock.ainvoke.return_value = AIMessage(
            content="你好！有什么可以帮助你的？",
            response_metadata={
                "model_name": "gpt-4o",
                "finish_reason": "stop",
                "token_usage": {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23},
            },
        )
        return mock

    # ── chat() 正常场景 ──

    @pytest.mark.asyncio
    async def test_chat_returns_response(self, mock_chat_model, chat_messages):
        """chat() 应返回 ChatResponse。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        client._get_chat_model = MagicMock(return_value=mock_chat_model)
        with patch(
            "inkflow.infrastructure.llm.langchain_client.get_provider_config",
            return_value=_fake_provider_config(),
        ):
            response = await client.chat(chat_messages, model="openai/gpt-4o")
        assert isinstance(response, ChatResponse)
        assert response.content == "你好！有什么可以帮助你的？"
        assert response.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_chat_passes_temperature(self, mock_chat_model, chat_messages):
        """chat() 应将 temperature 传递给 ChatOpenAI。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient(temperature=0.5)
        client._get_chat_model = MagicMock(return_value=mock_chat_model)
        with patch(
            "inkflow.infrastructure.llm.langchain_client.get_provider_config",
            return_value=_fake_provider_config(),
        ):
            await client.chat(chat_messages, temperature=0.9)
        client._get_chat_model.assert_called_once()
        call_kwargs = client._get_chat_model.call_args[1]
        assert call_kwargs["temperature"] == 0.9

    # ── chat_stream() ──

    @pytest.mark.asyncio
    async def test_chat_stream_yields_events(self, chat_messages):
        """chat_stream() 应逐 token 返回 StreamEvent。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        mock_model = AsyncMock()
        chunks = [
            AIMessage(content="你"),
            AIMessage(content="好"),
            AIMessage(content="！"),
            AIMessage(content="", response_metadata={"finish_reason": "stop"}),
        ]
        mock_model.astream = MagicMock(return_value=_async_iter(chunks))
        client._get_chat_model = MagicMock(return_value=mock_model)
        with patch(
            "inkflow.infrastructure.llm.langchain_client.get_provider_config",
            return_value=_fake_provider_config(),
        ):
            events = []
            async for event in client.chat_stream(chat_messages):
                events.append(event)
                assert isinstance(event, StreamEvent)

        assert len(events) == 5
        assert events[0].content == "你"
        assert events[1].content == "好"
        assert events[2].content == "！"
        # 第 4 个是空 content 的中间 chunk（finish_reason=stop）
        assert events[3].content == ""
        # 第 5 个是最终标记事件
        assert events[-1].is_final is True

    # ── count_tokens() ──

    @pytest.mark.asyncio
    async def test_count_tokens_returns_int(self, chat_messages):
        """count_tokens() 应返回正整数。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        count = await client.count_tokens(chat_messages)
        assert isinstance(count, int)
        assert count > 0

    @pytest.mark.asyncio
    async def test_count_tokens_empty_messages(self):
        """空消息列表应返回 0。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        count = await client.count_tokens([])
        assert count == 0

    # ── 错误场景 ──

    @pytest.mark.asyncio
    async def test_chat_empty_messages_raises(self):
        """空消息应抛出 ValueError。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        with pytest.raises(ValueError, match="messages cannot be empty"):
            await client.chat([])

    # ── Issue #86 契约 1（P0）：ChatOpenAI 超时参数名 timeout → request_timeout ──

    def test_get_chat_model_uses_request_timeout(self):
        """_get_chat_model 应传 request_timeout（langchain-openai 1.4.1 无 timeout 字段）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        provider_cfg = _fake_provider_config()
        with patch("inkflow.infrastructure.llm.langchain_client.ChatOpenAI") as mock_chat:
            LangChainLLMClient()._get_chat_model(provider_cfg)

        mock_chat.assert_called_once()
        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["request_timeout"] == float(provider_cfg.timeout)
        assert "timeout" not in call_kwargs

    # ── Issue #86 契约 4（小修）：count_tokens 按模型选 encoding ──

    @pytest.mark.asyncio
    async def test_count_tokens_uses_model_specific_encoding(self, chat_messages):
        """count_tokens 应按 model 调用 tiktoken.encoding_for_model，而非硬编码 cl100k_base。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        fake_enc = MagicMock()
        fake_enc.encode.return_value = [1, 2]
        fake_tiktoken = MagicMock()
        fake_tiktoken.encoding_for_model.return_value = fake_enc
        with patch.dict("sys.modules", {"tiktoken": fake_tiktoken}):
            count = await client.count_tokens(chat_messages, model="deepseek/deepseek-chat")

        fake_tiktoken.encoding_for_model.assert_called()
        model_arg = fake_tiktoken.encoding_for_model.call_args[0][0]
        assert isinstance(model_arg, str)
        assert "deepseek" in model_arg
        assert isinstance(count, int)
        assert count > 0

    @pytest.mark.asyncio
    async def test_count_tokens_unknown_model_falls_back(self, chat_messages):
        """未知模型导致 encoding_for_model 失败时应回退估算，不抛异常。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        fake_tiktoken = MagicMock()
        fake_tiktoken.encoding_for_model.side_effect = KeyError("unknown model")
        with patch.dict("sys.modules", {"tiktoken": fake_tiktoken}):
            count = await client.count_tokens(chat_messages, model="unknown/foo")

        assert isinstance(count, int)
        assert count > 0

    # ── Issue #86 契约 5（小修）：未知 role 显式报错 ──

    def test_to_langchain_messages_unknown_role_raises(self):
        """未知 role 应显式抛 ValueError，而非静默降级为 HumanMessage。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        with pytest.raises(ValueError) as exc_info:
            LangChainLLMClient._to_langchain_messages([ChatMessage(role="hacker", content="x")])
        assert "hacker" in str(exc_info.value)
        assert "role" in str(exc_info.value)

    def test_to_langchain_messages_known_roles(self):
        """已知 role（system/user/assistant）仍应正常转换。"""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        result = LangChainLLMClient._to_langchain_messages(
            [
                ChatMessage(role="system", content="s"),
                ChatMessage(role="user", content="u"),
                ChatMessage(role="assistant", content="a"),
            ]
        )
        assert [type(m) for m in result] == [SystemMessage, HumanMessage, AIMessage]

    # ── Issue #86 契约 6（小修）：_max_retries 死代码删除 ──

    def test_init_accepts_max_retries_but_does_not_store(self):
        """__init__ 保留 max_retries 参数兼容调用方，但不应再存储死代码属性 _max_retries。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient(max_retries=5)
        assert not hasattr(client, "_max_retries")


class TestLangChainLLMClientErrorMapping:
    """Issue #104 Phase 3：异常映射缺口（parse / provider / ainvoke / astream）。"""

    @pytest.fixture
    def chat_messages(self) -> list[ChatMessage]:
        return [
            ChatMessage(role="system", content="你是一个助手"),
            ChatMessage(role="user", content="你好"),
        ]

    @pytest.mark.asyncio
    async def test_chat_invalid_model_format_raises_llm_error(self, chat_messages):
        """model 字符串无 '/' → LLMRequestError（provider 为空、model 原样保留）。"""
        from inkflow.domain.ports.llm_errors import LLMRequestError
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        with pytest.raises(LLMRequestError) as exc_info:
            await client.chat(chat_messages, model="no-slash-model")
        assert exc_info.value.provider == ""
        assert exc_info.value.model == "no-slash-model"
        assert "Invalid model format" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_chat_unknown_provider_raises_llm_error(self, chat_messages):
        """get_provider_config 抛 ValueError（API key 未配置）→ LLMRequestError。"""
        from inkflow.domain.ports.llm_errors import LLMRequestError
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        with (
            patch(
                "inkflow.infrastructure.llm.langchain_client.get_provider_config",
                side_effect=ValueError("API key not configured for provider: openai"),
            ),
            pytest.raises(LLMRequestError) as exc_info,
        ):
            await client.chat(chat_messages, model="openai/gpt-4o")
        assert exc_info.value.provider == "openai"
        assert exc_info.value.model == "gpt-4o"
        assert "API key not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_chat_ainvoke_failure_maps_to_llm_error(self, chat_messages):
        """ainvoke 抛任意异常 → LLMRequestError（retries_exhausted=True）。"""
        from inkflow.domain.ports.llm_errors import LLMRequestError
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        mock_chat_model = AsyncMock()
        mock_chat_model.ainvoke = AsyncMock(side_effect=RuntimeError("upstream timeout"))
        client = LangChainLLMClient()
        client._get_chat_model = MagicMock(return_value=mock_chat_model)
        with (
            patch(
                "inkflow.infrastructure.llm.langchain_client.get_provider_config",
                return_value=_fake_provider_config(),
            ),
            pytest.raises(LLMRequestError) as exc_info,
        ):
            await client.chat(chat_messages, model="openai/gpt-4o")
        assert exc_info.value.retries_exhausted is True
        assert "LLM call failed" in str(exc_info.value)
        assert exc_info.value.provider == "openai"

    @pytest.mark.asyncio
    async def test_chat_stream_empty_messages_raises(self):
        """chat_stream 空消息 → ValueError（与 chat 一致）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        with pytest.raises(ValueError, match="messages cannot be empty"):
            async for _ in client.chat_stream([]):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_chat_stream_astream_failure_maps_to_llm_error(self, chat_messages):
        """astream 中途抛异常 → LLMRequestError「LLM stream failed」。"""
        from inkflow.domain.ports.llm_errors import LLMRequestError
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        async def _broken_stream(*args, **kwargs):
            raise RuntimeError("stream broke")
            yield  # pragma: no cover

        mock_model = MagicMock()
        mock_model.astream = _broken_stream
        client = LangChainLLMClient()
        client._get_chat_model = MagicMock(return_value=mock_model)
        with (
            patch(
                "inkflow.infrastructure.llm.langchain_client.get_provider_config",
                return_value=_fake_provider_config(),
            ),
            pytest.raises(LLMRequestError) as exc_info,
        ):
            async for _ in client.chat_stream(chat_messages):
                pass  # pragma: no cover
        assert "LLM stream failed" in str(exc_info.value)
        assert exc_info.value.provider == "openai"

    @pytest.mark.asyncio
    async def test_count_tokens_invalid_model_uses_raw_string(self, chat_messages):
        """count_tokens 无法解析 model 字符串 → 原样作为 model_name 传给 tiktoken。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        client = LangChainLLMClient()
        fake_enc = MagicMock()
        fake_enc.encode.return_value = [1, 2, 3]
        fake_tiktoken = MagicMock()
        fake_tiktoken.encoding_for_model.return_value = fake_enc
        with patch.dict("sys.modules", {"tiktoken": fake_tiktoken}):
            count = await client.count_tokens(chat_messages, model="no-slash-model")

        assert count > 0
        assert fake_tiktoken.encoding_for_model.call_args[0][0] == "no-slash-model"

    def test_get_chat_model_full_kwargs(self):
        """_get_chat_model 携带 api_key/base_url/max_tokens → 全部写入 ChatOpenAI kwargs。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        provider_cfg = LLMProviderConfig(
            provider="deepseek",
            api_key="ds-key",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-chat",
            max_retries=3,
            timeout=30,
        )
        with patch("inkflow.infrastructure.llm.langchain_client.ChatOpenAI") as mock_chat:
            LangChainLLMClient()._get_chat_model(
                provider_cfg, model_name="deepseek-chat", temperature=0.7, max_tokens=100
            )
        kwargs = mock_chat.call_args[1]
        assert kwargs["openai_api_key"] == "ds-key"
        assert kwargs["openai_api_base"] == "https://api.deepseek.com/v1"
        assert kwargs["max_tokens"] == 100
        assert kwargs["temperature"] == 0.7
        assert kwargs["request_timeout"] == float(30)

    def test_get_chat_model_omits_empty_optional_kwargs(self):
        """_get_chat_model 无 api_key/base_url/max_tokens → 对应 kwargs 不出现。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        provider_cfg = LLMProviderConfig(
            provider="ollama",
            api_key="",  # 空字符串为假值 → 不写 openai_api_key
            default_model="qwen2.5",
        )
        with patch("inkflow.infrastructure.llm.langchain_client.ChatOpenAI") as mock_chat:
            LangChainLLMClient()._get_chat_model(provider_cfg)
        kwargs = mock_chat.call_args[1]
        assert "openai_api_key" not in kwargs
        assert "openai_api_base" not in kwargs
        assert "max_tokens" not in kwargs

    # ── #344 管线节点 LLM 装配契约（真实 LLM 链路修复）──

    def test_pipeline_llm_client_assembles_api_key_base_url_model(self):
        """#344: 管线节点 LangChainLLMClient 装配 — APIKeyManager 已存 key 回退链生效.

        GUI 场景 key 经 POST /settings/llm-keys 注册（APIKeyManager 落盘），
        管线节点 LangChainLLMClient() 无参构造 → chat(model='zhipu/glm-4.5')
        应解析到已存 key + 注册表 base_url + 正确 model。防止「测试轨只锁
        writing 路径、管线路径裸奔」盲区（#344 修复方向 ③）。
        """
        from inkflow.domain.ports.llm_client import ChatMessage
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        fake_key = "zhipu-stored-key-abc123"
        # APIKeyManager.load 回退链命中（GUI 注册的 key）
        with patch(
            "inkflow.infrastructure.llm.provider_config._load_stored_key",
            return_value=fake_key,
        ):
            client = LangChainLLMClient()
            with patch("inkflow.infrastructure.llm.langchain_client.ChatOpenAI") as mock_chat:
                mock_chat.return_value.ainvoke = AsyncMock(
                    return_value=MagicMock(content="ok", response_metadata={})
                )
                import asyncio

                asyncio.run(
                    client.chat(
                        [ChatMessage(role="user", content="hi")],
                        model="zhipu/glm-4.5",
                    )
                )
        kwargs = mock_chat.call_args[1]
        assert kwargs["openai_api_key"] == fake_key
        assert kwargs["openai_api_base"] == "https://open.bigmodel.cn/api/paas/v4/"
        assert kwargs["model"] == "glm-4.5"

    def test_pipeline_llm_client_timeout_allows_slow_models(self):
        """#344: 管线节点 LLM 请求超时须大于慢模型真实延迟（zhipu 33-112s 实测）.

        根因实证（2026-08-14 真实 LLM）：glm-4.5 单次调用 33.7s（简单）/
        112.3s（architect 完整 prompt），request_timeout=120 处极限边缘，
        慢网络下必然超时 → 4 次重试 × 120s = 8 分钟 → 「architect 重试耗尽」。
        契约：LangChainLLMClient 构造的 ChatOpenAI request_timeout >= 300。
        """
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        # Contract 1: config.llm_request_timeout default must allow slow models
        # (real assembly data source in provider_config.get_provider_config)
        assert config.llm_request_timeout >= 300, (
            f"config.llm_request_timeout={config.llm_request_timeout} "
            "too tight for slow models (#344 root cause)"
        )

        provider_cfg = _fake_provider_config()
        with patch("inkflow.infrastructure.llm.langchain_client.ChatOpenAI") as mock_chat:
            LangChainLLMClient()._get_chat_model(provider_cfg)
        kwargs = mock_chat.call_args[1]
        assert (
            kwargs["request_timeout"] >= 300
        ), f"request_timeout={kwargs.get('request_timeout')} 对慢模型太紧（#344 根因）"
