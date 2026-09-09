"""F59-M5 (#966) 真实模型实证 ③ — dashscope enable_thinking 透传实测。

spec f59 §9.1 真实 AI ③：ADR-051 实证清单唯一推断项——dashscope 走 OpenAI 透传，
workspace 专属 OpenAI 兼容端点是否接受 reasoning_effort 参数（不被裁剪 / 不 400）。

端点：DASHSCOPE_API_BASE（默认
https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1，token-plan
workspace 专属）；模型：DASHSCOPE_MODEL 覆盖，默认 dashscope/qwen3.8-max。

实证修正（2026-09-09 真实 key 跑测，即本 issue 的证据）：workspace 端点没有
字面 qwen-plan 别名——spec §9.1 ③ 的命名是假设，实际请求抛
litellm.NotFoundError: DashscopeException - Model not exist；原始 curl 证明
qwen3.8-max → HTTP 200 OK（端点宣传的其他别名：qwen3.8-flash / glm-5.2 /
qwen3-coder-plus）。默认模型因此改为 qwen3.8-max；后续别名发现只需
DASHSCOPE_MODEL 环境变量覆盖，无需改代码。

装配说明（2026-09-09 本地实证，报告已登记；本文件不改生产代码）：
- InkFlow 探针 supports_reasoning_for_model("dashscope/qwen-plan")=False（litellm
  1.99 实测；该假别名已被上述实证否掉）→ 若经 LangChainLLMClient 工厂 + high，
  capability_probe.apply_reasoning_effort 会按 §5.5 软降级剥离参数——请求不带
  reasoning_effort，透传假设无从验证（qwen3.8-max 探针实测 True，但经工厂仍会
  被下一条顶层 kwargs 丢弃拦下，直连 ChatLiteLLM 的结论不变）；
- langchain-litellm ChatLiteLLM(0.7.1) pydantic extra=ignore 且无 reasoning_effort
  字段 → 顶层 kwargs 被静默丢弃（stub litellm.acompletion 实测收不到该参数）；
- litellm 1.99 check_valid_params 对 dashscope 判 reasoning_effort 不支持 → 直抛
  UnsupportedParamsError（除非 allowed_openai_params 显式放行）。
故本项经 ChatLiteLLM + model_kwargs（wrapper 唯一真正转发进 litellm 的通道）+
allowed_openai_params 放行，把 reasoning_effort=high 真实送到 workspace 端点——
隔离出「端点是否接受」这一推断项本身（InkFlow 侧参数通道缺陷另登记为生产 gap）。

断言：请求成功（HTTP 200 + 正文非空）。思考负载是否出现属 provider 行为，**刻意
不做硬断言**（会过度规定未知 provider 行为——这正是 issue 要记录的实证发现）；
以 pytest -s 打印 EVIDENCE 行记录 reasoning_content 出现与否。成本 1 次真实调用。
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage
from langchain_litellm import ChatLiteLLM

pytestmark = pytest.mark.e2e_ai

# 默认 qwen3.8-max（workspace 实证 200）；DASHSCOPE_MODEL 覆盖以便别名再发现。
MODEL = os.environ.get("DASHSCOPE_MODEL") or "dashscope/qwen3.8-max"
PROMPT = "用一句话回答：1+1=?"
REASONING_EFFORT = "high"
MAX_TOKENS = 200


@pytest.fixture(scope="module", autouse=True)
def _require_dashscope_key(dashscope_api_key: str) -> None:
    """module 级守门：无 dashscope key → 整模块 skip（缺 key 永远 skip 不 fail）。"""


def _text_content(message: object) -> str:
    """响应正文纯文本：str 原样；list 取 str 项与 type=="text" 块；其余空串。"""
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


def _reasoning_content(message: object) -> str:
    """响应思考内容（additional_kwargs reasoning_content / 直接属性）；无 → 空串。"""
    additional = getattr(message, "additional_kwargs", None)
    if isinstance(additional, dict):
        reasoning = additional.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            return reasoning
    reasoning_attr = getattr(message, "reasoning_content", None)
    if isinstance(reasoning_attr, str) and reasoning_attr:
        return reasoning_attr
    return ""


@pytest.mark.asyncio
async def test_dashscope_reasoning_effort_passthrough(
    dashscope_api_key: str, dashscope_api_base: str
) -> None:
    """workspace 端点接受带 reasoning_effort 的请求（HTTP 200 + 正文非空）。"""
    chat_model = ChatLiteLLM(
        model=MODEL,
        api_key=dashscope_api_key,
        api_base=dashscope_api_base,
        max_retries=1,
        request_timeout=45.0,
        max_tokens=MAX_TOKENS,
        model_kwargs={
            "reasoning_effort": REASONING_EFFORT,
            "allowed_openai_params": ["reasoning_effort"],
        },
    )
    response = await chat_model.ainvoke([HumanMessage(content=PROMPT)])

    content = _text_content(response)
    reasoning = _reasoning_content(response)
    assert content, (
        f"端点 {dashscope_api_base} 应接受 reasoning_effort=high 并返回正文；"
        "若 200 但正文空，换 DASHSCOPE_MODEL 探测其他 workspace 别名"
    )
    # 实证记录（pytest -s 可见）：reasoning 出现与否不决定 PASS/FAIL
    print(
        f"EVIDENCE dashscope model={MODEL} endpoint={dashscope_api_base} "
        f"reasoning_effort={REASONING_EFFORT} "
        f"content_len={len(content)} reasoning_present={bool(reasoning)}"
    )
