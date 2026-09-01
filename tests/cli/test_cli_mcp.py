"""F20 inkflow-mcp stdio 协议真实内核轨（M4 验收）— spec §9.2/§13（Issue #49，RED 阶段测试契约）。

真实内核轨：真实 ensure_kernel 拉起内核进程（F30）→ mcp client SDK
（stdio_client + ClientSession）连接 `python -m inkflow.mcp` 子进程 →
initialize → tools/list → tools/call 端到端。对齐 F38 test_cli_http_kernel.py
真实内核轨模式（state_file 显式注入 tmp_path + INKFLOW_DATA_DIR 隔离 + teardown
taskkill 进程树 + CI 环境跳过——GitHub Actions 沙箱拉起内核秒退先例）。

── GREEN 实现契约 ────────────────────────────────────────────────
1. `python -m inkflow.mcp`（inkflow.mcp.__main__）与 console script
   `inkflow-mcp`（pyproject [project.scripts] inkflow-mcp = "inkflow.mcp.server:run"）
   均可启动 stdio server（mcp 2.0：stdio_server() → server.run(rs, ws,
   create_initialization_options())）。
2. 启动时**不主动** ensure_kernel（惰性，首次 tools/call 前）；tools/list 不触发
   内核（纯装配，spec §7 #14）。
3. initialize → server_info.name == "inkflow"；tools/list → 恰好 15 工具；
   tools/call manage_project list → 信封 {"ok": true, "data": {"items": [...]}}。
4. 冷启动链路：内核未运行 → tools/call → ensure_kernel 自动拉起 → 调用成功
   （spec §5.2/§7 #1；本文件用例 5 验证无内核自动拉起）。

── RED 形态说明 ─────────────────────────────────────────────────
inkflow.mcp 模块不存在 → 用例体 lazy import 抛 ModuleNotFoundError → FAILED
（预期 RED；GREEN 落地后自动转绿）。本文件不顶部 import inkflow.mcp（测试
经 subprocess 启动，import 面断言在 unit 层覆盖）。

── 测试约定 ─────────────────────────────────────────────────────
- 真实内核冷启动 ~4.7s：module-scope fixture 一次拉起，多个用例共享。
- 隔离：state_file 显式注入 tmp_path；INKFLOW_DATA_DIR 指向 tmp（子进程
  SQLite/chroma 不落 worktree）；mcp server 子进程 env 继承隔离变量。
- teardown：taskkill 内核进程树 + 恢复环境变量原值（防 CI 内核泄漏）。
- ⚠️ CI 环境跳过（2026-08-09 PR #213 实测）：GitHub Actions Windows runner
  沙箱（Session 0）中 `sys.executable -m inkflow serve` 拉起后秒退；本机
  Windows 11 正常。对齐 spec §9.3「M5 延迟验证不入常规 CI」。
- async 用例显式 @pytest.mark.asyncio（pytest-asyncio 1.x STRICT）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from inkflow.infrastructure.kernel import ensure_kernel, state

if TYPE_CHECKING:
    from mcp.client.stdio import StdioServerParameters

_KERNEL_TIMEOUT = 60.0


def _kill_kernel_tree(pid: int) -> None:
    """可靠终止内核进程树（Windows taskkill /T /F；best-effort，已死进程容忍）。"""
    if pid <= 0:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )


def _skip_ci() -> bool:
    """GitHub Actions 沙箱无法拉起真实内核（秒退）→ CI 跳过。"""
    return os.environ.get("CI") == "true"


@pytest.fixture(scope="module")
def mcp_env(tmp_path_factory):
    """module-scope：拉起真实内核 + 提供 mcp server 子进程启动参数。

    隔离：state_file 显式注入 tmp_path（不碰真实 kernel.json）；INKFLOW_DATA_DIR
    指向 tmp（serve 子进程 SQLite/chroma 不落 worktree）；mcp 子进程 env 继承。
    teardown：taskkill 内核进程树 + 恢复环境变量原值。
    """
    state_file = tmp_path_factory.mktemp("kernel") / "kernel.json"
    child_data_dir = tmp_path_factory.mktemp("kernel-data")
    prev_data_dir = os.environ.get("INKFLOW_DATA_DIR")
    os.environ["INKFLOW_DATA_DIR"] = str(child_data_dir)
    handle = None
    try:
        handle = asyncio.run(
            ensure_kernel(state_file=state_file, timeout=_KERNEL_TIMEOUT)
        )
        yield SimpleNamespace(
            handle=handle,
            state_file=state_file,
            data_dir=child_data_dir,
        )
    finally:
        if handle is not None:
            _kill_kernel_tree(handle.pid)
        if prev_data_dir is None:
            os.environ.pop("INKFLOW_DATA_DIR", None)
        else:
            os.environ["INKFLOW_DATA_DIR"] = prev_data_dir


def _server_params(env: SimpleNamespace) -> StdioServerParameters:
    """mcp server 子进程启动参数（python -m inkflow.mcp，继承隔离 env）。

    🔴 返回 StdioServerParameters **对象**（mcp 2.0 client 要求位置传参，
    `**` 展开对象会 TypeError——Codex GREEN 2026-08-16 实测）。
    """
    from mcp.client.stdio import StdioServerParameters

    child_env = os.environ.copy()
    child_env["INKFLOW_DATA_DIR"] = str(env.data_dir)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "inkflow.mcp"],
        env=child_env,
    )


@pytest.mark.skipif(
    _skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）；本机 M4 验证"
)
class TestMcpStdioRealKernel:
    """真实内核 stdio 协议端到端（M4，spec §9.2）。"""

    @pytest.mark.asyncio
    async def test_initialize_and_list_tools(self, mcp_env):
        """initialize → server_info.name=inkflow；tools/list 恰好 15 工具。"""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        async with (
            stdio_client(_server_params(mcp_env)) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            init = await session.initialize()
            assert init.server_info.name == "inkflow"
            result = await session.list_tools()
            assert len(result.tools) == 15

    @pytest.mark.asyncio
    async def test_call_tool_manage_project_list(self, mcp_env):
        """tools/call manage_project list → 信封 ok=true + data.items（真实内核 HTTP）。"""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        async with (
            stdio_client(_server_params(mcp_env)) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool("manage_project", {"action": "list"})
            assert result.is_error is False
            env = json.loads(result.content[0].text)
            assert env["ok"] is True
            assert "items" in env["data"]


@pytest.mark.skipif(
    _skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）；本机 M4 验证"
)
class TestColdStart:
    """冷启动链路（spec §5.2/§7 #1）：无内核 → tools/call 自动拉起。"""

    @pytest.mark.asyncio
    async def test_no_kernel_auto_start(self, tmp_path_factory):
        """独立 tmp：无 kernel.json → MCP 工具调用自动拉起内核 → 调用成功。"""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        data_dir = tmp_path_factory.mktemp("cold-data")
        child_env = os.environ.copy()
        child_env["INKFLOW_DATA_DIR"] = str(data_dir)
        assert not (data_dir / "kernel.json").exists()

        handle_pid = None
        try:
            from mcp.client.stdio import StdioServerParameters

            async with (
                stdio_client(
                    StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "inkflow.mcp"],
                        env=child_env,
                    )
                ) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                result = await session.call_tool("manage_project", {"action": "list"})
                assert result.is_error is False
                env = json.loads(result.content[0].text)
                assert env["ok"] is True
                # 内核已被 MCP 侧 ensure_kernel 自动拉起
                st = state.read_kernel_state(data_dir / "kernel.json")
                assert st is not None
                assert st.pid > 0
                handle_pid = st.pid
        finally:
            if handle_pid:
                _kill_kernel_tree(handle_pid)


