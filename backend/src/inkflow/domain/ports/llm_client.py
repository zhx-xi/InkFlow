"""
LLM 客户端端口 — 定义领域层与 LLM Provider 之间的契约。

基础设施层（LangChain ChatLiteLLM）实现此 Protocol。
领域层只依赖此接口，不感知 LangChain。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChatResponse:
    """LLM 聊天完成响应 — 领域层统一数据模型。

    与 LangChain 的 AIMessage 解耦，避免领域层依赖框架类型。
    """

    content: str
    """LLM 返回的文本内容。"""

    model: str
    """实际使用的模型名称（provider/model_name）。"""

    token_usage: TokenUsage | None = None
    """Token 消耗统计（可能不可用，取决于 Provider）。"""

    finish_reason: str = "stop"
    """停止原因：stop / length / content_filter / error。"""


@dataclass
class StreamEvent:
    """流式响应事件 — 逐 token 推送。"""

    content: str
    """当前 chunk 的文本内容。"""

    is_final: bool = False
    """是否为最后一个 chunk。"""

    token_usage: TokenUsage | None = None
    """最终 chunk 携带的 Token 统计。"""


@dataclass
class TokenUsage:
    """Token 消耗统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatMessage:
    """聊天消息。"""

    role: str
    """消息角色：system / user / assistant。"""

    content: str
    """消息内容。"""


class LLMClientProtocol(Protocol):
    """LLM 客户端端口 — 统一 chat / stream / completion 接口。

    基础设施层实现示例：
        from langchain_community.chat_models import ChatLiteLLM
        class LangChainLLMClient: ...

    测试时可注入 Mock 实现，不依赖实际 LLM API。
    """

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        """发送聊天请求并获取完整响应。

        Args:
            messages: 消息列表（system / user / assistant）。
            model: 模型名称，None 则使用 LLMClient 的默认模型。
            temperature: 温度参数，None 则使用默认值。
            max_tokens: 最大输出 Token 数。
            **kwargs: Provider 特定参数。

        Returns:
            ChatResponse: 统一格式的响应。

        Raises:
            LLMRequestError: 调用失败（网络、超时、Provider 错误等）。
        """
        ...

    def chat_stream(  # type: ignore[misc]  # 生成器函数返回类型应为 Generator 而非 AsyncGenerator（Protocol 桩方法）
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式聊天 — 逐 token 返回。

        Args:
            messages: 消息列表。
            model: 模型名称。
            temperature: 温度参数。
            max_tokens: 最大输出 Token 数。
            **kwargs: Provider 特定参数。

        Yields:
            StreamEvent: 流式事件（逐 chunk）。
        """
        ...
        yield  # type: ignore[misc]  # 空 yield 与 AsyncGenerator[StreamEvent] 产出类型不符（桩无需实际产出）

    async def count_tokens(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> int:
        """计算消息列表的 Token 数。

        Args:
            messages: 消息列表。
            model: 模型名称（不同模型 Tokenizer 不同）。

        Returns:
            Token 数量估算。
        """
        ...
