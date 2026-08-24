"""F50 LangSmith 追踪 — env 解析与注入（横切可观测性）。

默认关闭；仅 langsmith_enabled=True 且 api_key 非空时注入 LANGSMITH_* env。
"""

from __future__ import annotations

import os

from loguru import logger

from inkflow.core.config import InkFlowConfig, config

# 本模块管理的 LangSmith env 键（apply 时先 pop 再 update，幂等）
_LANGSMITH_ENV_KEYS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
)


def resolve_langsmith_trace_env(cfg: InkFlowConfig) -> dict[str, str]:
    """按 config 解析 LangSmith 追踪 env（纯函数，无外部副作用）。

    - langsmith_enabled=False → {}
    - enabled 但 api_key 为空 → {} + logger.warning（非致命）
    - enabled 且 key 非空 → {LANGSMITH_TRACING: "true", LANGSMITH_API_KEY: key,
      LANGSMITH_PROJECT: project or "inkflow"}；langsmith_endpoint 非空时追加
      LANGSMITH_ENDPOINT。
    """
    if not cfg.langsmith_enabled:
        return {}
    api_key = cfg.langsmith_api_key
    if not api_key:
        logger.warning("langsmith_enabled=True 但 langsmith_api_key 为空 — LangSmith 追踪未启用")
        return {}
    env = {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": api_key,
        "LANGSMITH_PROJECT": cfg.langsmith_project or "inkflow",
    }
    if cfg.langsmith_endpoint:
        env["LANGSMITH_ENDPOINT"] = cfg.langsmith_endpoint
    return env


def apply_langsmith_tracing(cfg: InkFlowConfig | None = None) -> None:
    """按 config 注入/清除 LangSmith env（有副作用，幂等；启动时调用）。

    先无条件 pop 4 键（清除残留/保证幂等），再按 resolve 结果 update。
    cfg 为 None 时用全局 config 单例。
    """
    effective = cfg if cfg is not None else config
    for k in _LANGSMITH_ENV_KEYS:
        os.environ.pop(k, None)
    env = resolve_langsmith_trace_env(effective)
    if env:
        os.environ.update(env)
        logger.info("LangSmith 追踪已启用 → project=%s", effective.langsmith_project or "inkflow")
