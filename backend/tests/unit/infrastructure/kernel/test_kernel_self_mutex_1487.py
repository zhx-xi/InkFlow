"""#1487 / ADR-066 ② —— 存活期互斥**由内核进程自持**的 RED 契约。

本文件是 ADR-066 推翻 ADR-059 ②「客户端持有互斥」后的**新契约**（旧契约测试
`test_kernel_concurrency_kind.py` 随 ADR 同步改写）。三层断言：

1. **装配缝**：客户端 `ensure_kernel` **不再**获取存活期互斥（旧实现：`_acquire_lifetime_mutex`
   被客户端调用并持锁至调用方退出）；
2. **装配缝**：内核侧公开准入原语 `hold_lifetime_mutex` + 冲突退出码常量
   `KERNEL_CONFLICT_EXIT_CODE == 3`；
3. **行为**：内核以退出码 3 退出（自持互斥被占）→ `ensure_kernel` 抛 `KernelStartupError`，
   消息含既有实例的 port / pid / data_dir（不静默、不只报「失败」）；
4. **真实 Win32**：同一 data_dir 连起两个内核 → 第二个被拒（真实双进程，最强证据）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import inkflow
from inkflow.infrastructure.kernel import bootstrap as bootstrap_mod
from inkflow.infrastructure.kernel.bootstrap import ensure_kernel
from inkflow.infrastructure.kernel.kernel_errors import KernelStartupError
from inkflow.infrastructure.kernel.state import KernelState

SPAWN_CMD = ["inkflow-dev.exe", "serve", "--port", "0"]


def _state() -> KernelState:
    return KernelState(
        port=8123,
        token="tok-test-123",
        pid=os.getpid(),
        version=inkflow.__version__,
        started_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    )


def _exited_popen(returncode: int) -> MagicMock:
    popen = MagicMock()
    popen.poll.return_value = returncode
    popen.returncode = returncode
    return popen


# ── 装配缝：内核侧公开准入原语 ─────────────────────────────────────────────


def test_hold_lifetime_mutex_and_conflict_exit_code_public_api():
    """内核侧准入原语与冲突退出码是**公开**契约（`serve` 消费）。"""
    assert bootstrap_mod.KERNEL_CONFLICT_EXIT_CODE == 3
    assert callable(bootstrap_mod.hold_lifetime_mutex)
    assert bootstrap_mod.KERNEL_CONFLICT_LINE == "INKFLOW_KERNEL_CONFLICT"


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Win32 互斥语义仅 Windows")
def test_hold_lifetime_mutex_real_two_holders(tmp_path):
    """真实互斥：同一 (kind, state_file) 第二次获取 → None；释放后可再取。"""
    state_file = tmp_path / "kernel.json"
    first = bootstrap_mod.hold_lifetime_mutex("dev", state_file)
    assert first is not None
    try:
        assert bootstrap_mod.hold_lifetime_mutex("dev", state_file) is None
    finally:
        bootstrap_mod._release_mutex(first)
    third = bootstrap_mod.hold_lifetime_mutex("dev", state_file)
    assert third is not None
    bootstrap_mod._release_mutex(third)


# ── 装配缝：客户端不再持有存活期互斥 ───────────────────────────────────────


async def test_ensure_kernel_does_not_acquire_lifetime_mutex(tmp_path):
    """🔴 拉起路径：客户端 `ensure_kernel` 绝不获取存活期互斥（ADR-066 ②）。

    可证伪性：恢复 `_acquire_lifetime_mutex(kind, state_file)` 调用 → 本用例 FAIL。
    """
    handle = object()
    with (
        patch("inkflow.infrastructure.kernel.state.read_kernel_state", return_value=None),
        patch("inkflow.infrastructure.kernel.state.write_kernel_state"),
        patch("inkflow.infrastructure.kernel.state.is_process_alive", return_value=True),
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_mutex", return_value=handle),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex"),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel",
            return_value=_exited_popen(0),
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=_state()),
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event"),
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_lifetime_mutex") as lifetime,
    ):
        result = await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="prod"
        )

    assert result.reused is False
    lifetime.assert_not_called()


async def test_client_no_longer_writes_instance_registry(tmp_path):
    """注册表**由内核自身写**（ADR-066 ③）：客户端拉起成功不再写注册表。"""
    handle = object()
    with (
        patch("inkflow.infrastructure.kernel.state.read_kernel_state", return_value=None),
        patch("inkflow.infrastructure.kernel.state.write_kernel_state"),
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_mutex", return_value=handle),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex"),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel",
            return_value=_exited_popen(0),
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=_state()),
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event"),
        patch("inkflow.infrastructure.kernel.registry.write_instance") as write_instance,
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
        )

    write_instance.assert_not_called()


# ── 行为：退出码 3 → 既有实例冲突（可感知，含 data_dir） ────────────────────


@pytest.mark.parametrize("kind", ["rc", "prod", "dev"])
async def test_conflict_exit_code_3_raises_with_existing_instance_detail(kind, tmp_path):
    """🔴 内核以退出码 3 退出 → 抛 KernelStartupError，消息含既有实例 port/pid/data_dir。

    可证伪性：把退出码 3 当普通秒退重试（旧行为）→ 本用例 FAIL（会抛「启动后立即退出」）。
    """
    handle = object()
    existing = SimpleNamespace(
        kind=kind, pid=4242, port=60001, data_dir="C:/other-data", version="0.17.0", started_at="x"
    )
    with (
        patch("inkflow.infrastructure.kernel.state.read_kernel_state", return_value=None),
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_mutex", return_value=handle),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex"),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel",
            return_value=_exited_popen(3),
        ) as spawn,
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=None),
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event"),
        patch("inkflow.infrastructure.kernel.registry.find_by_kind", return_value=[existing]),
        pytest.raises(KernelStartupError) as exc,
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind=kind
        )

    msg = str(exc.value)
    assert "60001" in msg
    assert "4242" in msg
    assert "C:/other-data" in msg
    spawn.assert_called_once()  # 冲突不重试


async def test_conflict_without_registry_entry_reports_actionable_message(tmp_path):
    """注册表无记录（可能刚退出）→ 仍是明确错误（不静默并存、不退化为裸失败）。"""
    handle = object()
    with (
        patch("inkflow.infrastructure.kernel.state.read_kernel_state", return_value=None),
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_mutex", return_value=handle),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex"),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel", return_value=_exited_popen(3)
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=None),
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event"),
        patch("inkflow.infrastructure.kernel.registry.find_by_kind", return_value=[]),
        pytest.raises(KernelStartupError) as exc,
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="prod"
        )

    assert "已被占用" in str(exc.value)


async def test_conflict_via_state_file_reuse_wins(tmp_path):
    """竞态：内核退出码 3 但状态文件已就绪（对端刚拉起完成）→ 优先复用而非报错。"""
    handle = object()
    with (
        patch(
            "inkflow.infrastructure.kernel.state.read_kernel_state", side_effect=[None, _state()]
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_mutex", return_value=handle),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex"),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel", return_value=_exited_popen(3)
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=None),
        patch("inkflow.infrastructure.kernel.bootstrap._probe_health", return_value=True),
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event"),
    ):
        result = await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="prod"
        )

    assert result.reused is True
    assert result.port == 8123


# ── 真实双进程（Win32）：机器级限 1 名实相符 ───────────────────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="真实内核双进程仅 Windows")
def test_real_second_kernel_same_data_dir_exits_3(tmp_path):
    """🔴 真实内核：同一 data_dir 连起两个 `inkflow serve` → 第二个退出码 3。

    这是「机器级限 1 成立」的最强证据（ADR-066 ①）：互斥在内核进程内获取，
    与拉起方是谁（GUI / CLI / 手工）无关。
    """
    state_file = tmp_path / "kernel.json"
    env = {**os.environ, "INKFLOW_INSTANCE_KIND": "dev", "PYTHONIOENCODING": "utf-8"}
    cmd = [
        sys.executable,
        "-m",
        "inkflow",
        "serve",
        "--port",
        "0",
        "--port-file",
        str(state_file),
    ]
    first = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        assert _wait_for_file(state_file, timeout=120.0), "首个内核未在超时内写 kernel.json"

        second = subprocess.run(cmd, capture_output=True, env=env, timeout=180, check=False)
        assert second.returncode == 3, (
            f"第二个内核应被自持互斥拒绝（退出码 3），实际 {second.returncode}；"
            f"stdout={second.stdout[:400]!r}"
        )
        assert "INKFLOW_KERNEL_CONFLICT" in second.stdout.decode("utf-8", errors="replace")
        # 首个内核不受影响
        assert first.poll() is None
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(first.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=20,
        )
        first.wait(timeout=20)


def _wait_for_file(path: Path, *, timeout: float) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return False
