"""F59-M5 (#966) 真实模型实证 ② — deepseek 多轮思考回传不报错。

spec f59 §9.1 真实 AI ② / §5.2（litellm _fill_reasoning_content 自动补齐）/
§7 #8（DeepSeek 思考模式要求历史 reasoning_content 原样回传）。

第 1 轮 reasoning_effort=high 收 assistant 消息（含 additional_kwargs
reasoning_content）；第 2 轮 messages=[user1, assistant1(with reasoning),
user2] 原样回传 → 断言不抛错（litellm 自动补齐路径）且第 2 轮正文非空。
成本 2 次真实调用。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_litellm import ChatLiteLLM

from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.provider_config import get_provider_config, parse_model_string

pytestmark = pytest.mark.e2e_ai

MODEL = "deepseek/deepseek-v4-flash"
TURN1_PROMPT = "用一句话回答：1+1=?"
TURN2_PROMPT = "用一句话回答：2+2=?"
REASONING_EFFORT = "high"
MAX_TOKENS = 200


@pytest.fixture(scope="module", autouse=True)
def _require_deepseek_key(deepseek_api_key: str) -> None:
    """module 级守门：无 deepseek key → 整模块 skip（缺 key 永远 skip 不 fail）。"""


def _message_text(message: object) -> str:
    """消息正文纯文本（镜像 _content_text 消费面归一）：str 原样；list 取 str 项
    与 type=="text" 块的 text/content 键；其余形态空串。"""
    content = getattr(message, "content", "")
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


def _message_reasoning(message: object) -> str:
    """消息思考内容（实证形态：additional_kwargs reasoning_content 优先，其次
    直接属性）；无思考 → 空串。"""
    additional = getattr(message, "additional_kwargs", None)
    if isinstance(additional, dict):
        reasoning = additional.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            return reasoning
    reasoning_attr = getattr(message, "reasoning_content", None)
    if isinstance(reasoning_attr, str) and reasoning_attr:
        return reasoning_attr
    return ""


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
async def test_deepseek_multiturn_reasoning(deepseek_api_key: str) -> None:
    """第 2 轮带首轮 reasoning_content 回传：不报错且正文非空。"""
    chat_model = _build_chat_model(deepseek_api_key)

    first = await chat_model.ainvoke([HumanMessage(content=TURN1_PROMPT)])
    reasoning1 = _message_reasoning(first)
    text1 = _message_text(first)
    assert reasoning1, "第 1 轮 high 必须返回 reasoning_content（多轮回传的前置条件）"
    assert text1, "第 1 轮正文应非空"

    second = await chat_model.ainvoke(
        [
            HumanMessage(content=TURN1_PROMPT),
            AIMessage(
                content=text1,
                additional_kwargs={"reasoning_content": reasoning1},
            ),
            HumanMessage(content=TURN2_PROMPT),
        ]
    )
    text2 = _message_text(second)
    assert text2, (
        "第 2 轮带首轮 reasoning_content 回传必须成功且正文非空"
        "（litellm _fill_reasoning_content 自动补齐路径）"
    )
