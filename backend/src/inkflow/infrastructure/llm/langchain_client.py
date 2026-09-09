"""LangChain LLM 客户端 — 实现 LLMClientProtocol。

基于 langchain_litellm.ChatLiteLLM（ADR-051，取代 ADR-005v2），通过 api_base
支持多 Provider / OpenAI 兼容 API。
领域层通过 LLMClientProtocol 调用，不感知 LangChain。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_litellm import ChatLiteLLM

from inkflow.core.config import config
from inkflow.domain.ports.llm_client import ChatMessage, ChatResponse, StreamEvent, TokenUsage
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.infrastructure.llm.capability_probe import apply_reasoning_effort
from inkflow.infrastructure.llm.content_text import content_text
from inkflow.infrastructure.llm.provider_config import (
    LLMProviderConfig,
    get_provider_config,
    litellm_model_name,
    parse_model_string,
)
from inkflow.logging import instrument, log_structured


class LangChainLLMClient:
    """LangChain ChatLiteLLM 适配器 — 经 litellm 前缀口径 + api_base 支持多 Provider
    （ADR-051，取代 ADR-005v2）。

    测试时可注入 Mock ChatLiteLLM，不发起真实 HTTP 请求。
    """

    def __init__(
        self,
        default_model: str | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        api_key: str | None = None,
        openai_api_base: str | None = None,
    ) -> None:
        self._default_model = default_model or config.llm_default_model
        self._temperature = temperature if temperature is not None else config.llm_temperature
        # 可选 API Key 覆盖值（连通探测按请求携带密钥，优先于环境变量注入）
        self._api_key = api_key
        # 可选自定义端点覆盖（连通探测 openai_api_base，优先于 provider 注册表 base_url）
        self._openai_api_base = openai_api_base

    # ── Public API ──

    @instrument(caller_type="llm")
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        """发送聊天请求并获取完整响应。"""
        if not messages:
            raise ValueError("messages cannot be empty")

        reasoning_effort = kwargs.get("reasoning_effort")
        if not isinstance(reasoning_effort, str):
            reasoning_effort = None
        return await self._chat_async(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

    @instrument(caller_type="llm")
    async def _chat_async(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> ChatResponse:
        """异步聊天实现。"""
        model_str = model or self._default_model
        try:
            provider, model_name = parse_model_string(model_str)
        except ValueError as e:
            raise LLMRequestError(str(e), provider="", model=model_str) from e

        try:
            provider_cfg = get_provider_config(provider, api_key=self._api_key)
        except ValueError as e:
            raise LLMRequestError(str(e), provider=provider, model=model_name) from e

        chat_model = self._get_chat_model(
            provider_cfg,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

        langchain_messages = self._to_langchain_messages(messages)
        log_structured(
            level="DEBUG",
            caller_type="llm",
            caller_name="langchain_client.chat",
            event="llm_request",
            message_key="log.event.llm_request",
            message=f"LLM 请求：{model_str}（{len(messages)} 条消息）",
            params={"model": model_str, "count": len(messages)},
        )
        try:
            response: AIMessage = await chat_model.ainvoke(langchain_messages)
        except Exception as e:
            raise LLMRequestError(
                f"LLM call failed: {e}",
                provider=provider,
                model=model_name,
                retries_exhausted=True,
            ) from e

        result = self._to_chat_response(response)
        log_structured(
            level="DEBUG",
            caller_type="llm",
            caller_name="langchain_client.chat",
            event="llm_response",
            message_key="log.event.llm_response",
            message=f"LLM 响应：{result.model}（{len(result.content)} 字符）",
            params={"model": result.model, "length": len(result.content)},
        )
        return result

    @instrument(caller_type="llm")
    async def chat_stream(
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

        reasoning_effort = kwargs.get("reasoning_effort")
        if not isinstance(reasoning_effort, str):
            reasoning_effort = None
        model_str = model or self._default_model
        provider, model_name = parse_model_string(model_str)
        provider_cfg = get_provider_config(provider, api_key=self._api_key)

        chat_model = self._get_chat_model(
            provider_cfg,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

        langchain_messages = self._to_langchain_messages(messages)
        try:
            async for chunk in chat_model.astream(langchain_messages):
                content_raw = chunk.content if hasattr(chunk, "content") else str(chunk)
                content = _content_text(content_raw)
                yield StreamEvent(content=content, is_final=False)
        except Exception as e:
            raise LLMRequestError(
                f"LLM stream failed: {e}",
                provider=provider,
                model=model_name,
            ) from e

        # Final event
        yield StreamEvent(content="", is_final=True)

    @instrument(caller_type="llm")
    async def count_tokens(
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

        model_str = model or self._default_model
        try:
            _, model_name = parse_model_string(model_str)
        except ValueError:
            model_name = model_str

        try:
            import tiktoken

            enc = tiktoken.encoding_for_model(model_name)
            total = 0
            for msg in messages:
                total += 4
                total += len(enc.encode(msg.content))
        except Exception:
            total_chars = sum(len(m.content) for m in messages)
            return max(1, total_chars // 4)
        else:
            return total

    # ── Private helpers ──

    def _get_chat_model(
        self,
        provider_cfg: LLMProviderConfig,
        model_name: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> ChatLiteLLM:
        """创建 ChatLiteLLM 实例（经 litellm 前缀口径 + api_base 支持多 Provider，
        ADR-051）。

        model 收 provider 全名（现状 parse_model_string 拆开传裸名的形态回退为不拆，
        spec f59 §5.1 ⚠️ 行）；api_key/api_base 为 ChatLiteLLM 原生字段名；
        max_retries/request_timeout 直传 litellm 顶层参数——禁 num_retries（实证
        tenacity × openai SDK 双层叠加重试是缺陷，只许单层）。

        reasoning_effort: F59 可选思考档位——经 apply_reasoning_effort 注入
        ChatLiteLLM kwargs（default/None 不发送；超能力软降级见 §5.5）。
        """
        model = model_name or provider_cfg.default_model
        if model and "/" not in model:
            model = f"{provider_cfg.provider}/{model}"
        temp = temperature if temperature is not None else self._temperature
        base_url = self._openai_api_base or provider_cfg.base_url

        full_model = litellm_model_name(model, base_url)
        chat_kwargs: dict[str, object] = {
            "model": full_model,
            "temperature": temp,
            "max_retries": provider_cfg.max_retries,
            "request_timeout": float(provider_cfg.timeout),
        }
        if provider_cfg.api_key:
            chat_kwargs["api_key"] = provider_cfg.api_key
        if base_url:
            chat_kwargs["api_base"] = base_url
        if max_tokens is not None:
            chat_kwargs["max_tokens"] = max_tokens
        chat_kwargs = apply_reasoning_effort(
            chat_kwargs,
            model_full=full_model,
            effort=reasoning_effort,
        )

        return ChatLiteLLM(**chat_kwargs)  # type: ignore[arg-type]  # chat_kwargs 为动态 dict[str, object]，无法静态匹配 ChatLiteLLM 构造参数

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
            if msg.role not in role_map:
                raise ValueError(f"未知消息角色: {msg.role} (unknown role)")
            msg_cls = role_map[msg.role]
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
            content=_content_text(response.content),
            model=metadata.get("model_name", "unknown"),
            token_usage=usage,
            finish_reason=metadata.get("finish_reason", "stop"),
        )


def _content_text(content: object) -> str:
    """Delegate to the shared normalizer (unified in #1045)."""
    return content_text(content)
