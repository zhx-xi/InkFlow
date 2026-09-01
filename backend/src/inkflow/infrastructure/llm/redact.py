"""对话输入机密脱敏 —— `redact_secrets` 纯函数 + `load_known_keys` 工具（spec §3.1/§3.2）。"""

from __future__ import annotations

import re
from typing import TypeVar

from inkflow.core.config import config
from inkflow.domain.models.agent_run import AgentStep, AgentToolCall
from inkflow.infrastructure.llm.key_manager import APIKeyManager

_SK_PATTERN = re.compile(r"[Ss][Kk]-[A-Za-z0-9_-]{12,}")
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_-]+")
_LONG_RUN_PATTERN = re.compile(r"[A-Za-z0-9_-]{24,}")
_UNICODE_ESCAPE_PATTERN = re.compile(r"\\u[0-9a-fA-F]{4}")
_ScrubT = TypeVar("_ScrubT", str, dict, list)


def redact_secrets(prompt: str, known_keys: list[str] | None = None) -> str:
    """把 prompt 内常见密钥形态与已存密钥替换为 '****'。

    A（正则兜底）：
      - sk- 后接 >=12 位 [A-Za-z0-9_-] -> 保留 'sk-' 前缀 + '****'
      - Bearer 后接 token -> token 替换 '****'，保留 'Bearer ' 前缀
      - 连续 >=24 位 [A-Za-z0-9_-]（疑似 token）-> 整体 '****'
    B（已存密钥）：known_keys 非空时逐个明文字符串子串替换。
    """
    result = prompt
    # unescape 先于 known_keys：#632 要求 known_keys 整串替换先于长串正则，但若 stored key
    # 在 prompt 里以 \uXXXX 转义形态出现，必须先归一到字面字符才能被 known_keys/正则命中。
    result = _UNICODE_ESCAPE_PATTERN.sub(
        lambda m: chr(int(m.group(0)[2:], 16)), result
    )
    for key in known_keys or []:
        result = result.replace(key, "****")
    result = _SK_PATTERN.sub("sk-****", result)
    result = _BEARER_PATTERN.sub(r"\1****", result)
    return _LONG_RUN_PATTERN.sub("****", result)


def _redact_text(value: str) -> str:
    """窄脱敏（redact_step 专用）：仅遮蔽密钥信号——已存 key / sk- / Bearer。

    故意**不**用 redact_secrets 的 `_LONG_RUN_PATTERN`：那是「>=24 位连续 [A-Za-z0-9_-]」，
    会误伤 tool 参数里的 UUID（36 位 hex+连字符）/ID/字数等**合法结构化字段**。steps 是
    落库决策轨迹，必须保留这些标识符，只挡真正的密钥形态。
    """
    result = value
    for key in load_known_keys():
        result = result.replace(key, "****")
    result = _SK_PATTERN.sub("sk-****", result)
    return _BEARER_PATTERN.sub(r"\1****", result)


def _scrub_value(value: _ScrubT) -> _ScrubT:
    """递归脱敏 str/dict/list；其他类型原样保留。"""
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {key: _scrub_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    return value


def redact_step(step: AgentStep) -> AgentStep:
    """把 AgentStep 决策轨迹里所有可回显密钥的字段脱敏后返回
    （message_content/reasoning/tool_calls[].arguments/result）。"""
    tool_calls = [
        AgentToolCall(
            step_index=call.step_index,
            tool_name=call.tool_name,
            arguments=_scrub_value(call.arguments),
            result=_redact_text(call.result),
            is_error=call.is_error,
        )
        for call in step.tool_calls
    ]
    return AgentStep(
        index=step.index,
        message_content=_redact_text(step.message_content),
        reasoning=_redact_text(step.reasoning),
        tool_calls=tool_calls,
        tokens=step.tokens,
    )


def load_known_keys() -> list[str]:
    """读取已存所有 provider 的明文 key；单个读取/解密失败时跳过，不抛错。"""
    manager = APIKeyManager(
        secret_key=config.secret_key,
        storage_dir=config.data_dir / "keys",
    )
    keys: list[str] = []
    for provider in manager.list_providers():
        try:
            keys.append(manager.load(provider))
        except Exception:
            continue
    return keys
