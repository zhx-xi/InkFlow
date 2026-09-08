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


def resolve_reasoning_effort(
    request_effort: str | None = None,
    project_effort: str | None = None,
    global_effort: str | None = None,
) -> str:
    """调用 > 项目 > 全局，首个非 None 即用；全 None → "default"。"""
    for effort in (request_effort, project_effort, global_effort):
        if effort is not None:
            return effort
    return "default"
