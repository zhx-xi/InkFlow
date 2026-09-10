"""deepagents 装配层 — ChatLiteLLM 实例直传 create_deep_agent（litellm 多 Provider，
ADR-051，取代 ADR-005v2）.

模型名经 provider_config.litellm_model_name 口径校准（zhipu/glm-4.5 → zai/glm-4.5，
不剥离前缀）后构造 ChatLiteLLM，领域 Tool 映射为 StructuredTool，默认文件系统
工具与 subagent（task 工具）禁用。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeAlias, cast

from deepagents import create_deep_agent
from langchain_core.tools import StructuredTool
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from inkflow.infrastructure.agent.deepagents.profiles import ensure_profile
from inkflow.infrastructure.agent.tools import Tool
from inkflow.infrastructure.llm.capability_probe import (
    apply_reasoning_effort,
    to_chat_model_kwargs,
)
from inkflow.infrastructure.llm.provider_config import (
    litellm_model_name,
    resolve_reasoning_manual,
)

# deepagents 0.7.5 的 create_deep_agent 返回 CompiledStateGraph；任务契约将该返回值
# 类型记作 Agent，此处以 TypeAlias 对齐（--follow-imports=skip 下解析为 Any，语义仍清晰）
Agent: TypeAlias = CompiledStateGraph


def _litellm_model_name(model: str, base_url: str) -> str:
    """registry/全名 → litellm 模型名（zhipu/glm-4.5 → zai/glm-4.5，ADR-051 口径
    校准）；base_url 透传（ollama 带 http(s) base_url → openai/ 兼容形态，
    #962）；无前缀裸名（parse ValueError 防御路径）→ 原样返回。"""
    return litellm_model_name(model, base_url)


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
    reasoning_effort: str | None = None,
) -> Agent:
    """构建 deepagents 编排 Agent（ChatLiteLLM 直传，多 Provider 兼容，ADR-051）.

    profile_key 缺省时确保 "litellm:<口径映射后模型全名>" HarnessProfile 已注册
    （deepagents 对预构建 ChatLiteLLM 实例按 ls_provider='litellm' + model 全名
    解析 profile，键不命中则默认 FS 工具禁用静默失效——安全面）；显式传入则原样
    使用、不抛错。

    reasoning_effort: F59 可选思考档位——经 apply_reasoning_effort 注入
    ChatLiteLLM kwargs（default/None 不发送；超能力软降级见 §5.5）。
    """
    mapped_model = _litellm_model_name(model, base_url)
    chat_kwargs: dict[str, object] = {
        "model": mapped_model,
        "temperature": 0.2,
    }
    if api_key:
        chat_kwargs["api_key"] = api_key
    if base_url:
        chat_kwargs["api_base"] = base_url
    # #1039：档位可行动时才查注册表手动覆盖（None/"default" 不查——构造点在每条链上）
    manual = (
        resolve_reasoning_manual(model)
        if reasoning_effort not in (None, "default")
        else None
    )
    decision = apply_reasoning_effort(
        chat_kwargs,
        model_full=mapped_model,
        effort=reasoning_effort,
        manual=manual,
    )
    if manual is True and "reasoning_effort" in decision:
        # Q1=A：litellm 对表 False 模型本地门禁直抛 UnsupportedParamsError → manual
        # 注入必须同带旁路（仅随显式覆盖出现，自动路径零变化）
        decision["allowed_openai_params"] = ["reasoning_effort"]
    chat_kwargs = to_chat_model_kwargs(decision)
    chat = ChatLiteLLM(**chat_kwargs)  # type: ignore[arg-type]  # chat_kwargs 为动态 dict[str, object]，无法静态匹配 ChatLiteLLM pydantic 构造参数
    if profile_key is None:
        ensure_profile(mapped_model)
    return create_deep_agent(
        model=chat,
        tools=_map_tools(tools),
        system_prompt=system_prompt,
        checkpointer=InMemorySaver(),
    )
