"""F59-M5 (#966) 真实模型实证 ① — deepseek-v4-flash 开 high 收到非空思考帧。

spec f59 §9.1 真实 AI ① / §13 M5 行 / ADR-051 D：ChatLiteLLM 把思考内容规范进
additional_kwargs["reasoning_content"]，流块可能另带 type=="thinking" 块。

装配走项目自有工厂链（LangChainLLMClient._get_chat_model → ChatLiteLLM：
provider_config 前缀口径 + capability_probe.apply_reasoning_effort 注入 high），
再以真实 astream 观察 HTTP/SSE 层流块。LangChainLLMClient.chat_stream 在消费面
把 content 归一化只透 text（_content_text），思考负载不进 StreamEvent，故必须
直取 ChatLiteLLM 原始流块断言（行为层，零 mock）。

断言：流中至少一个非空 reasoning payload（chunk additional_kwargs
reasoning_content 或 thinking 块）；拼接正文非空。成本 1 次真实调用。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langchain_litellm import ChatLiteLLM

from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.provider_config import get_provider_config, parse_model_string

pytestmark = pytest.mark.e2e_ai

MODEL = "deepseek/deepseek-v4-flash"
PROMPT = "用一句话回答：1+1=?"
REASONING_EFFORT = "high"
MAX_TOKENS = 200


@pytest.fixture(scope="module", autouse=True)
def _require_deepseek_key(deepseek_api_key: str) -> None:
    """module 级守门：无 deepseek key → 整模块 skip（缺 key 永远 skip 不 fail）。"""


def _text_from_chunk(chunk: object) -> str:
    """流块正文纯文本（消费面归一镜像 _content_text）：str 原样；list 取 str 项
    与 type=="text" 块的 text/content 键；其余形态空串。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            value = item.get("text")
            if value is None:
                value = item.get("content")
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)


def _reasoning_fragments(chunk: object) -> list[str]:
    """流块思考负载片段（实证形态：additional_kwargs reasoning_content、直接
    reasoning_content 属性、content 中 type=="thinking" 块）；无思考 → []。"""
    fragments: list[str] = []
    additional = getattr(chunk, "additional_kwargs", None)
    if isinstance(additional, dict):
        reasoning = additional.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            fragments.append(reasoning)
    reasoning_attr = getattr(chunk, "reasoning_content", None)
    if isinstance(reasoning_attr, str) and reasoning_attr:
        fragments.append(reasoning_attr)
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "thinking":
                value = item.get("thinking")
                if value is None:
                    value = item.get("content")
                if isinstance(value, str) and value:
                    fragments.append(value)
    return fragments


def _build_chat_model(api_key: str) -> ChatLiteLLM:
    """项目自有工厂链构建真实 ChatLiteLLM（真实 key + 真实端点，零 mock）。"""
    client = LangChainLLMClient(api_key=api_key)
    provider, model_name = parse_model_string(MODEL)
    provider_cfg = get_provider_config(provider, api_key=api_key)
    return client._get_chat_model(
        provider_cfg,
        model_name=model_name,
        max_tokens=MAX_TOKENS,
        reasoning_effort=REASONING_EFFORT,
    )


@pytest.mark.asyncio
async def test_deepseek_reasoning_frames(deepseek_api_key: str) -> None:
    """deepseek-v4-flash + high：真实流必须产出非空思考帧，且正文非空。"""
    chat_model = _build_chat_model(deepseek_api_key)
    reasoning_fragments: list[str] = []
    text_parts: list[str] = []
    chunk_count = 0
    async for chunk in chat_model.astream([HumanMessage(content=PROMPT)]):
        chunk_count += 1
        reasoning_fragments.extend(_reasoning_fragments(chunk))
        text = _text_from_chunk(chunk)
        if text:
            text_parts.append(text)

    reasoning = "".join(reasoning_fragments).strip()
    content = "".join(text_parts).strip()
    assert reasoning, (
        f"deepseek-v4-flash + high 应产出非空思考负载（共 {chunk_count} 块；"
        "additional_kwargs/thinking 块两形态均空）"
    )
    assert content, (
        f"deepseek-v4-flash 真实流正文应非空（共 {chunk_count} 块，思考负载非空但正文空）"
    )
