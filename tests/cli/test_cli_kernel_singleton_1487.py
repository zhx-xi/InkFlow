"""#1487 / ADR-066 ②⑤ —— CLI 侧：内核准入冲突退出码 3 + tray-only GUI 拉起（RED）。

- `inkflow serve` 拿不到内核自持互斥 → stdout 打 `INKFLOW_KERNEL_CONFLICT` + **退出码 3**
- `cli/tray_launch.resolve_gui_exe`：检测已安装 GUI（env > 同目录 > 标准安装位置）
- `maybe_launch_tray_gui`：**仅「本次真正拉起内核」**时以 `--tray-only` detach 拉起；
  复用（reused=True）不拉起；检测不到 GUI 不拉起（负例 → 走空闲回收兜底）
- `tray_gui_sink`：包装命令模块 `ensure_kernel`，按 `handle.reused` 决定是否拉起
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli import tray_launch
from inkflow.cli.commands.serve import app as serve_app

runner = CliRunner()


# ── serve：内核自持互斥被占 → 退出码 3 + 冲突行 ───────────────────────────


def test_serve_exits_3_when_lifetime_mutex_taken(tmp_path):
    """🔴 内核拿不到存活期互斥 → 退出码 3 + `INKFLOW_KERNEL_CONFLICT`（不启动服务）。

    可证伪性：去掉准入（旧行为）→ 本用例会尝试真起 uvicorn，退出码非 3。
    """
    with patch("inkflow.cli.commands.serve._acquire_kernel_lifetime_mutex", return_value=None):
        result = runner.invoke(
            serve_app,
            ["--port", "0", "--port-file", str(tmp_path / "kernel.json")],
        )

    assert result.exit_code == 3
    assert "INKFLOW_KERNEL_CONFLICT" in result.stdout


def test_serve_acquires_lifetime_mutex_once(tmp_path):
    """准入原语按 (kind, state_file) 调用恰一次（内核自持）。"""
    handle = object()
    with (
        patch(
            "inkflow.cli.commands.serve._acquire_kernel_lifetime_mutex", return_value=handle
        ) as acquire,
        patch("inkflow.cli.commands.serve._run_server", return_value=12345),
        patch("inkflow.cli.commands.serve._start_idle_watchdog"),
        patch("inkflow.cli.commands.serve._write_kernel_registry"),
    ):
        result = runner.invoke(
            serve_app,
            ["--port", "0", "--port-file", str(tmp_path / "kernel.json")],
        )

    assert result.exit_code == 0
    acquire.assert_called_once()
    kind, state_file = acquire.call_args.args
    assert kind in {"dev", "rc", "prod"}
    assert Path(state_file).name == "kernel.json"


def test_serve_touches_activity_at_ready_before_watchdog(tmp_path):
    """🔴 空闲倒计时**起点 = 就绪时刻**（#1487 实证抓出：从 import 起算 → 刚就绪即被回收）。

    顺序断言：先 `activity_tracker().touch()`（把时钟拨到就绪），后启动看门狗。
    可证伪性：删掉 touch（恢复「import 起算」）→ 本用例 FAIL。
    """
    order: list[str] = []

    def _start_watchdog(*_a: object, **_k: object) -> object:
        order.append("watchdog")
        return SimpleNamespace(stop=lambda: None)

    with (
        patch("inkflow.cli.commands.serve._acquire_kernel_lifetime_mutex", return_value=object()),
        patch("inkflow.cli.commands.serve._run_server", return_value=12345),
        patch("inkflow.cli.commands.serve._write_kernel_registry"),
        patch("inkflow.infrastructure.kernel.idle_reclaim.resolve_idle_timeout", return_value=5.0),
        patch("inkflow.infrastructure.kernel.idle_reclaim.activity_tracker") as tracker,
        patch(
            "inkflow.cli.commands.serve._start_idle_watchdog", side_effect=_start_watchdog
        ) as watchdog,
    ):
        tracker.return_value.touch.side_effect = lambda: order.append("touch")
        result = runner.invoke(
            serve_app, ["--port", "0", "--port-file", str(tmp_path / "kernel.json")]
        )

    assert result.exit_code == 0
    watchdog.assert_called_once()
    assert order == ["touch", "watchdog"]


def test_serve_without_idle_timeout_starts_no_watchdog(tmp_path):
    """阈值未设置（默认）→ 不启动看门狗（手工 serve 常驻语义不变，ADR-030 D2=A 兼容面）。"""
    with (
        patch("inkflow.cli.commands.serve._acquire_kernel_lifetime_mutex", return_value=object()),
        patch("inkflow.cli.commands.serve._run_server", return_value=12345),
        patch("inkflow.cli.commands.serve._write_kernel_registry"),
        patch("inkflow.infrastructure.kernel.idle_reclaim.resolve_idle_timeout", return_value=None),
        patch("inkflow.cli.commands.serve._start_idle_watchdog") as watchdog,
    ):
        result = runner.invoke(
            serve_app, ["--port", "0", "--port-file", str(tmp_path / "kernel.json")]
        )

    assert result.exit_code == 0
    watchdog.assert_not_called()


# ── resolve_gui_exe：检测已安装 GUI ───────────────────────────────────────


def test_resolve_gui_exe_prefers_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "Custom" / "InkFlow.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    monkeypatch.setenv(tray_launch.GUI_EXE_ENV, str(exe))
    assert tray_launch.resolve_gui_exe() == exe


def test_resolve_gui_exe_env_points_to_missing_file_falls_through(tmp_path, monkeypatch):
    monkeypatch.setenv(tray_launch.GUI_EXE_ENV, str(tmp_path / "nope.exe"))
    monkeypatch.setattr(tray_launch, "_sibling_gui_exe", lambda: None)
    monkeypatch.setattr(tray_launch, "_standard_gui_exe", lambda: None)
    assert tray_launch.resolve_gui_exe() is None


def test_resolve_gui_exe_sibling_then_standard(tmp_path, monkeypatch):
    monkeypatch.delenv(tray_launch.GUI_EXE_ENV, raising=False)
    sibling = tmp_path / "InkFlow.exe"
    monkeypatch.setattr(tray_launch, "_sibling_gui_exe", lambda: sibling)
    monkeypatch.setattr(tray_launch, "_standard_gui_exe", lambda: tmp_path / "other.exe")
    assert tray_launch.resolve_gui_exe() == sibling


def test_standard_gui_exe_candidates_cover_install_locations(monkeypatch, tmp_path):
    """标准安装位置候选：%LOCALAPPDATA%\\Programs\\InkFlow 与 %PROGRAMFILES%\\InkFlow。"""
    local = tmp_path / "LocalAppData"
    program_files = tmp_path / "ProgramFiles"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    installed = local / "Programs" / "InkFlow" / "InkFlow.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"x")
    assert tray_launch._standard_gui_exe() == installed


# ── maybe_launch_tray_gui：只在「本次拉起」时拉起 ─────────────────────────


def test_maybe_launch_skips_when_reused(tmp_path, monkeypatch):
    """复用既有内核 → **不**拉起 GUI（内核原始拉起方已保证托盘存在）。"""
    monkeypatch.setenv(tray_launch.GUI_EXE_ENV, str(tmp_path / "InkFlow.exe"))
    with patch("inkflow.cli.tray_launch.subprocess.Popen") as popen:
        assert tray_launch.maybe_launch_tray_gui(reused=True) is None
    popen.assert_not_called()


def test_maybe_launch_skips_when_no_gui(tmp_path, monkeypatch):
    """🔴 负例：检测不到 GUI → 不拉起（走内核空闲回收兜底，决策 3A）。"""
    monkeypatch.delenv(tray_launch.GUI_EXE_ENV, raising=False)
    monkeypatch.setattr(tray_launch, "_sibling_gui_exe", lambda: None)
    monkeypatch.setattr(tray_launch, "_standard_gui_exe", lambda: None)
    with patch("inkflow.cli.tray_launch.subprocess.Popen") as popen:
        assert tray_launch.maybe_launch_tray_gui(reused=False) is None
    popen.assert_not_called()


def test_maybe_launch_spawns_tray_only(tmp_path, monkeypatch):
    """🔴 检测到 GUI + 本次拉起 → 以 `--tray-only` detach 拉起。"""
    exe = tmp_path / "InkFlow.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv(tray_launch.GUI_EXE_ENV, str(exe))
    monkeypatch.delenv(tray_launch.DISABLE_ENV, raising=False)
    popen = MagicMock()
    popen.return_value = SimpleNamespace(pid=4242)
    with patch("inkflow.cli.tray_launch.subprocess.Popen", popen):
        pid = tray_launch.maybe_launch_tray_gui(reused=False)

    assert pid == 4242
    argv = popen.call_args.args[0]
    assert argv[0] == str(exe)
    assert tray_launch.TRAY_ONLY_FLAG in argv
    kwargs = popen.call_args.kwargs
    assert kwargs.get("env", {}).get("INKFLOW_TRAY_ONLY") == "1"


def test_maybe_launch_respects_disable_env(tmp_path, monkeypatch):
    """逃生口 `INKFLOW_NO_TRAY_GUI` → 不拉起（MCP/无头场景）。"""
    exe = tmp_path / "InkFlow.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv(tray_launch.GUI_EXE_ENV, str(exe))
    monkeypatch.setenv(tray_launch.DISABLE_ENV, "1")
    with patch("inkflow.cli.tray_launch.subprocess.Popen") as popen:
        assert tray_launch.maybe_launch_tray_gui(reused=False) is None
    popen.assert_not_called()


def test_maybe_launch_swallows_launch_failure(tmp_path, monkeypatch):
    """拉起失败（GUI 被删 / 权限）→ 静默降级（不阻塞 CLI；兜底走空闲回收）。"""
    exe = tmp_path / "InkFlow.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv(tray_launch.GUI_EXE_ENV, str(exe))
    with patch("inkflow.cli.tray_launch.subprocess.Popen", side_effect=OSError("denied")):
        assert tray_launch.maybe_launch_tray_gui(reused=False) is None


# ── tray_gui_sink：命令模块 ensure_kernel 包装 ────────────────────────────


def test_tray_gui_sink_wraps_ensure_kernel_and_restores(monkeypatch):
    """包装命令模块 `ensure_kernel`：本次拉起 → 触发 tray-only 拉起；退出后还原。"""
    module = SimpleNamespace()

    async def fake_ensure(*_a, **_kw):
        return SimpleNamespace(reused=False)

    module.ensure_kernel = fake_ensure
    monkeypatch.setitem(__import__("sys").modules, "inkflow.cli.commands._fake_for_1487", module)

    launched: list[bool] = []
    monkeypatch.setattr(
        tray_launch, "maybe_launch_tray_gui", lambda *, reused: launched.append(reused)
    )

    import asyncio

    with tray_launch.tray_gui_sink():
        wrapped = module.ensure_kernel
        assert wrapped is not fake_ensure
        asyncio.run(wrapped())

    assert module.ensure_kernel is fake_ensure  # 还原
    assert launched == [False]


def test_tray_gui_sink_does_not_launch_on_reuse(monkeypatch):
    module = SimpleNamespace()

    async def fake_ensure(*_a, **_kw):
        return SimpleNamespace(reused=True)

    module.ensure_kernel = fake_ensure
    monkeypatch.setitem(__import__("sys").modules, "inkflow.cli.commands._fake_for_1487b", module)

    launched: list[bool] = []
    monkeypatch.setattr(
        tray_launch, "maybe_launch_tray_gui", lambda *, reused: launched.append(reused)
    )

    import asyncio

    with tray_launch.tray_gui_sink():
        asyncio.run(module.ensure_kernel())

    assert launched == []


@pytest.mark.parametrize("value", ["1", "true", "on", "yes"])
def test_tray_gui_sink_disabled_by_env(monkeypatch, value):
    monkeypatch.setenv(tray_launch.DISABLE_ENV, value)
    module = SimpleNamespace()

    async def fake_ensure(*_a, **_kw):
        return SimpleNamespace(reused=False)

    module.ensure_kernel = fake_ensure
    monkeypatch.setitem(__import__("sys").modules, "inkflow.cli.commands._fake_for_1487c", module)
    with patch("inkflow.cli.tray_launch.subprocess.Popen") as popen:
        import asyncio

        with tray_launch.tray_gui_sink():
            asyncio.run(module.ensure_kernel())
    popen.assert_not_called()
