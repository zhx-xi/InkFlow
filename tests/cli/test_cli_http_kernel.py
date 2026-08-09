"""InkFlow CLI 恒经 HTTP 真实内核轨（M5 验收）— F38 spec §9.2（Issue #169，RED 阶段测试契约）.

真实内核轨 = 真实 ensure_kernel 拉起内核进程（F30 已实现）→ 复用路径 pid 不变 →
豁免命令不触发拉起 → InkFlowHTTPClient 直连真实内核 HTTP。本文件是首个
「真实拉起内核」的 CLI 测试（test_cli_kernel.py 为 mock 轨，绝不拉起）。

── GREEN 实现契约 ────────────────────────────────────────────────

1. ensure_kernel（F30 已交付，backend/src/inkflow/infrastructure/kernel/__init__.py）：
   async def ensure_kernel(*, spawn_cmd=None, timeout=30.0, health_timeout=2.0,
   state_file=None, version_check=True) -> KernelHandle
   - 复用：state_file 有合法状态 + pid 存活 + /health 200 + 版本 major 相同
     → KernelHandle(reused=True)（pid/port/token 原样透传）
   - 拉起：CreateMutexW 互斥 → spawn → 轮询 state_file 就绪 → 写回五字段
     → KernelHandle(reused=False)
   - KernelHandle 字段（frozen dataclass）：port/token/pid/version/started_at/reused
   - 默认 spawn 命令 = [sys.executable, "-m", "inkflow", "serve", "--port", "0",
     "--port-file", <state_file>]——serve 子进程把端口交付 JSON（四字段）写到
     state_file 路径本身，ensure_kernel 轮询该文件就绪后回写五字段（本文件
     全部用例走默认 spawn_cmd=None，与真实 CLI 行为一致）。

2. 真实内核隔离策略（父侧拍板折中，不污染真实 kernel.json）：
   - 测试全程把 state_file 显式注入 tmp_path，与用户机器上可能存在的真实内核
     零冲突（bootstrap 互斥仅存于拉起期间，运行中内核不持互斥；双内核各用
     各的端口/状态文件/数据目录）。
   - 子进程数据目录隔离：ensure_kernel 前设 INKFLOW_DATA_DIR=<tmp>，serve
     子进程的 SQLite/chroma 全部落在 tmp（防污染 worktree 的 backend/data/）。
   - 「CLI 命令内部自动拉起」由手工 M5 验证（spec §13 M5 标注）；自动化轨 =
     ensure_kernel 级拉起/复用 + InkFlowHTTPClient 直连级（spec §9.2）。

3. 清理（防 CI 内核泄漏，必须可靠）：
   - module fixture teardown：读 KernelHandle.pid → taskkill /PID <pid> /T /F
     （/T 连坐子进程链；taskkill 对已死进程 best-effort 容忍）。
   - 恢复 INKFLOW_DATA_DIR 环境变量原值。

4. InkFlowHTTPClient（spec §2.1，GREEN 目标，RED 阶段模块不存在）：
   - 模块 inkflow.infrastructure.http（__init__.py 导出 InkFlowHTTPClient /
     HttpApiError / map_http_error；client.py 为 httpx.AsyncClient 封装）。
   - InkFlowHTTPClient(handle: KernelHandle, timeout: float = 30.0)：
     base_url = http://127.0.0.1:{handle.port}/api/v1；请求头
     X-InkFlow-Token: {handle.token}；async 上下文管理器（__aenter__/__aexit__
     关闭连接池，spec §1.4 的 async with 形态）。
   - async def get(path, *, params=None) -> dict：2xx 返回解析后 JSON
     （裸数据，非信封，spec §2.1 实测核实）；非 2xx 抛 HttpApiError。
   - GET /projects → {"items": [...], "total": N, "offset": 0, "limit": 50}
     （全新隔离 DB → total == 0）。

5. 豁免契约（spec §1.3 / §7 #15，已 GREEN 模块）：
   - inkflow --help：不触发 ensure_kernel（惰性接线）。
   - inkflow kernel status / inkflow config show：纯查询/本地文件，绝不 spawn。

── RED 形态说明 ─────────────────────────────────────────────────
- 用例 1/2（ensure_kernel 拉起 + 复用）：F30 已交付 → PASS（拉起 ~4.7s 属预期）
- 用例 3/4（--help / 豁免命令）：依赖模块已 GREEN → PASS
- 用例 5（InkFlowHTTPClient 直连）：inkflow.infrastructure.http 不存在 →
  用例体 lazy import 抛 ModuleNotFoundError → FAILED（预期 RED 形态；
  GREEN 落地后自动转绿）
- ⚠️ InkFlowHTTPClient 的 import 必须放在用例 5 函数体内（lazy）：若放模块
  顶部，整文件收集期 ModuleNotFoundError 会拖垮用例 1-4（规则 1c 例外）。

── 测试约定 ─────────────────────────────────────────────────────
- CliRunner(env={"NO_COLOR": "1"})：CI FORCE_COLOR 坑（先例 test_cli_serve.py）。
- 真实内核冷启动 ~4.7s：module-scope fixture 一次拉起，用例 1/2/5 共享；
  用例 3/4 独立 tmp_path，不依赖内核。
- 用例执行顺序与拉起无耦合：拉起发生在 fixture 内，用例 1/2/5 可任意顺序。
- async 用例（用例 5）必须显式 `pytestmark = pytest.mark.asyncio`：pytest-asyncio
  1.x STRICT 模式（pyproject 的 asyncio_mode=auto 已被 1.x 移除/忽略），先例
  tests/integration/test_agent_pipeline.py。
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.app import app
from inkflow.infrastructure.kernel import ensure_kernel, state

# inkflow.core 包把 config 属性重绑定为实例，`import a.b as x` 会取到实例而非模块，
# 因此用 importlib 取 sys.modules 中的真实模块（先例 test_cli_kernel.py）
core_config_mod = importlib.import_module("inkflow.core.config")

# 冷启动 ~4.7s（chromadb/BGE 加载），拉起/复用共用显式超时（防 env 干扰）
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


@pytest.fixture
def cli_runner():
    # CI FORCE_COLOR 陷阱：NO_COLOR 强制关色，防 ANSI 码污染 output 断言（先例 test_cli_serve.py）
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture(scope="module")
def real_kernel(tmp_path_factory):
    """module-scope：拉起一个真实内核，供拉起/复用/HTTP 直连三个用例共享。

    隔离：state_file 显式注入 tmp_path（不触碰真实 kernel.json）；子进程数据
    目录经 INKFLOW_DATA_DIR 指向 tmp（serve 的 SQLite/chroma 不落 worktree）。
    teardown：taskkill 内核进程树 + 恢复环境变量原值。
    """
    state_file = tmp_path_factory.mktemp("kernel") / "kernel.json"
    child_data_dir = tmp_path_factory.mktemp("kernel-data")
    prev_data_dir = os.environ.get("INKFLOW_DATA_DIR")
    os.environ["INKFLOW_DATA_DIR"] = str(child_data_dir)
    handle = None
    try:
        # spawn_cmd=None → F30 默认命令：sys.executable -m inkflow serve
        # --port 0 --port-file <state_file>（端口交付 JSON 写 state_file 本身）
        handle = asyncio.run(
            ensure_kernel(state_file=state_file, timeout=_KERNEL_TIMEOUT)
        )
        yield SimpleNamespace(handle=handle, state_file=state_file)
    finally:
        if handle is not None:
            _kill_kernel_tree(handle.pid)
        if prev_data_dir is None:
            os.environ.pop("INKFLOW_DATA_DIR", None)
        else:
            os.environ["INKFLOW_DATA_DIR"] = prev_data_dir


class TestEnsureKernelReal:
    """真实内核轨：ensure_kernel 自动拉起 + 复用（M5，spec §9.2）。"""

    def test_no_kernel_auto_spawn(self, real_kernel):
        """无 kernel.json → ensure_kernel 自动拉起：reused=False + 五字段状态文件。"""
        handle = real_kernel.handle
        assert handle.reused is False
        # 状态文件已写入 tmp_path（五字段契约，spec §2.1）
        state_file = real_kernel.state_file
        assert state_file.exists()
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        assert set(payload) == {"port", "token", "pid", "version", "started_at"}
        assert isinstance(payload["port"], int) and payload["port"] > 0
        assert isinstance(payload["token"], str) and payload["token"]
        assert isinstance(payload["pid"], int) and payload["pid"] > 0
        assert isinstance(payload["version"], str) and payload["version"]
        # 句柄字段与状态文件一致；内核进程真实存活
        assert handle.pid == payload["pid"]
        assert handle.port == payload["port"]
        assert handle.token == payload["token"]
        assert state.is_process_alive(handle.pid)

    def test_reuse_same_pid(self, real_kernel):
        """二次 ensure_kernel（同 state_file）：reused=True 且 pid 不变（未重新 spawn）。"""
        first = real_kernel.handle
        second = asyncio.run(
            ensure_kernel(state_file=real_kernel.state_file, timeout=_KERNEL_TIMEOUT)
        )
        assert second.reused is True
        assert second.pid == first.pid
        assert second.port == first.port
        assert second.token == first.token


class TestNoSpawn:
    """豁免路径：--help / kernel status / config show 绝不触发拉起（spec §7 #15 / §1.3）。"""

    def test_help_does_not_spawn(self, cli_runner, tmp_path, monkeypatch):
        """inkflow --help：exit 0 且不生成 kernel.json（惰性接线，不触发 ensure_kernel）。"""
        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert not (tmp_path / "kernel.json").exists()

    def test_kernel_status_and_config_show_do_not_spawn(
        self, cli_runner, tmp_path, monkeypatch
    ):
        """kernel status / config show 豁免：纯查询，不 spawn 子进程、不生成 kernel.json。"""
        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        with patch("subprocess.Popen") as mock_popen:
            status = cli_runner.invoke(app, ["kernel", "status"])
            config = cli_runner.invoke(app, ["config", "show"])
        assert status.exit_code == 0
        assert config.exit_code == 0
        assert not (tmp_path / "kernel.json").exists()
        # 豁免契约：两命令全程不触碰任何 spawn 机制
        mock_popen.assert_not_called()


class TestHttpClientReal:
    """InkFlowHTTPClient 直连真实内核（spec §2.1；RED 阶段本类唯一用例 FAILED）。"""

    # pytest-asyncio 1.x STRICT 模式（asyncio_mode=auto 已移除/被忽略）：
    # async 用例必须显式 mark（先例 tests/integration/test_agent_pipeline.py）
    pytestmark = pytest.mark.asyncio

    async def test_get_projects_via_real_http(self, real_kernel):
        """真实 HTTP：GET /api/v1/projects → 200 + items/total（裸数据，非信封）。

        RED 阶段：inkflow.infrastructure.http 不存在 → lazy import 抛
        ModuleNotFoundError → 本用例 FAILED（预期 RED 形态；GREEN 落地后自动转绿）。
        """
        from inkflow.infrastructure.http import InkFlowHTTPClient

        async with InkFlowHTTPClient(real_kernel.handle) as client:
            data = await client.get("/projects")
        # 全新隔离 DB：空项目列表（端点返回裸数据 {"items": [...], "total": N}）
        assert isinstance(data, dict)
        assert isinstance(data["items"], list)
        assert data["total"] == 0