# ── 错误自愈契约（ADR-048 §4，S2）────────────────────────────────────────────
# tools/call 失败 error 应为结构化对象 {code, message, hint}（LLM 可续用），
# 不裸抛纯文本。当前实现 error 为字符串 → 本类用例在 RED 阶段 FAIL。
# CI 沙箱无法拉起真实内核（同 module-scope 先例）→ skipif；本地黑盒验证。


@pytest.mark.skipif(
    _skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）；本机 M4 验证"
)
class TestMcpStdioErrorSelfHeal:
    """真实 stdio 轨：错误自愈契约（unknown tool / invalid args → 结构化 error）。"""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_structured_error(self, mcp_env):
        """tools/call 未知工具 → error{code:UNKNOWN_TOOL, message, hint}（LLM 可续用）。"""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        async with (
            stdio_client(_server_params(mcp_env)) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool("no_such_tool", {})
            assert result.is_error is True
            env = json.loads(result.content[0].text)
            assert env["ok"] is False
            err = env["error"]
            # 🔴 error 必须是对象（当前为纯文本字符串 → 本断言 FAIL → RED）
            assert isinstance(err, dict)
            assert err["code"] == "UNKNOWN_TOOL"
            assert err["message"]
            assert err["hint"]
            assert "manage_project" in err["hint"]

    @pytest.mark.asyncio
    async def test_invalid_action_returns_structured_error(self, mcp_env):
        """tools/call 参数错（非法 action）→ error{code:INVALID_ARGS, message, hint}。"""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        async with (
            stdio_client(_server_params(mcp_env)) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool("manage_project", {"action": "frobnicate"})
            assert result.is_error is True
            env = json.loads(result.content[0].text)
            err = env["error"]
            assert isinstance(err, dict)
            assert err["code"] == "INVALID_ARGS"
            assert err["message"]
            assert err["hint"]
