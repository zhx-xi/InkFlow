"""LangChainLLMClient 单元测试 — Mock ChatOpenAI，不发起真实 LLM 调用。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from inkflow.domain.ports.llm_client import ChatMessage, ChatResponse, StreamEvent
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig


# Helper: convert list to async generator
async def _async_iter(items):
    for item in items:
        yield item


def _fake_provider_config(provider: str = "openai") -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider,
        api_key="test-key",
        default_model="gpt-4o",
        max_retries=1,
        timeout=10,
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
