"""deepagents 装配层 — ChatOpenAI 实例直传 create_deep_agent（custom base_url 多 Provider）.

模型名剥离（zhipu/glm-4.5 → glm-4.5）后构造 ChatOpenAI，领域 Tool 映射为
StructuredTool，默认文件系统工具与 subagent（task 工具）禁用。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeAlias, cast

from deepagents import create_deep_agent
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
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
    async 路径走 coroutine——coroutine-only + sync invoke 抛 NotImplementedError
    （M5 探针实测仍成立，结论未过时：func 必须保留，不能只给 coroutine）。
    #953 C1：adapter（agentic_writer.DeepAgentInvokeAdapter）async 优先后，真实链路
    await graph.ainvoke → ToolNode async 路径 → coroutine 在宿主事件循环执行；
    sync invoke 兜底（CLI/MCP/MagicMock 鸭子回退）仍走 func sync 桥，本函数双给
    结构与 _make_sync_wrapper 行为保持不变（兜底路径）。
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
        coro = cast(Coroutine[Any, Any, str], async_fn(*args, **kwargs))
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中事件循环（普通 sync 线程）——asyncio.run 原路径
            return asyncio.run(coro)
        # 运行中事件循环（FastAPI/uvloop，打包版 ToolNode sync 路径）——不能 asyncio.run
        # （抛 RuntimeError），也不能 run_coroutine_threadsafe(...).result()（当前线程即循环所有者，
        # 会死锁）。改为在独立 worker 线程 + 新事件循环上运行到完成，阻塞返回结果/异常。
        loop = asyncio.new_event_loop()
        results: list[str] = []
        errors: list[BaseException] = []

        def _run() -> None:
            asyncio.set_event_loop(loop)
            try:
                results.append(loop.run_until_complete(coro))
            except BaseException as exc:  # 保留原始异常语义（工具失败向上传播）
                errors.append(exc)
            finally:
                loop.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        return results[0]

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
    chat_kwargs: dict[str, object] = {
        "model": model_name,
        "temperature": 0.2,
    }
    if api_key:
        chat_kwargs["openai_api_key"] = api_key
    if base_url:
        chat_kwargs["openai_api_base"] = base_url
    chat = ChatOpenAI(**chat_kwargs)  # type: ignore[arg-type]  # chat_kwargs 为动态 dict[str, object]，无法静态匹配 ChatOpenAI 构造参数（langchain-openai pydantic 签名，openai_api_* 为运行时别名）
    if profile_key is None:
        ensure_profile(model_name)
    return create_deep_agent(
        model=chat,
        tools=_map_tools(tools),
        system_prompt=system_prompt,
        checkpointer=InMemorySaver(),
    )
