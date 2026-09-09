"""#933 新工具 MCP stdio 全链路（issue #933 验收 A9/A10/A11，spec f20 §13）。

两条轨：

1. **非 LLM 轨**（本机可跑，CI 跳过——同 `test_cli_mcp.py` 沙箱限制）：
   真实内核 + `python -m inkflow.mcp` stdio 子进程 → tools/list 18 项 →
   `manage_config` provider_list/llm_status、`manage_log` query、
   `write` draft_list/confirm_draft/reject_draft（含错误信封与本地 INVALID_ARGS）
   端到端可用（链路 = stdio → 工具 → ensure_kernel → InkFlowHTTPClient → 内核 REST）。
2. **LLM 门禁轨**（`LLM_API_KEY` 未设置 → skip；ADR-026「缺 key 永远 skip 不 fail」）：
   旅程 stage3/6 的 MCP 驱动重放——`manage_book` plan_start → plan_respond(auto) →
   run → status → summary（真实 LLM 一次完成 WritingPlan）。

纪律：
- 每次 tools/call 新建 stdio 子进程连接（镜像 #866 采样形态，进程态隔离）。
- 隔离：`INKFLOW_DATA_DIR` + 显式 state_file 指向 tmp（不碰真实 %APPDATA%\\InkFlow）。
- 种子数据经内核 REST 直建（前置数据不走被测面，避免根因混淆）。
- 断言只用**语义子串/结构**，不锁全句（LLM 输出不可确定性断言）。
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

#: spec §4.1 #16-18
_NEW_TOOL_NAMES = ("manage_book", "manage_config", "manage_log")


def _kill_kernel_tree(pid: int) -> None:
    """可靠终止内核进程树（Windows taskkill /T /F；best-effort）。"""
    if pid <= 0:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15
        )


def _skip_ci() -> bool:
    """GitHub Actions 沙箱无法拉起真实内核（秒退）→ CI 跳过（同 test_cli_mcp.py）。"""
    return os.environ.get("CI") == "true"


def _llm_child_env() -> dict[str, str] | None:
    """LLM 门禁：LLM_API_KEY 缺省 → None（轨跳过）。

    子内核经 `INKFLOW_LLM_DEFAULT_MODEL` + `INKFLOW_{PROVIDER}_API_KEY`
    解析凭据（provider_config.get_provider_config 调用时读 os.environ）。
    """
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    raw = os.environ.get("LLM_MODEL", "deepseek/deepseek-v4-flash")
    provider = raw.split("/", 1)[0] if "/" in raw else "deepseek"
    model = raw if "/" in raw else f"deepseek/{raw}"
    return {
        "INKFLOW_LLM_DEFAULT_MODEL": model,
        f"INKFLOW_{provider.upper()}_API_KEY": key,
    }


@contextlib.contextmanager
def _isolated_kernel(tmp_path_factory, extra_env: dict[str, str] | None = None):
    """隔离环境拉起真实内核（module-scope 复用由调用方决定）。"""
    state_file = tmp_path_factory.mktemp("kernel") / "kernel.json"
    child_data_dir = tmp_path_factory.mktemp("kernel-data")
    prev_data_dir = os.environ.get("INKFLOW_DATA_DIR")
    prev_extra = {k: os.environ.get(k) for k in (extra_env or {})}
    os.environ["INKFLOW_DATA_DIR"] = str(child_data_dir)
    for key, value in (extra_env or {}).items():
        os.environ[key] = value
    handle = None
    try:
        handle = asyncio.run(ensure_kernel(state_file=state_file, timeout=_KERNEL_TIMEOUT))
        yield SimpleNamespace(handle=handle, state_file=state_file, data_dir=child_data_dir)
    finally:
        if handle is not None:
            _kill_kernel_tree(handle.pid)
        if prev_data_dir is None:
            os.environ.pop("INKFLOW_DATA_DIR", None)
        else:
            os.environ["INKFLOW_DATA_DIR"] = prev_data_dir
        for key, value in prev_extra.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _server_params(env: SimpleNamespace) -> StdioServerParameters:
    """mcp server 子进程启动参数（python -m inkflow.mcp，继承隔离 env）。"""
    from mcp.client.stdio import StdioServerParameters

    child_env = os.environ.copy()
    child_env["INKFLOW_DATA_DIR"] = str(env.data_dir)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "inkflow.mcp"],
        env=child_env,
    )


async def _call(env: SimpleNamespace, tool: str, arguments: dict) -> tuple[dict, bool]:
    """新 stdio 连接调一次工具 → (信封 dict, is_error)。"""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    async with (
        stdio_client(_server_params(env)) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments)
        return json.loads(result.content[0].text), bool(result.is_error)


async def _list_tools(env: SimpleNamespace) -> list[str]:
    """tools/list 工具名列表（新连接）。"""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    async with (
        stdio_client(_server_params(env)) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [t.name for t in result.tools]


def _seed_project(env: SimpleNamespace) -> str:
    """经内核 REST 直建一个项目（前置数据不走被测面）。"""
    import httpx

    base = f"http://127.0.0.1:{env.handle.port}"
    headers = {"X-InkFlow-Token": env.handle.token}
    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
        resp = client.post(
            "/api/v1/projects",
            json={"name": "933 stdio 种子", "tags": ["其他"], "language": "zh-CN"},
        )
        resp.raise_for_status()
        return str(resp.json()["id"])


@pytest.fixture(scope="module")
def stdio_env(tmp_path_factory):
    """非 LLM 轨：隔离内核 + 种子项目（module 级，属性对测试可见）。"""
    with _isolated_kernel(tmp_path_factory) as env:
        env.project_id = _seed_project(env)
        yield env


@pytest.fixture(scope="module")
def stdio_llm_env(tmp_path_factory):
    """LLM 门禁轨：额外注入 INKFLOW_* 凭据（无 LLM_API_KEY → skip）。"""
    extra = _llm_child_env()
    if extra is None:
        pytest.skip("LLM_API_KEY 未设置 — 真实 LLM 轨跳过（ADR-026）")
    with _isolated_kernel(tmp_path_factory, extra) as env:
        env.project_id = _seed_project(env)
        yield env


@pytest.mark.skipif(_skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）")
class TestMcpNewSurfaceStdio933:
    """非 LLM 轨：新工具经 stdio 全链路（真实内核）。"""

    @pytest.mark.asyncio
    async def test_tools_list_18(self, stdio_env):
        names = await _list_tools(stdio_env)
        assert len(names) == 18, names
        for name in _NEW_TOOL_NAMES:
            assert name in names

    @pytest.mark.asyncio
    async def test_manage_config_provider_list(self, stdio_env):
        envelope, is_error = await _call(
            stdio_env, "manage_config", {"action": "provider_list"}
        )
        assert is_error is False
        assert envelope["ok"] is True
        # GET /provider-configs 返回 {items, total}
        assert "items" in envelope["data"]

    @pytest.mark.asyncio
    async def test_manage_config_llm_status(self, stdio_env):
        envelope, is_error = await _call(
            stdio_env,
            "manage_config",
            {"action": "llm_status", "project_id": stdio_env.project_id},
        )
        assert is_error is False
        assert envelope["ok"] is True
        data = envelope["data"]
        assert "providers" in data
        assert "embedding_model" in data
        assert "vector_status" in data

    @pytest.mark.asyncio
    async def test_manage_log_query(self, stdio_env):
        envelope, is_error = await _call(
            stdio_env,
            "manage_log",
            {"action": "query", "limit": 5, "caller_type": "mcp"},
        )
        assert is_error is False
        assert envelope["ok"] is True
        # /logs 返回 F7 信封 → 工具层再包一层 MCP 信封
        assert "data" in envelope["data"]

    @pytest.mark.asyncio
    async def test_write_draft_list(self, stdio_env):
        envelope, is_error = await _call(
            stdio_env,
            "write",
            {"action": "draft_list", "project_id": stdio_env.project_id},
        )
        assert is_error is False
        assert envelope["ok"] is True
        assert "items" in envelope["data"]

    @pytest.mark.asyncio
    async def test_write_confirm_draft_unknown_id_business_error(self, stdio_env):
        """未知草稿 → 业务性 NOT_FOUND（非空 message，链路正常）。"""
        envelope, is_error = await _call(
            stdio_env,
            "write",
            {
                "action": "confirm_draft",
                "draft_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert is_error is True
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "NOT_FOUND"
        assert envelope["error"]["message"]

    @pytest.mark.asyncio
    async def test_write_reject_draft_unknown_id_business_error(self, stdio_env):
        envelope, is_error = await _call(
            stdio_env,
            "write",
            {
                "action": "reject_draft",
                "draft_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert is_error is True
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_write_confirm_draft_missing_id_invalid_args(self, stdio_env):
        """缺 draft_id → 本地 INVALID_ARGS（零 HTTP 往返，spec §7 #16）。"""
        envelope, is_error = await _call(
            stdio_env, "write", {"action": "confirm_draft"}
        )
        assert is_error is True
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "INVALID_ARGS"

    @pytest.mark.asyncio
    async def test_manage_book_status_unknown_run(self, stdio_env):
        """book status 未知 run_id → NOT_FOUND 业务信封（链路通）。"""
        envelope, is_error = await _call(
            stdio_env,
            "manage_book",
            {"action": "status", "run_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert is_error is True
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_manage_book_plan_confirm_unknown_session(self, stdio_env):
        """plan_confirm 未知会话 → 业务信封（404/422 映射后非空 message）。"""
        envelope, is_error = await _call(
            stdio_env,
            "manage_book",
            {
                "action": "plan_confirm",
                "session_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert is_error is True
        assert envelope["ok"] is False
        assert envelope["error"]["message"]

    @pytest.mark.asyncio
    async def test_manage_book_missing_args_invalid_args(self, stdio_env):
        envelope, is_error = await _call(stdio_env, "manage_book", {"action": "run"})
        assert is_error is True
        assert envelope["error"]["code"] == "INVALID_ARGS"


@pytest.mark.skipif(_skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）")
class TestMcpBookJourneyLlM933:
    """LLM 门禁轨：旅程 stage3/6 的 MCP 驱动重放（无 LLM_API_KEY → skip）。"""

    @pytest.mark.asyncio
    async def test_plan_start_respond_run_status_summary(self, stdio_llm_env):
        """manage_book 全链路：plan_start → plan_respond(auto) → run → status → summary。"""
        started, err = await _call(
            stdio_llm_env,
            "manage_book",
            {
                "action": "plan_start",
                "project_id": stdio_llm_env.project_id,
                "one_liner": "少年替师出诊",
            },
        )
        assert err is False, started
        assert started["ok"] is True
        session_id = started["data"]["session_id"]
        assert started["data"]["questions"]

        done, err = await _call(
            stdio_llm_env,
            "manage_book",
            {"action": "plan_respond", "session_id": session_id, "auto": True},
        )
        assert err is False, done
        assert done["ok"] is True
        assert done["data"]["completed"] is True
        plan = done["data"]["writing_plan"]
        assert plan and plan.get("id")
        plan_id = plan["id"]

        # plan_show 回读会话
        shown, err = await _call(
            stdio_llm_env,
            "manage_book",
            {"action": "plan_show", "session_id": session_id},
        )
        assert err is False
        assert shown["ok"] is True

        run, err = await _call(
            stdio_llm_env,
            "manage_book",
            {
                "action": "run",
                "writing_plan_id": plan_id,
                "mode": "static",
                # 上限护栏：真实 LLM 只写 1 章（缺省 max_chapters=100 会跑满全书）
                "limits": {"max_chapters": 1},
            },
        )
        assert err is False, run
        assert run["ok"] is True
        run_id = run["data"]["run_id"]
        assert run_id

        status, err = await _call(
            stdio_llm_env, "manage_book", {"action": "status", "run_id": run_id}
        )
        assert err is False, status
        assert status["ok"] is True
        assert status["data"].get("run_id") == run_id

        summary, err = await _call(
            stdio_llm_env, "manage_book", {"action": "summary", "run_id": run_id}
        )
        assert err is False, summary
        assert summary["ok"] is True
