"""#1488 契约：测试拉起的 `inkflow serve` 内核进程 —— 会话级统一回收。

覆盖三则（对应 issue 验收）：

1. **归属命中的测试内核被回收**（basetemp 锚 / pytest 亲缘锚，两条判据各一例）；
2. **非测试内核不在清理集**（手工常驻内核形态；负例守护，当前 PASS 必须保持）；
3. **清理失败不得让测试 ERROR** —— 枚举/终止失败一律吞掉记日志。

判据载体 = `tests/conftest.py::reclaim_test_kernel_processes`（会话级 autouse fixture
`_reclaim_kernel_processes` 在会话结束调用它）。本文件用**进程替身**承载真实
`inkflow serve` 命令行形态——回收逻辑的唯一输入是 CommandLine + 亲缘链，故替身对判据
等价，而每条断言不必付 ~10s 的真实内核冷启动；另有一条真实内核端到端用例（CI skip，
与本目录既有真实内核轨同规，见 `test_cli_http_kernel.py`）。
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from inkflow.infrastructure.kernel import ensure_kernel
from inkflow.infrastructure.kernel.state import is_process_alive

# tests/conftest.py 的模块真身：`import a.b as x` 可能被包属性遮蔽（先例
# test_cli_kernel.py 用 importlib 取 inkflow.core.config 真身），此处同规。
conftest_mod = importlib.import_module("tests.conftest")

# 外来 pytest pid（非本进程）→ 亲缘锚必然不命中，用于隔离两条归属判据
_FOREIGN_PYTEST_PID = os.getpid() + 987654

# 真实内核冷启动 ~5s（chromadb/BGE 加载）；与 test_cli_http_kernel.py 同口径
_KERNEL_COLD_START_TIMEOUT = 60.0
_STANDIN_LIFETIME_S = 120


def _spawn_kernel_standin(state_file: Path) -> subprocess.Popen:
    """进程替身：CommandLine 形态与 `_spawn_kernel` 产出一致，但不加载内核。

    真实内核命令行 = ``<venv python> -m inkflow serve --port 0 --port-file <state_file>``
    （`bootstrap.py::_default_spawn_cmd`）；替身只把「加载内核」换成 sleep，故对
    「CommandLine + 亲缘链」这两条判据输入等价。`sys.executable` 是 uv shim
    → 替身同样产出 shim + 真解释器两个 python.exe（与真实内核一致的形状）。
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import time; time.sleep({_STANDIN_LIFETIME_S})",
            "-m",
            "inkflow",
            "serve",
            "--port",
            "0",
            "--port-file",
            str(state_file),
        ],
        creationflags=creationflags,
    )


def _kill_quietly(pid: int) -> None:
    """收尾清场（用例自身不依赖被测实现时用；失败静默）。"""
    with contextlib.suppress(Exception):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)


