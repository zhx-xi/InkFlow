"""LLM 探测实现 — `InfrastructureLLMProbe`（#936 C 项）。

domain 定义 `LLMProbeProtocol`，本模块提供实现（ADR-015 依赖倒置）。复用
`LangChainLLMClient` 的 chat 语义 + `LiteLLMEmbeddings` 的 embedding 语义；
不 import api 层 `settings.py` 的私有函数（跨层），在本模块写等价实现。
两类探测失败均抛出异常（由 service 转 422）。
探测请求钉固定小预算（PROBE_REQUEST_TIMEOUT_S）——连通探测不得继承 provider 120s 业务超时（#1117）。
"""

from __future__ import annotations

import asyncio

# 连通探测请求超时预算（秒）：最小连通性探针，不继承 provider 120s 业务超时（#1117）。
PROBE_REQUEST_TIMEOUT_S = 15


class InfrastructureLLMProbe:
    """`LLMProbeProtocol` 实现：chat 最小 completion + embedding 占位探测。"""

    async def probe_chat(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        """构造 `LangChainLLMClient` 发一条最小 chat；await 完成即成功（失败抛异常）。"""
        from inkflow.domain.ports.llm_client import ChatMessage
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        model_ref = model if "/" in model else f"{provider}/{model}"
        if base_url:
            client = LangChainLLMClient(
                default_model=model_ref,
                api_key=api_key,
                openai_api_base=base_url,
                request_timeout=PROBE_REQUEST_TIMEOUT_S,
            )
        else:
            client = LangChainLLMClient(
                default_model=model_ref,
                api_key=api_key,
                request_timeout=PROBE_REQUEST_TIMEOUT_S,
            )
        probe = client.chat([ChatMessage(role="user", content="ping")])
        # LLMClientProtocol.chat 为 async 协程；防御探测桩返回非 awaitable 的边界
        if asyncio.iscoroutine(probe):
            await probe

    async def probe_embedding(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> int:
        """`embed_query("0")` 占位探测（#328 先例）；返回向量维度（失败抛异常）。"""
        from langchain_litellm import LiteLLMEmbeddings

        # #428 平移：统一 openai/ 前缀 + api_base（wire 裸 id 自动剥；key 明文 str）
        embeddings = LiteLLMEmbeddings(
            model=f"openai/{model.split('/', 1)[-1]}",
            api_key=api_key,
            api_base=base_url or None,
            request_timeout=PROBE_REQUEST_TIMEOUT_S,
        )
        vector: list[float] = await asyncio.to_thread(embeddings.embed_query, "0")
        return len(vector)
