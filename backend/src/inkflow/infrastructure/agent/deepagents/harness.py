"""deepagents 装配层 — ChatOpenAI 实例直传 create_deep_agent（custom base_url 多 Provider）.

模型名剥离（zhipu/glm-4.5 → glm-4.5）后构造 ChatOpenAI，领域 Tool 映射为
StructuredTool，默认文件系统工具与 subagent（task 工具）禁用。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeAlias, cast

from deepagents import create_deep_agent
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from inkflow.infrastructure.agent.deepagents.profiles import ensure_profile
from inkflow.infrastructure.agent.tools import Tool
from inkflow.infrastructure.llm.provider_config import parse_model_string

# deepagents 0.7.5 的 create_deep_agent 返回 CompiledStateGraph；任务契约将该返回值
# 类型记作 Agent，此处以 TypeAlias 对齐（--follow-imports=skip 下解析为 Any，语义仍清晰）
Agent: TypeAlias = CompiledStateGraph


def _strip_model_prefix(model: str) -> str:
    """剥离 registry 前缀（zhipu/glm-4.5 → glm-4.5）；无前缀原样使用（防御）."""
    try:
        _, model_name = parse_model_string(model)
    except ValueError:
        return model
    return str(model_name)


def _map_tools(tools: list[Tool]) -> list[StructuredTool]:
    """将领域 Tool 映射为 deepagents 可消费的 StructuredTool（name/description 透传）.

    func + coroutine 双给：deepagents ToolNode sync 路径走 func（asyncio.run 桥接），
    async 路径走 coroutine——coroutine-only 会抛 NotImplementedError（M5 实测缺陷）。
    """
    mapped: list[StructuredTool] = []
    for tool in tools:
        mapped.append(
            StructuredTool.from_function(
                func=_make_sync_wrapper(tool.func),
                coroutine=tool.func,
                name=tool.spec.name,
                description=tool.spec.description,
                args_schema=tool.spec.input_schema,
            )
        )
    return mapped


def _make_sync_wrapper(async_fn: Callable[..., Awaitable[str]]) -> Callable[..., str]:
    """构造 sync 桥接 wrapper——async_fn 按参数绑定（每次调用独立闭包，避免循环变量共享）."""

    def _sync_wrapper(*args, **kwargs) -> str:
        # asyncio.run 要求 Coroutine，领域契约为 Awaitable——cast 桥接两类型
        return asyncio.run(cast(Coroutine[Any, Any, str], async_fn(*args, **kwargs)))

    return _sync_wrapper


def build_deep_agent(
    *,
    model: str,
    api_key: str,
    base_url: str,
    tools: list[Tool],
    system_prompt: str,
    profile_key: str | None = None,
) -> Agent:
    """构建 deepagents 编排 Agent（ChatOpenAI 直传，多 Provider 兼容）.

    profile_key 缺省时确保 "openai:<模型名>" HarnessProfile 已注册（禁用默认 FS 工具
    与 subagent）；显式传入则原样使用、不抛错。
    """
    model_name = _strip_model_prefix(model)
    chat = ChatOpenAI(
        model=model_name,
        openai_api_base=base_url,
        openai_api_key=api_key,
        temperature=0.2,
    )
    if profile_key is None:
        ensure_profile(model_name)
    return create_deep_agent(
        model=chat,
        tools=_map_tools(tools),
        system_prompt=system_prompt,
    )
