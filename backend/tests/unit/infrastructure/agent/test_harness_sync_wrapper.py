"""#710 打包版 chat Agent 工具调用 sync 兜底 — _make_sync_wrapper 事件循环契约测试.

根因（已实证）：#710 打包版（PyInstaller frozen）deepagents chat Agent 工具调用失败——
SSE 无 tool_result 帧直接 error。实证根因在 _make_sync_wrapper
（infrastructure/agent/deepagents/harness.py L56-63）：LangGraph ToolNode 在已有事件循环
（FastAPI/uvloop）中调用工具 sync func 时，asyncio.run() 抛 RuntimeError
（asyncio.run() cannot be called from a running event loop）→ 工具执行失败 → 端点层
except Exception 产出「Agent 执行失败」。

dev 源码环境工具走 coroutine/ainvoke 路径正常；打包版环境触发 sync 路径失败。

本 RED 契约聚焦 _make_sync_wrapper 与 _map_tools：
- test_sync_wrapper_running_loop_returns_result（RED 焦点）：async 测试函数（运行中事件循环）
  内调用 sync wrapper → 当前实现 asyncio.run → RuntimeError FAILED（正确 RED）。
- test_map_tools_structure（回归护栏）：_map_tools 产出 StructuredTool 结构——
  coroutine=原始 async 函数、func=sync wrapper（双路径保持）。当前实现已满足 → PASS。
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.deepagents.harness import _make_sync_wrapper, _map_tools
from inkflow.infrastructure.agent.tools import Tool


async def _afn(*args, **kwargs) -> str:
    """领域工具最小的 async 实现（返回固定字符串，无副作用）。"""
    return "ok"


def _fake_tool() -> Tool:
    """构造最小真实 Tool——spec 可断言、func=async 函数（不执行）。"""
    return Tool(
        spec=ToolSpec(name="t", description="desc", input_schema={}),
        func=_afn,
    )


class TestMakeSyncWrapper:
    """_make_sync_wrapper 事件循环行为契约（#710 根因）。"""

    @pytest.mark.asyncio
    async def test_sync_wrapper_running_loop_returns_result(self) -> None:
        """运行中事件循环内调用 sync wrapper → 不抛 RuntimeError 且返回 async_fn 结果。

        RED：当前实现 asyncio.run(cast(..., async_fn(...))) 在运行中事件循环内抛
        RuntimeError（asyncio.run() cannot be called from a running event loop）→ FAILED。
        """
        wrapper = _make_sync_wrapper(_afn)
        result = wrapper()  # 在 async 测试函数（运行中事件循环）内调用
        assert result == "ok"


class TestMapToolsStructure:
    """_map_tools 产出 StructuredTool 的结构契约（回归护栏，当前已满足 → PASS）。"""

    def test_coroutine_is_original_async_func_and_func_is_sync_wrapper(self) -> None:
        """coroutine=原始 async 函数（async 路径）、func=sync wrapper（sync 路径）。

        双路径保持：deepagents ToolNode async 走 coroutine、sync 走 func。sync wrapper
        在无运行中事件循环的正常 sync 上下文可执行并返回结果。
        """
        mapped = _map_tools([_fake_tool()])
        assert len(mapped) == 1
        st = mapped[0]
        assert st.coroutine is _afn
        assert st.func is not _afn
        assert st.name == "t"
        assert st.description == "desc"
        assert st.func() == "ok"  # sync 上下文（无运行中事件循环）可执行
