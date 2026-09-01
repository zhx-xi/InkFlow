"""CLI 黑盒断言契约（ADR-048 §3）— 真实子进程 `inkflow` + 真实内核（本地跑，CI skip）。

覆盖 C1 结果一致 / C2 成功·错误显示 / C3 退出码 / C4 错误码映射（黑盒边界）。

── C4 已知缺口（本文件 RED 锚点）────────────────────────────────────────────
`inkflow project get --id <合法 UUID 不存在>`：合法 UUID（int 值超 SQLite int64）
经 `_to_int_id` → `uuid.int` 超 int64 → `project_repo.get` 绑定超范围整数到 SQLite
→ 抛 OverflowError → 内核 500 → CLI 映射 INTERNAL_ERROR。契约要求 NOT_FOUND。

── 运行形态 ────────────────────────────────────────────────────────────────
- module-scope fixture 起真实内核（ensure_kernel，isolated INKFLOW_DATA_DIR），
  子进程 `inkflow` 复用（读同 kernel.json）。
- CI 沙箱无法拉起真实内核（同 test_cli_mcp 先例）→ skipif；本地黑盒验证。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from inkflow.infrastructure.kernel import ensure_kernel

_KERNEL_TIMEOUT = 60.0

# 合法 UUID v4（int 值远超 SQLite int64 → 触发 C4 溢出路径）
_NONEXIST_UUID = "00000000-0000-4000-8000-000000000999"
# 整数 id（_parse_project_id 无法解析为 UUID → ValueError → 404 NOT_FOUND 对照）
_NONEXIST_INT = "1"


def _kill_kernel_tree(pid: int) -> None:
    """可靠终止内核进程树（Windows taskkill /T /F；best-effort）。"""
    if pid <= 0:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )


def _skip_ci() -> bool:
    return os.environ.get("CI") == "true"


@pytest.fixture(scope="module")
def kernel_env(tmp_path_factory):
    """module-scope：真实内核 + 隔离 INKFLOW_DATA_DIR；teardown taskkill。"""
    child_data_dir = tmp_path_factory.mktemp("cli-blackbox")
    prev = os.environ.get("INKFLOW_DATA_DIR")
    os.environ["INKFLOW_DATA_DIR"] = str(child_data_dir)
    handle = None
    try:
        handle = asyncio.run(ensure_kernel(timeout=_KERNEL_TIMEOUT))
        yield SimpleNamespace(data_dir=child_data_dir)
    finally:
        if handle is not None:
            _kill_kernel_tree(handle.pid)
        if prev is None:
            os.environ.pop("INKFLOW_DATA_DIR", None)
        else:
            os.environ["INKFLOW_DATA_DIR"] = prev


def _inkflow(*args: str) -> subprocess.CompletedProcess[str]:
    """黑盒调用 `inkflow <args...>`（继承父进程 env → INKFLOW_DATA_DIR 隔离内核）。"""
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, "-m", "inkflow", *args],
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )


def _json_result(proc: subprocess.CompletedProcess[str]) -> dict:
    """stdout 整体 JSON 信封（inkflow --json 输出多行缩进 JSON）。"""
    return json.loads(proc.stdout)


@pytest.mark.skipif(_skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）；本地黑盒验证")
class TestCliBlackbox:
    """CLI 黑盒契约（C1-C4），真实子进程 + 真实内核。"""

    def test_project_list_json_envelope_ok(self, kernel_env):
        """C1 结果一致：`inkflow --json project list` → {ok:true, data: 对象数组}
        （F7 §5 允许 data 为对象数组形态）。"""
        proc = _inkflow("--json", "project", "list")
        assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
        env = _json_result(proc)
        assert env["ok"] is True
        assert isinstance(env["data"], list)

    def test_project_get_int_missing_returns_not_found(self, kernel_env):
        """C2/C3 回归保护：`project get --id 1`（int，不存在）→ NOT_FOUND + 退出码 1。"""
        proc = _inkflow("--json", "project", "get", "--id", _NONEXIST_INT)
        assert proc.returncode == 1, f"exit={proc.returncode}"
        env = _json_result(proc)
        assert env["ok"] is False
        assert env["error"]["code"] == "NOT_FOUND"

    def test_project_get_uuid_missing_should_be_not_found(self, kernel_env):
        """C4 错误码映射（黑盒边界）——🔴 RED 锚点：
        合法 UUID 不存在应 NOT_FOUND（当前 INTERNAL_ERROR，因 int 溢出 → 500）。"""
        proc = _inkflow("--json", "project", "get", "--id", _NONEXIST_UUID)
        assert proc.returncode == 1, f"exit={proc.returncode}"
        env = _json_result(proc)
        assert env["ok"] is False
        # 🔴 契约：应 NOT_FOUND；当前实现返回 INTERNAL_ERROR（int 溢出）→ 本断言 FAIL → RED
        assert env["error"]["code"] == "NOT_FOUND"