def _wait_dead(pid: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            return
        time.sleep(0.1)


class TestReclaimScope:
    """归属命中：两条判据各一例（#1488 验收 1）。"""

    def test_reclaims_kernel_under_session_basetemp(self, tmp_path, tmp_path_factory):
        """basetemp 锚：state_file 落在会话临时根下（真实测试内核形态）→ 被回收。

        传外来 pytest pid → 亲缘锚必然不命中，命中只能来自 basetemp 判据。
        """
        proc = _spawn_kernel_standin(tmp_path / "kernel" / "kernel.json")
        try:
            assert is_process_alive(proc.pid)
            reclaimed = conftest_mod.reclaim_test_kernel_processes(
                _FOREIGN_PYTEST_PID, str(tmp_path_factory.getbasetemp())
            )
            assert proc.pid in reclaimed, f"basetemp 锚未命中：reclaimed={reclaimed}"
            _wait_dead(proc.pid)
            assert not is_process_alive(proc.pid), "回收后进程仍存活"
        finally:
            _kill_quietly(proc.pid)

    def test_reclaims_kernel_by_pytest_ancestry(self, tmp_path, tmp_path_factory):
        """亲缘锚：state_file 落在 basetemp **之外**（如固定端口 serve）→ 仍被回收。"""
        outside = Path(tempfile.mkdtemp(prefix="inkflow-1488-outside-"))
        proc = _spawn_kernel_standin(outside / "kernel.json")
        try:
            reclaimed = conftest_mod.reclaim_test_kernel_processes(
                os.getpid(), str(tmp_path_factory.getbasetemp())
            )
            assert proc.pid in reclaimed, f"亲缘锚未命中：reclaimed={reclaimed}"
            _wait_dead(proc.pid)
            assert not is_process_alive(proc.pid), "回收后进程仍存活"
        finally:
            _kill_quietly(proc.pid)
            shutil.rmtree(outside, ignore_errors=True)


class TestReclaimSparesNonTestKernels:
    """负例（#1488 验收 2）：清理集不含非测试内核 —— 不得误杀。"""

    def test_spares_kernel_outside_basetemp_and_ancestry(self, tmp_path_factory):
        """手工常驻内核形态：数据目录不在 basetemp 下 + 亲缘链不指向本 pytest → 保留。"""
        manual = Path(tempfile.mkdtemp(prefix="inkflow-1488-manual-"))
        proc = _spawn_kernel_standin(manual / "kernel.json")
        try:
            assert is_process_alive(proc.pid)
            reclaimed = conftest_mod.reclaim_test_kernel_processes(
                _FOREIGN_PYTEST_PID, str(tmp_path_factory.getbasetemp() / "other-session")
            )
            assert proc.pid not in reclaimed, f"误杀非测试内核：reclaimed={reclaimed}"
            assert is_process_alive(proc.pid), "非测试内核被误杀"
        finally:
            _kill_quietly(proc.pid)
            shutil.rmtree(manual, ignore_errors=True)

    def test_spares_non_inkflow_serve_process(self, tmp_path_factory):
        """非内核进程（CommandLine 无 inkflow/serve）永不进入清理集。"""
        proc = subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({_STANDIN_LIFETIME_S})"],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            reclaimed = conftest_mod.reclaim_test_kernel_processes(
                os.getpid(), str(tmp_path_factory.getbasetemp())
            )
            assert proc.pid not in reclaimed
            assert is_process_alive(proc.pid)
        finally:
            _kill_quietly(proc.pid)


class TestReclaimNeverRaises:
    """#1488 验收 3：清理失败不得把测试 ERROR（当前无此路径 → 新增）。"""

    def test_enumeration_failure_is_swallowed(self, monkeypatch):
        """枚举失败（无 powershell / 超时）→ 返回空表且不抛。"""

        def _boom() -> list[tuple[int, int, str]]:
            raise OSError("powershell 不可用")

        monkeypatch.setattr(conftest_mod, "enumerate_processes", _boom)
        assert conftest_mod.reclaim_test_kernel_processes(os.getpid(), r"C:\x") == []

    def test_kill_failure_is_swallowed(self, monkeypatch, tmp_path_factory):
        """终止失败（进程已退出 / 权限不足）→ 不抛、不计入结果。"""
        base = str(tmp_path_factory.getbasetemp())
        fake_rows = [(4242, 1, f"python.exe -m inkflow serve --port 0 --port-file {base}\\k.json")]

        def _boom(pid: int) -> None:
            raise PermissionError(f"拒绝访问 pid={pid}")

        monkeypatch.setattr(conftest_mod, "enumerate_processes", lambda: list(fake_rows))
        monkeypatch.setattr(conftest_mod, "terminate_process_tree", _boom)
        assert conftest_mod.reclaim_test_kernel_processes(os.getpid(), base) == []


