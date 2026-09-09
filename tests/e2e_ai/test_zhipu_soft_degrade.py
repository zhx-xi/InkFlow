"""F59-M5 (#966) 真实模型实证 ④ — zhipu glm-4.5 超能力软降级 + WARNING。

spec f59 §3.3 异常表行 2 / §5.5 / §12 D5（Q1=A 拍板：档位 > 模型能力 → 剥离参数发起调用 +
loguru WARNING，不断流不 422）/ §13 M5 行。zhipu→zai 前缀口径实证：
litellm 1.99 provider_list 含 zai 不含 zhipu（provider_config.py 口径表）；
supports_reasoning_for_model("zai/glm-4.5")=False（litellm 模型表 + provider
params 两级均无）→ 请求 high 时 capability_probe.apply_reasoning_effort 剥离
reasoning_effort 并发 WARNING（锚文本见 capability_probe.py 源码 message）。

走项目公共客户端（LangChainLLMClient.chat，真实 key + 真实端点）：断言调用成功
（无异常 + 正文非空）且 WARNING 锚文本出现在 loguru 输出。成本 1 次真实调用。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

pytestmark = pytest.mark.e2e_ai

MODEL = "zhipu/glm-4.5"
PROMPT = "用一句话回答：1+1=?"
REASONING_EFFORT = "high"
MAX_TOKENS = 200
# capability_probe.apply_reasoning_effort 软降级 WARNING 的精确锚文本
# （message=f"reasoning effort downgraded: model={model_full} effort={effort}"，
# zhipu 注册 provider 经口径映射后 full_model 为 zai/glm-4.5）
WARN_ANCHOR = "reasoning effort downgraded: model=zai/glm-4.5 effort=high"


def _record_level_name(record: dict) -> str:
    """loguru record 级别名：RecordLevel 取 .name（record["level"] 非嵌套 dict、
    plain str level 则原样返回，防御未知形状）。"""
    level = record.get("level")
    name = getattr(level, "name", None)
    if name is not None:
        return str(name)
    return str(level)


@pytest.fixture(scope="module", autouse=True)
def _require_zhipu_key(zhipu_api_key: str) -> None:
    """module 级守门：无 zhipu key → 整模块 skip（缺 key 永远 skip 不 fail）。"""


@pytest.fixture
def loguru_records() -> Iterator[list[dict]]:
    """loguru WARNING 级捕获 sink（test_capability_probe.loguru_records 同款）。"""
    from loguru import logger

    records: list[dict] = []
    sink_id = logger.add(
        lambda message: records.append(message.record),
        level="WARNING",
        format="{message}",
    )
    yield records
    logger.remove(sink_id)


@pytest.mark.asyncio
async def test_zhipu_reasoning_effort_soft_degrade(
    zhipu_api_key: str, loguru_records: list[dict]
) -> None:
    """glm-4.5 + high：调用成功（剥离后发起）+ 软降级 WARNING 锚文本落日志。"""
    client = LangChainLLMClient(api_key=zhipu_api_key, default_model=MODEL)

    response = await client.chat(
        [ChatMessage(role="user", content=PROMPT)],
        model=MODEL,
        max_tokens=MAX_TOKENS,
        reasoning_effort=REASONING_EFFORT,
    )

    assert response.content.strip(), "glm-4.5 软降级后调用应成功且正文非空"
    matched = [
        record
        for record in loguru_records
        if _record_level_name(record) == "WARNING"
        and WARN_ANCHOR in str(record.get("message", ""))
    ]
    assert matched, (
        f"软降级必须留下 WARNING（锚文本 {WARN_ANCHOR!r} 未出现在 loguru 输出）"
    )
