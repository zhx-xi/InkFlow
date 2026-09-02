"""S3b C2 进程级并发契约 — 多进程 ensure_kernel 互斥 + 内核启动（M1/M2，真实进程轨）。

M1 门禁：两进程同时冷调用 ensure_kernel（共享同一 state_file）→ 恰一个 spawn
（reused=False），另一个复用（reused=True），kernel.json 单一且合法——绝不双 spawn
（双内核端口/token 冲突）或双 wait-stale 误判。当前实现已有 Windows 命名互斥
（InkFlowKernelBootstrap）+ 状态复用分支，本文件做进程级实证（有 mock 零真实验证）。

M2 门禁：两个真实 SQLite 连接（各自独立进程/连接，均带 busy_timeout）并发写同一
项目 → 不抛 "database is locked"（busy_timeout 进程级未验证）。

⚠️ CI 环境跳过：GitHub Actions Windows runner 沙箱（Session 0）拉起内核秒退
（先例 tests/cli/test_cli_mcp.py）；本机 Windows 11 正常。E2E 不计入覆盖。
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from inkflow.infrastructure.kernel import state


def _skip_ci() -> bool:
    return os.environ.get("CI") == "true"


def _kill_kernel_tree(pid: int) -> None:
    if pid <= 0:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )


_ENSURE_KERNEL_SNIPPET = textwrap.dedent(
    """
    import asyncio, json, sys
    from pathlib import Path
    from inkflow.infrastructure.kernel import ensure_kernel
    state_file = Path(sys.argv[1])
    handle = asyncio.run(
        ensure_kernel(
            state_file=state_file,
            timeout=60.0,
            spawn_cmd=[sys.executable, "-m", "inkflow", "serve",
                       "--port", "0", "--port-file", str(state_file)],
        )
    )
    print(json.dumps({"pid": handle.pid, "reused": handle.reused,
                      "port": handle.port, "token": handle.token}))
    sys.stdout.flush()
    """
)


def _run_ensure_kernel(venv_python: str, state_file: Path, data_dir: Path) -> dict:
    """子进程 ensure_kernel（隔离 INKFLOW_DATA_DIR），返回 {pid,reused,port,token}。"""
    env = os.environ.copy()
    env["INKFLOW_DATA_DIR"] = str(data_dir)
    proc = subprocess.run(
        [venv_python, "-c", _ENSURE_KERNEL_SNIPPET, str(state_file)],
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )
    assert proc.returncode == 0, f"ensure_kernel 子进程失败: {proc.stderr}"
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


@pytest.mark.skipif(_skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）；本机验证")
class TestDualProcessEnsureKernelMutex:
    """M1：两进程同 state_file 并发 ensure_kernel → 恰一 spawn + 一 reuse。"""

    def test_two_processes_exactly_one_spawns(self, tmp_path, monkeypatch) -> None:
        venv_python = sys.executable
        data_dir = tmp_path / "kernel-data"
        data_dir.mkdir(parents=True)
        state_file = data_dir / "kernel.json"
        assert not state_file.exists()

        # 两个真实子进程【并发】ensure_kernel（同一 state_file + 隔离 data_dir）——
        # 用线程近乎同时 launch，才能真正竞争互斥（顺序执行第二个只会直接复用，测不到竞态）。
        import threading

        handles: list[dict] = []
        lock = __import__("threading").Lock()

        def _launch() -> None:
            h = _run_ensure_kernel(venv_python, state_file, data_dir)
            with lock:
                handles.append(h)

        threads = [threading.Thread(target=_launch) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(handles) == 2, f"应有两个 handle，得到 {handles}"

        reused_flags = [h["reused"] for h in handles]
        pids = [h["pid"] for h in handles]
        # M1 核心：恰好一个进程真拉起（reused=False），一个复用（reused=True）
        assert reused_flags.count(False) == 1, f"期望恰一 spawn，得到 {handles}"
        assert reused_flags.count(True) == 1, f"期望恰一 reuse，得到 {handles}"
        # 两个 handle 指向同一内核（同 pid 同 port）
        assert pids[0] == pids[1]
        assert handles[0]["port"] == handles[1]["port"]
        # kernel.json 单一且合法（五字段；pid/port 与 handle 一致）
        st = state.read_kernel_state(state_file)
        assert st is not None
        assert st.pid == pids[0]
        assert st.port == handles[0]["port"]
        assert not (data_dir / "kernel.json.tmp").exists()
        _kill_kernel_tree(pids[0])


@pytest.mark.skipif(_skip_ci(), reason="需真实内核/多进程；本机验证")
class TestConcurrentSqliteWrite:
    """M2：两进程并发写同一 SQLite 项目 → 不抛 'database is locked'（busy_timeout 兜底）。"""

    _WRITE_SNIPPET = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        from inkflow.core.database import apply_sqlite_pragma
        import sqlite3
        db = Path(sys.argv[1])
        conn = sqlite3.connect(str(db))
        try:
            apply_sqlite_pragma(conn)  # busy_timeout 前置（WAL 已由父侧预初始化，无转换竞态）
            for i in range(50):
                conn.execute("INSERT INTO t(v) VALUES ('x%d')" % i)
            conn.commit()
        finally:
            conn.close()
        print("OK")
        """
    )

    def _init_db(self, db: Path) -> None:
        """父侧预初始化 DB：建表 + 置 WAL——消除并发 WAL 转换竞态，专注并发写入。"""
        import sqlite3

        from inkflow.core.database import apply_sqlite_pragma

        conn = sqlite3.connect(str(db))
        try:
            apply_sqlite_pragma(conn)
            conn.execute("CREATE TABLE IF NOT EXISTS t(id INTEGER PRIMARY KEY, v TEXT)")
            conn.commit()
        finally:
            conn.close()

    def test_two_processes_concurrent_writes_no_locked(self, tmp_path) -> None:
        db = tmp_path / "concurrent.db"
        self._init_db(db)
        venv_python = sys.executable
        env = os.environ.copy()
        env["INKFLOW_DATA_DIR"] = str(tmp_path / "cfg")
        Path(env["INKFLOW_DATA_DIR"]).mkdir(parents=True, exist_ok=True)

        def _writer() -> subprocess.CompletedProcess:
            return subprocess.run(
                [venv_python, "-c", self._WRITE_SNIPPET, str(db)],
                capture_output=True,
                text=True,
                timeout=90,
                env=env,
            )

        import threading

        results: list[subprocess.CompletedProcess] = []
        threads = [threading.Thread(target=lambda: results.append(_writer())) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for r in results:
            assert r.returncode == 0, f"并发写失败: {r.stderr}"
            assert "database is locked" not in (r.stderr or "").lower()
            assert r.stdout.strip() == "OK"
