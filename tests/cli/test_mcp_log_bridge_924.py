"""#924 MCP 日志桥接 — 真实内核集成契约（M1/M2 验收面，RED 测试）。

缺陷（issue #924）：MCP 进程日志落 stderr 不进内核 StructuredLogStore →
GET /api/v1/logs?caller_type=mcp 恒 total=0，GUI 日志页「内核」分类 MCP 盲区。

验收链（issue M1→M2）：
  真实 stdio 子进程（python -m inkflow.mcp，INKFLOW_DATA_DIR 隔离）完成
  tools/call → 查询**同一内核** GET /api/v1/logs?caller_type=mcp →
  total>0 且包含该操作记录（event=工具名 / caller_name=inkflow-mcp）。

RED 预期（main@242cf37）：桥接不存在 → mcp 记录恒 0 → 核心用例 FAIL。
旁证断言（防假绿）：同一查询窗口 api 类记录 >0（MCP 写操作确实在内核留痕，
只是 mcp 分类空）——若 api 也 0 说明内核/数据目录装配坏，先报装配失败。

── 测试约定（镜像 test_mcp_tool_surface_retest_866.py，spec 自包含 #140）──
- module-scope 一次拉起真实内核（ensure_kernel state_file/data_dir 隔离 tmp）。
- ⚠️ CI 跳过（GitHub Actions 沙箱拉内核秒退）；裁判在本地，CI 只保证收集。
- 断言用轮询（桥接 flush 在 call 返回前同步完成，但 HTTP 落盘→查询留 2s 余量）。
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

from inkflow.infrastructure.kernel import ensure_kernel

if TYPE_CHECKING:
    from mcp.client.stdio import StdioServerParameters

_KERNEL_TIMEOUT = 60.0
_POLL_DEADLINE_S = 5.0


def _kill_kernel_tree(pid: int) -> None:
    if pid <= 0:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )


def _skip_ci() -> bool:
    return os.environ.get("CI") == "true"


@pytest.fixture(scope="module")
def bridge_env(tmp_path_factory):
    """module-scope：隔离数据目录拉起真实内核（不预置任何日志记录）。"""
    state_file = tmp_path_factory.mktemp("kernel") / "kernel.json"
    child_data_dir = tmp_path_factory.mktemp("kernel-data")
    prev = os.environ.get("INKFLOW_DATA_DIR")
    os.environ["INKFLOW_DATA_DIR"] = str(child_data_dir)
    handle = None
    try:
        handle = asyncio.run(
            ensure_kernel(state_file=state_file, timeout=_KERNEL_TIMEOUT)
        )
        yield SimpleNamespace(handle=handle, state_file=state_file, data_dir=child_data_dir)
    finally:
        if handle is not None:
            _kill_kernel_tree(handle.pid)
        if prev is None:
            os.environ.pop("INKFLOW_DATA_DIR", None)
        else:
            os.environ["INKFLOW_DATA_DIR"] = prev


def _server_params(env: SimpleNamespace) -> StdioServerParameters:
    from mcp.client.stdio import StdioServerParameters

    child_env = os.environ.copy()
    child_env["INKFLOW_DATA_DIR"] = str(env.data_dir)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "inkflow.mcp"],
        env=child_env,
    )


async def _mcp_call(env: SimpleNamespace, tool: str, params: dict) -> dict:
    """新开 stdio 连接调用一次工具（与被测桥接同进程生命周期）。"""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    async with (
        stdio_client(_server_params(env)) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, params)
    assert result.content and isinstance(result.content[0].text, str)
    return json.loads(result.content[0].text)


def _query_mcp_logs(env: SimpleNamespace, caller_type: str = "mcp") -> dict:
    import httpx

    base = f"http://127.0.0.1:{env.handle.port}"
    headers = {"X-InkFlow-Token": env.handle.token}
    with httpx.Client(base_url=base, headers=headers, timeout=10.0) as client:
        r = client.get("/api/v1/logs", params={"caller_type": caller_type, "limit": 100})
        r.raise_for_status()
        return r.json()


def _poll_mcp_records(env: SimpleNamespace, *, expect_event: str) -> dict:
    """轮询直至 caller_type=mcp 出现 expect_event 或超时；返回最后一次响应 data。"""
    import time

    deadline = time.monotonic() + _POLL_DEADLINE_S
    data: dict = {}
    while True:
        data = _query_mcp_logs(env)["data"]
        events = {item.get("event") for item in data.get("items", [])}
        if expect_event in events or time.monotonic() >= deadline:
            return data
        time.sleep(0.25)


@pytest.mark.skipif(_skip_ci(), reason="GitHub Actions 沙箱拉内核秒退；#924 桥接验收在本地轨")
class TestMcpLogBridgeIntegration:
    """M1：MCP 操作日志进内核 store；M2：GET /logs?caller_type=mcp total>0。"""

    @pytest.mark.asyncio
    async def test_mcp_tool_call_visible_in_kernel_store(self, bridge_env: SimpleNamespace) -> None:
        envelope = await _mcp_call(bridge_env, "manage_project", {"action": "list"})
        assert envelope.get("ok") is True, envelope

        data = _poll_mcp_records(bridge_env, expect_event="manage_project")
        assert data["total"] > 0, (
            "#924 核心判据：MCP tools/call 后 caller_type=mcp 仍恒空（桥接缺失）"
        )
        item = next(i for i in data["items"] if i["event"] == "manage_project")
        assert item["caller_type"] == "mcp"
        assert item["caller_name"] == "inkflow-mcp"
        assert item["level"] == "INFO"
        assert item["message_key"] == "log.event.mcp_tool_call"

    @pytest.mark.asyncio
    async def test_failed_mcp_call_recorded_as_warn(self, bridge_env: SimpleNamespace) -> None:
        envelope = await _mcp_call(bridge_env, "no_such_tool_924", {})
        assert envelope.get("ok") is False
        data = _poll_mcp_records(bridge_env, expect_event="no_such_tool_924")
        item = next(i for i in data["items"] if i["event"] == "no_such_tool_924")
        assert item["level"] == "WARN"
        assert item["error_code"] == "UNKNOWN_TOOL"

    @pytest.mark.asyncio
    async def test_write_operation_auditable_with_project(
        self, bridge_env: SimpleNamespace
    ) -> None:
        """审计闭环（M3）：建项目 → 记录带 project_id 可过滤回查。"""
        created = await _mcp_call(
            bridge_env,
            "manage_project",
            {"action": "create", "name": "924桥接审计", "language": "zh-CN"},
        )
        assert created.get("ok") is True, created
        project_id = created["data"]["id"]

        await _mcp_call(bridge_env, "manage_chapter", {"action": "list", "project_id": project_id})
        data = _poll_mcp_records(bridge_env, expect_event="manage_chapter")
        item = next(i for i in data["items"] if i["event"] == "manage_chapter")
        # UUID project_id → 顶层不猜 int（契约 §4），值保留在 params（GUI 过滤回查面）
        assert item["params"]["project_id"] == project_id

    @pytest.mark.asyncio
    async def test_api_records_present_as_side_evidence(self, bridge_env: SimpleNamespace) -> None:
        """旁证防假绿：同窗口 api 类记录 >0（内核埋点正常，仅 mcp 分类是缺陷面）。"""
        await _mcp_call(bridge_env, "tool_search", {"action": "list"})
        api_data = _query_mcp_logs(bridge_env, caller_type="api")["data"]
        assert api_data["total"] > 0, "内核 api 记录也空——装配/数据目录异常，本文件判据失效"

    @pytest.mark.asyncio
    async def test_stdout_discipline_holds(self, bridge_env: SimpleNamespace) -> None:
        """F20 硬约束回归：桥接后 tools/call 会话仍正常（协议帧未受污染即连接成功）。"""
        envelope = await _mcp_call(bridge_env, "tool_search", {"action": "list"})
        assert envelope.get("ok") is True