class TestReclaimRegistered:
    """「统一后置处理」必须真的挂上（防止 helper 存在但无人调用的假闭环）。"""

    def test_session_autouse_fixture_declared(self, request):
        """回收 fixture 必须「已注册 + 会话级 + autouse」——否则形同虚设。

        内省属性名随 pytest 版本漂移（9.x = `_fixture_function_marker`，
        8.x = `_pytestfixturefunction`），两者都认。
        """
        fixture_defs = request.session._fixturemanager.getfixturedefs(
            "_reclaim_kernel_processes", request.node
        )
        assert fixture_defs, "会话级回收 fixture 未注册"
        assert fixture_defs[-1].scope == "session"
        fixture = conftest_mod._reclaim_kernel_processes
        marker = getattr(fixture, "_fixture_function_marker", None) or getattr(
            fixture, "_pytestfixturefunction", None
        )
        assert marker is not None, "回收 fixture 未经 @pytest.fixture 装饰"
        assert marker.autouse is True, "回收 fixture 必须 autouse（否则不会自动跑）"


class TestReclaimRealKernel:
    """真实内核端到端：真实 `inkflow serve`（含 uv shim 父链）被归属并回收。"""

    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="GitHub Actions runner 沙箱无法拉起真实内核（秒退）；本机验证",
    )
    def test_reclaims_real_inkflow_serve_kernel(self, tmp_path, tmp_path_factory):
        state_file = tmp_path / "kernel" / "kernel.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        prev_data_dir = os.environ.get("INKFLOW_DATA_DIR")
        os.environ["INKFLOW_DATA_DIR"] = str(tmp_path / "kernel-data")
        try:
            handle = asyncio.run(
                ensure_kernel(state_file=state_file, timeout=_KERNEL_COLD_START_TIMEOUT)
            )
            assert is_process_alive(handle.pid)
            reclaimed = conftest_mod.reclaim_test_kernel_processes(
                os.getpid(), str(tmp_path_factory.getbasetemp())
            )
            assert handle.pid in reclaimed, f"真实内核未被归属：reclaimed={reclaimed}"
            _wait_dead(handle.pid)
            assert not is_process_alive(handle.pid), "真实内核回收后仍存活"
        finally:
            if prev_data_dir is None:
                os.environ.pop("INKFLOW_DATA_DIR", None)
            else:
                os.environ["INKFLOW_DATA_DIR"] = prev_data_dir


class TestMirrorRootParity:
    """两套 pytest 根的回收实现镜像同源（防重复实现漂移）。"""

    def test_backend_root_is_a_faithful_mirror(self):
        repo_root = next(
            parent
            for parent in Path(__file__).resolve().parents
            if (parent / "backend" / "conftest.py").is_file()
        )
        spec = importlib.util.spec_from_file_location(
            "_inkflow_backend_conftest_probe", repo_root / "backend" / "conftest.py"
        )
        assert spec is not None and spec.loader is not None
        backend_conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend_conf)

        assert callable(getattr(backend_conf, "reclaim_test_kernel_processes", None))
        assert callable(getattr(backend_conf, "_reclaim_kernel_processes", None))
        # 判据逐例同源（两处必须同步改动）
        parents = {10: 20, 20: 30}
        base = r"c:\tmp\pytest-of-x\pytest-1"
        cases = [
            # (cmdline, pid, pytest_pid, basetemp)
            ("python -m inkflow serve --port 0", 10, 30, ""),  # 亲缘命中
            ("python -m inkflow serve --port 0", 10, 999, base),  # 都不中
            (f"python -m inkflow serve --port-file {base}\\k.json", 77, 999, base),  # basetemp 命中
            ("python -c pass", 10, 30, ""),  # 非内核
        ]
        for cmdline, pid, pytest_pid, basetemp in cases:
            assert backend_conf.is_test_kernel(
                cmdline, pid, parents, pytest_pid=pytest_pid, basetemp=basetemp
            ) == conftest_mod.is_test_kernel(
                cmdline, pid, parents, pytest_pid=pytest_pid, basetemp=basetemp
            ), f"两处判据漂移：{cmdline!r} pid={pid}"
