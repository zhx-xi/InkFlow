"""backend 测试根 conftest —— 提供 test_engine（F47 #379 RED 契约：unit 层 DB fixture）。

顶层 tests/conftest.py 的 test_engine 属集成测试 conftest 链（repo_root/tests/），
backend/tests/unit/ 的 conftest 链不加载它；test_agent_trace.py 的 ExecutionStore
用例需要真实 in-memory SQLite，故在此镜像同一 fixture（不修改任何既有测试文件）。

# #735 D1: config.llm_default_model 全局默认已改空（移除内置 deepseek 硬编码）。
# 后台单元/集成测试的历史用例依赖「未指定 model 时回退到 deepseek 默认」的契约，
# 此处统一经环境变量 INKFLOW_LLM_DEFAULT_MODEL（env_prefix INKFLOW_ + 字段名
# llm_default_model）注入该值（「mock config 回退」），使既有用例在新空默认下保持
# 原语义；D1 的空默认契约由 test_model_resolution.py 用 InkFlowConfig.model_fields
# （class 默认，免疫 env）单独断言。

#1488 / #1496（0.17.0）：测试基础设施后置处理在本根**镜像**顶层 tests/conftest.py
（两套 pytest 根各自加载各自的 conftest、互不 import，镜像与上条 test_engine 同规）：
会话结束回收本会话拉起的 `inkflow serve` 内核进程 + 注入 F51 逃生门
`INKFLOW_DEBUG_NO_BROWSER=1`。判据/实现说明见顶层 `tests/conftest.py` 的
`reclaim_test_kernel_processes`（契约测试：`tests/cli/test_kernel_cleanup_1488.py`）。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

os.environ.setdefault("INKFLOW_LLM_DEFAULT_MODEL", "deepseek/deepseek-v4-flash")

# ── #1496：pytest 侧统一注入 F51 v1.1（#949）逃生门（与顶层 tests/conftest.py 同）──
# debug 态 `serve` 默认自动弹系统浏览器打开 /docs（F51 D2）→ 本地跑测试累积窗口。
# 显式赋值（非 setdefault）：宿主 shell 残留值不得让弹窗复发；产品默认语义不变。
os.environ["INKFLOW_DEBUG_NO_BROWSER"] = "1"

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from inkflow.core.database import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_engine():
    """function-scoped in-memory SQLite engine with tables created per test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


# ── #1488：测试拉起的 `inkflow serve` 内核进程——会话级统一回收 ────────────────
#
# 镜像顶层 `tests/conftest.py`（实现与判据逐字同源，两处同步改动）。判据两条：
#   ① CommandLine 含本会话 pytest 临时根（basetemp）；② 亲缘链上溯到本 pytest 进程。
# 不匹配手工常驻内核与并行会话/其他 worktree 的内核（宁漏不误杀）。清理失败只记
# WARNING，绝不把测试 ERROR（#1488 验收）。

ENUM_TIMEOUT_S = 30.0
KILL_TIMEOUT_S = 15.0
KILL_PASSES = 2
KILL_SETTLE_S = 0.3
ANCESTRY_DEPTH = 16

logger = logging.getLogger(__name__)


def enumerate_processes() -> list[tuple[int, int, str]]:
    """枚举本机全部进程 → ``[(pid, ppid, cmdline)]``（非 Windows → ``[]``）。装配缝。"""
    if sys.platform != "win32":
        return []
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | ForEach-Object { "
        '"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.CommandLine)" }'
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=ENUM_TIMEOUT_S,
        check=False,
    )
    rows: list[tuple[int, int, str]] = []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
        except ValueError:
            continue
    return rows


def terminate_process_tree(pid: int) -> None:
    """终止单个进程树（`taskkill /PID <pid> /T /F`）；调用方负责吞掉"已退出"类失败。"""
    if pid <= 0:
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        timeout=KILL_TIMEOUT_S,
        check=False,
    )


def is_test_kernel(
    cmdline: str, pid: int, parents: dict[int, int], *, pytest_pid: int, basetemp: str
) -> bool:
    """归属判定（纯函数）：该进程是否为本 pytest 会话拉起的测试内核。"""
    if "inkflow" not in cmdline or "serve" not in cmdline:
        return False
    if basetemp and basetemp in cmdline.lower():
        return True
    seen: set[int] = set()
    current = pid
    for _ in range(ANCESTRY_DEPTH):
        parent = parents.get(current)
        if not parent or parent <= 0 or parent in seen:
            return False
        seen.add(parent)
        if parent == pytest_pid:
            return True
        current = parent
    return False


def reclaim_test_kernel_processes(pytest_pid: int, basetemp: str) -> list[int]:
    """回收本会话拉起的 `inkflow serve` 内核进程 → 已下发终止的 pid 列表。

    最多两趟（`/T` 的进程树终止有传播延迟，杀掉 shim 后复查一次真解释器）。
    **绝不抛错**：枚举失败（无 powershell / 超时）与终止失败（进程已退出 / 权限不足）
    全部吞掉并记 WARNING——清理失败不得把测试 ERROR（#1488 验收）。
    """
    terminated: list[int] = []
    for attempt in range(KILL_PASSES):
        try:
            rows = enumerate_processes()
        except Exception as exc:  # 清理失败不得升级为测试 ERROR（#1488 验收）
            logger.warning("#1488 内核进程枚举失败（第 %d 趟）：%s", attempt + 1, exc)
            return terminated
        parents = {pid: ppid for pid, ppid, _ in rows}
        base = basetemp.lower()
        targets = [
            pid
            for pid, _ppid, cmdline in rows
            if is_test_kernel(cmdline or "", pid, parents, pytest_pid=pytest_pid, basetemp=base)
        ]
        if not targets:
            break
        for pid in targets:
            try:
                terminate_process_tree(pid)
                terminated.append(pid)
            except Exception as exc:  # 进程已退出 / 权限不足 → 记日志不抛（#1488 验收）
                logger.warning("#1488 终止测试内核 pid=%s 失败：%s", pid, exc)
        time.sleep(KILL_SETTLE_S)
    return terminated


@pytest.fixture(scope="session", autouse=True)
def _reclaim_kernel_processes(tmp_path_factory):
    """#1488：会话结束回收本会话拉起的 `inkflow serve` 内核进程（契约见顶层 conftest）。"""
    yield
    terminated = reclaim_test_kernel_processes(os.getpid(), str(tmp_path_factory.getbasetemp()))
    if terminated:
        logger.warning("#1488 会话结束回收测试内核进程 pid=%s", terminated)
