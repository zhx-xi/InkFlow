"""F57-S2 显式 checkpoint — LLM DEBUG 请求/响应摘要契约测试（spec §4.1 语义层）。

契约来源
--------
specs/f57-logging-i18n/spec.md §4（LLM 调用 DEBUG=请求/响应摘要）+ §4.1（显式
checkpoint DEBUG 步骤级：LLM 请求/响应摘要）。

设计假设（GREEN 必须满足）
--------------------------
LangChainLLMClient.chat() 成功路径上，除装饰器结构日志（log.call.chat，由 @instrument
产出，caller_type="llm"）外，还须有**显式语义 checkpoint**：

1. 至少一条 DEBUG 记录 extra.caller_type == "llm" 且 extra.message_key 以
   "log.event.llm_" 开头（推荐 log.event.llm_request / log.event.llm_response）。
2. **摘要脱敏铁律**：该 DEBUG 记录 extra["params"] 序列化后不得包含消息原文
   （prompt 全文不进日志，只进摘要类字段如 count / 截断长度等）。
3. 不要求具体 params 键名（GREEN 自由度），只锁键前缀 + 原文不外泄。

RED 预期：checkpoint 未铺开 → 无 log.event.llm_* DEBUG → 失败。
"""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from loguru import logger

from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

# 长 prompt 全文（用于断言不外泄）；含敏感形态
_PROMPT_TEXT = (
    "请把以下机密写进故事：api_key=sk-" + "A" * 32
    + " 以及这段足够长的提示词原文摘要测试" * 3
)


@pytest.fixture(autouse=True)
def _restore_loguru():
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture():
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level="DEBUG", format="{message}")
    return records, sid


class TestLLMDebugDigest:
    @pytest.mark.asyncio
    async def test_chat_emits_debug_llm_digest(self) -> None:
        client = LangChainLLMClient(default_model="openai/gpt-4o")
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(
            return_value=AIMessage(content="好的", response_metadata={"model_name": "gpt-4o"})
        )
        client._get_chat_model = MagicMock(return_value=mock_model)
        fake_cfg = MagicMock()
        fake_cfg.api_key = "sk-provider-key-must-not-log"
        fake_cfg.base_url = "https://example.invalid"

        records, sid = _capture()
        try:
            with patch(
                "inkflow.infrastructure.llm.langchain_client.get_provider_config",
                return_value=fake_cfg,
            ):
                resp = await client.chat([ChatMessage(role="user", content=_PROMPT_TEXT)])
        finally:
            logger.remove(sid)
        assert resp.content == "好的"

        digests = [
            r
            for r in records
            if r["level"].name == "DEBUG"
            and r["extra"].get("caller_type") == "llm"
            and str(r["extra"].get("message_key", "")).startswith("log.event.llm_")
        ]
        assert digests, (
            "chat() 成功路径应发显式 DEBUG 摘要（caller_type=llm，message_key=log.event.llm_*）；"
            "实际 DEBUG keys="
            f"{[r['extra'].get('message_key') for r in records if r['level'].name == 'DEBUG']}"
        )
        # 摘要不外泄消息原文 / provider key（log_structured.mask_fields 兜底 + 摘要本身克制）
        blob = json.dumps([dict(r["extra"]) for r in digests], ensure_ascii=False, default=str)
        assert "机密写进故事" not in blob, "DEBUG 摘要不得包含 prompt 原文"
        assert _PROMPT_TEXT[:40] not in blob, "DEBUG 摘要不得包含 prompt 原文前缀"
        assert "sk-provider-key-must-not-log" not in blob, "DEBUG 摘要不得泄漏 provider key"

    @pytest.mark.asyncio
    async def test_decorator_call_record_present(self) -> None:
        """@instrument 结构层与显式语义层共存：log.call.chat DEBUG 也在（回归护栏）。"""
        client = LangChainLLMClient(default_model="openai/gpt-4o")
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(
            return_value=AIMessage(content="ok", response_metadata={"model_name": "gpt-4o"})
        )
        client._get_chat_model = MagicMock(return_value=mock_model)

        records, sid = _capture()
        try:
            with patch(
                "inkflow.infrastructure.llm.langchain_client.get_provider_config",
                return_value=MagicMock(api_key="", base_url=""),
            ):
                await client.chat([ChatMessage(role="user", content="hi")])
        finally:
            logger.remove(sid)
        calls = [
            r
            for r in records
            if r["extra"].get("message_key") == "log.call.chat"
            and r["level"].name == "DEBUG"
        ]
        assert calls, "装饰器 log.call.chat DEBUG 入口记录须存在"
        assert calls[0]["extra"]["caller_type"] == "llm"
