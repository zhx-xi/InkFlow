"""T1 (ADR-026)：LLM 客户端连通性 — 真实 key 最小请求。

验证：key 有效 / OpenAI 兼容协议 / 网络可达。断言宽松（非空），不断言内容。
"""

import pytest

from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_llm_connectivity(llm_env):
    """真实 key 最小请求：key 有效 / 协议兼容 / 网络可达。"""
    client = LangChainLLMClient(
        api_key=llm_env["api_key"], default_model=llm_env["model"]
    )

    resp = await client.chat(
        [ChatMessage(role="user", content="只回复两个字：正常")],
        model=llm_env["model"],
        max_tokens=20,
        temperature=0.0,
    )

    assert resp.content.strip()  # 非空（宽松断言）
    assert resp.model  # 回显模型名
