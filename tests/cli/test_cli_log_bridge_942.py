"""#942 CLI 日志桥接 — 真实内核集成契约（M1/M2/M3 验收面，RED 测试）。

缺陷（issue #942，#924 同族 CLI 侧）：CLI 子命令日志落 stderr 不进内核
StructuredLogStore → GET /api/v1/logs?caller_type=cli 恒 total=0，GUI 日志页
「内核」分类 CLI 操作痕迹永远缺失（审计盲区）。

验收链（issue M1→M3）：
  真实 CLI 子进程（python -m inkflow，INKFLOW_DATA_DIR 隔离）执行命令 →
  查询**同一内核** GET /api/v1/logs?caller_type=cli →
  total>0 且包含该命令记录（event=命令路径 / caller_name=inkflow-cli）；
  失败命令 → WARN；写操作 api 旁证 >0（防假绿）+ CLI 写审计可按项目回查。

RED 预期（main@9b89e06）：桥接不存在 → cli 记录恒 0 → 核心用例 FAIL。
实测旁证（探针 2026-09-05）：CLI project create 后内核 api total=1、cli total=0。

── 测试约定（镜像 test_mcp_log_bridge_924.py，spec 自包含 #140）──
- module-scope 一次拉起真实内核（ensure_kernel state_file/data_dir 隔离 tmp）；
  CLI 子进程继承 INKFLOW_DATA_DIR → 复用同一内核（零冷启动抖动）。
- ⚠️ CI 跳过（GitHub Actions 沙箱拉内核秒退）；裁判在本地，CI 只保证收集。
- 断言用轮询（桥接 flush 在 CLI 进程退出前同步完成，HTTP 落盘→查询留余量）。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from inkflow.infrastructure.kernel import ensure_kernel

_KERNEL_TIMEOUT = 60.0
_POLL_DEADLINE_S = 8.0
_CLI_TIMEOUT_S = 120.0


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


def _cli(*args: str) -> subprocess.CompletedProcess:
    """在当前隔离 env 下跑一次真实 CLI 子进程。"""
    return subprocess.run(
        [sys.executable, "-m", "inkflow", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_CLI_TIMEOUT_S,
    )


def _query_cli_logs(env: SimpleNamespace, caller_type: str = "cli") -> dict:
    import httpx

    base = f"http://127.0.0.1:{env.handle.port}"
    headers = {"X-InkFlow-Token": env.handle.token}
    with httpx.Client(base_url=base, headers=headers, timeout=10.0) as client:
        r = client.get("/api/v1/logs", params={"caller_type": caller_type, "limit": 100})
        r.raise_for_status()
        return r.json()


def _poll_cli_records(env: SimpleNamespace, *, expect_event: str) -> dict:
    """轮询直至 caller_type=cli 出现 expect_event 或超时；返回最后一次响应 data。"""
    deadline = time.monotonic() + _POLL_DEADLINE_S
    data: dict = {}
    while True:
        data = _query_cli_logs(env)["data"]
        events = {item.get("event") for item in data.get("items", [])}
        if expect_event in events or time.monotonic() >= deadline:
            return data
        time.sleep(0.25)


@pytest.mark.skipif(_skip_ci(), reason="GitHub Actions 沙箱拉内核秒退；#942 桥接验收在本地轨")
class TestCliLogBridgeIntegration:
    """M1：CLI 操作日志进内核 store；M2：GET /logs?caller_type=cli total>0。"""

    def test_cli_command_visible_in_kernel_store(self, bridge_env: SimpleNamespace) -> None:
        proc = _cli("project", "list")
        assert proc.returncode == 0, proc.stderr[-500:]

        data = _poll_cli_records(bridge_env, expect_event="project.list")
        assert data["total"] > 0, (
            "#942 核心判据：CLI project list 后 caller_type=cli 仍恒空（桥接缺失）"
        )
        item = next(i for i in data["items"] if i["event"] == "project.list")
        assert item["caller_type"] == "cli"
        assert item["caller_name"] == "inkflow-cli"
        assert item["level"] == "INFO"
        assert item["message_key"] == "log.event.cli_command"
        assert item["params"]["group"] == "project"
        assert item["params"]["command"] == "list"

    def test_failed_cli_command_recorded_as_warn(self, bridge_env: SimpleNamespace) -> None:
        """不存在的 project_id → 内核 404 → CLI exit 1 → WARN checkpoint。"""
        proc = _cli(
            "chapter", "list", "-p", "00000000-0000-4000-8000-000000000099"
        )
        assert proc.returncode != 0
        data = _poll_cli_records(bridge_env, expect_event="chapter.list")
        item = next(i for i in data["items"] if i["event"] == "chapter.list")
        assert item["level"] == "WARN"
        assert item["caller_type"] == "cli"

    def test_write_operation_auditable_with_project(
        self, bridge_env: SimpleNamespace
    ) -> None:
        """审计闭环（M3）：CLI 建项目 → api 旁证 >0 → 记录可按 project 回查。"""
        proc = _cli("--json", "project", "create", "--name", "942桥接审计")
        assert proc.returncode == 0, proc.stderr[-500:]
        import json

        project_id = json.loads(proc.stdout)["data"]["id"]
        assert isinstance(project_id, str) and project_id

        data = _poll_cli_records(bridge_env, expect_event="project.create")
        item = next(i for i in data["items"] if i["event"] == "project.create")
        assert item["level"] == "INFO"
        assert item["params"]["command"] == "create"

        api_data = _query_cli_logs(bridge_env, caller_type="api")["data"]
        assert api_data["total"] > 0, "内核 api 记录也空——装配/数据目录异常，本文件判据失效"
        create_api = next(
            (i for i in api_data["items"] if i["event"] == "create_project"), None
        )
        assert create_api is not None, "CLI 建项目未在内核留 api 痕（服务层埋点异常）"

    def test_body_content_never_forwarded(self, bridge_env: SimpleNamespace) -> None:
        """正文哨兵：CLI 传长中文正文参数，审计记录绝不包含它。"""
        secret = "剑气纵横三万里，一剑光寒十九洲——这段正文绝不该进审计日志。"
        proc = _cli("project", "create", "--name", secret, "--language", "zh-CN")
        assert proc.returncode == 0, proc.stderr[-500:]
        _poll_cli_records(bridge_env, expect_event="project.create")
        data = _query_cli_logs(bridge_env)["data"]
        for item in data["items"]:
            blob = (
                str(item.get("params", {}))
                + str(item.get("event", ""))
                + item.get("message_key", "")
            )
            assert secret not in blob

    def test_cli_stdout_untouched_by_bridge(self, bridge_env: SimpleNamespace) -> None:
        """CLI 用户输出面纪律：stdout 仍只有业务输出，无日志行混入。"""
        proc = _cli("--json", "project", "list")
        assert proc.returncode == 0, proc.stderr[-500:]
        import json

        envelope = json.loads(proc.stdout)  # stdout 必须是合法 JSON 信封
        assert envelope["ok"] is True
        assert "caller_type" not in proc.stdout
