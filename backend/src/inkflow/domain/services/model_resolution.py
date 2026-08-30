"""模型加载优先级单点收口（#735）— agent > 项目 > 全局，首个非空即用。

所有消费方统一经 `resolve_model` 解析模型，禁止散落 `or` 回退链。
"""

from __future__ import annotations


def resolve_model(
    agent_model: str | None = None,
    project_model: str | None = None,
    global_default: str | None = None,
) -> str | None:
    """模型加载优先级：agent > 项目 > 全局，首个非空即用；全空 → None。"""
    return agent_model or project_model or global_default or None
