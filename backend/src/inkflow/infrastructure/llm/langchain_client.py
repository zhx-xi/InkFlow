"""LangChain LLM 客户端 — 实现 LLMClientProtocol。

基于 langchain_openai.ChatOpenAI，通过 custom base_url 支持 OpenAI 兼容 API。
领域层通过 LLMClientProtocol 调用，不感知 LangChain。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from inkflow.core.config import config
from inkflow.domain.ports.llm_client import ChatMessage, ChatResponse, StreamEvent, TokenUsage
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.infrastructure.llm.provider_config import (
    LLMProviderConfig,
    get_provider_config,
    parse_model_string,
)


class LangChainLLMClient:
    """LangChain ChatOpenAI 适配器 — 通过 base_url 支持多 Provider。

    测试时可注入 Mock ChatOpenAI，不发起真实 HTTP 请求。
    """

    def __init__(
        self,
        default_model: str | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._default_model = default_model or config.llm_default_model
        self._temperature = temperature if temperature is not None else config.llm_temperature
        self._max_retries = max_retries if max_retries is not None else config.llm_max_retries

    # ── Public API ──

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        """发送聊天请求并获取完整响应（同步封装）。"""
        if not messages:
            raise ValueError("messages cannot be empty")

        import asyncio

        return asyncio.run(
            self._chat_async(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        )

    async def _chat_async(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """异步聊天实现。"""
        model_str = model or self._default_model
        try:
            provider, model_name = parse_model_string(model_str)
        except ValueError as e:
            raise LLMRequestError(str(e), provider="", model=model_str) from e

        try:
            provider_cfg = get_provider_config(provider)
        except ValueError as e:
            raise LLMRequestError(str(e), provider=provider, model=model_name) from e

        chat_model = self._get_chat_model(
            provider_cfg,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        langchain_messages = self._to_langchain_messages(messages)
        try:
            response: AIMessage = await chat_model.ainvoke(langchain_messages)
        except Exception as e:
            raise LLMRequestError(
                f"LLM call failed: {e}",
                provider=provider,
                model=model_name,
                retries_exhausted=True,
            ) from e

        return self._to_chat_response(response)

    async def chat_stream(  # type: ignore[misc]
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式聊天 — 逐 token 返回 StreamEvent。"""
        if not messages:
            raise ValueError("messages cannot be empty")

        model_str = model or self._default_model
        provider, model_name = parse_model_string(model_str)
        provider_cfg = get_provider_config(provider)

        chat_model = self._get_chat_model(
            provider_cfg,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        langchain_messages = self._to_langchain_messages(messages)
        try:
            async for chunk in chat_model.astream(langchain_messages):
                content_raw = chunk.content if hasattr(chunk, "content") else str(chunk)
                content = content_raw if isinstance(content_raw, str) else str(content_raw)
                yield StreamEvent(content=content, is_final=False)
        except Exception as e:
            raise LLMRequestError(
                f"LLM stream failed: {e}",
                provider=provider,
                model=model_name,
            ) from e

        # Final event
        yield StreamEvent(content="", is_final=True)

    def count_tokens(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> int:
        """估算消息列表的 Token 数。

        优先使用 tiktoken，回退到字符数/4 估算。
        """
        if not messages:
            return 0

        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            total = 0
            for msg in messages:
                total += 4
                total += len(enc.encode(msg.content))
            return total
        except Exception:
            total_chars = sum(len(m.content) for m in messages)
            return max(1, total_chars // 4)

    # ── Private helpers ──

    def _get_chat_model(
        self,
        provider_cfg: LLMProviderConfig,
        model_name: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatOpenAI:
        """创建 ChatOpenAI 实例（通过 base_url 支持多 Provider）。"""
        model = model_name or provider_cfg.default_model
        temp = temperature if temperature is not None else self._temperature

        chat_kwargs: dict[str, object] = {
            "model": model,
            "temperature": temp,
            "max_retries": provider_cfg.max_retries,
            "timeout": float(provider_cfg.timeout),
        }
        if provider_cfg.api_key:
            chat_kwargs["openai_api_key"] = provider_cfg.api_key
        if provider_cfg.base_url:
            chat_kwargs["openai_api_base"] = provider_cfg.base_url
        if max_tokens is not None:
            chat_kwargs["max_tokens"] = max_tokens

        return ChatOpenAI(**chat_kwargs)  # type: ignore[arg-type]

    @staticmethod
    def _to_langchain_messages(messages: list[ChatMessage]) -> list:
        """将领域层 ChatMessage 转换为 LangChain 消息类型。"""
        role_map: dict[str, type] = {
            "system": SystemMessage,
            "user": HumanMessage,
            "assistant": AIMessage,
        }
        result: list = []
        for msg in messages:
            msg_cls = role_map.get(msg.role, HumanMessage)
            result.append(msg_cls(content=msg.content))
        return result

    @staticmethod
    def _to_chat_response(response: AIMessage) -> ChatResponse:
        """将 LangChain AIMessage 转换为领域层 ChatResponse。"""
        metadata = response.response_metadata or {}
        usage = None
        if "token_usage" in metadata:
            tu = metadata["token_usage"]
            usage = TokenUsage(
                prompt_tokens=tu.get("prompt_tokens", 0),
                completion_tokens=tu.get("completion_tokens", 0),
                total_tokens=tu.get("total_tokens", 0),
            )
        return ChatResponse(
            content=response.content
            if isinstance(response.content, str)
            else str(response.content),
            model=metadata.get("model_name", "unknown"),
            token_usage=usage,
            finish_reason=metadata.get("finish_reason", "stop"),
        )
