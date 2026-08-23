"""对话输入机密脱敏 —— `redact_secrets` 纯函数 + `load_known_keys` 工具（spec §3.1/§3.2）。"""

from __future__ import annotations

import re

from inkflow.core.config import config
from inkflow.infrastructure.llm.key_manager import APIKeyManager

_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_-]+")
_LONG_RUN_PATTERN = re.compile(r"[A-Za-z0-9_-]{24,}")


def redact_secrets(prompt: str, known_keys: list[str] | None = None) -> str:
    """把 prompt 内常见密钥形态与已存密钥替换为 '****'。

    A（正则兜底）：
      - sk- 后接 >=12 位 [A-Za-z0-9_-] -> 保留 'sk-' 前缀 + '****'
      - Bearer 后接 token -> token 替换 '****'，保留 'Bearer ' 前缀
      - 连续 >=24 位 [A-Za-z0-9_-]（疑似 token）-> 整体 '****'
    B（已存密钥）：known_keys 非空时逐个明文字符串子串替换。
    """
    result = _SK_PATTERN.sub("sk-****", prompt)
    result = _BEARER_PATTERN.sub(r"\1****", result)
    result = _LONG_RUN_PATTERN.sub("****", result)
    for key in known_keys or []:
        result = result.replace(key, "****")
    return result


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
