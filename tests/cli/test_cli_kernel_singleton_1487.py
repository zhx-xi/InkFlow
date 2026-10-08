"""#1487 / ADR-066 ②⑤ —— CLI 侧：内核准入冲突退出码 3 + tray-only GUI 拉起（RED）。

- `inkflow serve` 拿不到内核自持互斥 → stdout 打 `INKFLOW_KERNEL_CONFLICT` + **退出码 3**
- `cli/tray_launch.resolve_gui_exe`：检测已安装 GUI（env > 同目录 > 标准安装位置）
- `maybe_launch_tray_gui`：**仅「本次真正拉起内核」**时以 `--tray-only` detach 拉起；
  复用（reused=True）不拉起；检测不到 GUI 不拉起（负例 → 走空闲回收兜底）
- `tray_gui_sink`：包装命令模块 `ensure_kernel`，按 `handle.reused` 决定是否拉起
"""

from __future__ import annotations

import os
import sys
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


def test_serve_idle_watchdog_seam_delegates_and_on_idle_sets_should_exit(tmp_path):
    """#1487：装配缝 `_start_idle_watchdog` 真实委派 + `_on_idle` 置 should_exit。"""
    from inkflow.cli.commands import serve as serve_mod

    captured: dict[str, object] = {}
    server = SimpleNamespace(should_exit=False)

    def _fake_start_watchdog(
        _tracker: object, timeout: float, *, on_idle: object, **_kw: object
    ) -> object:
        captured["timeout"] = timeout
        captured["on_idle"] = on_idle
        return SimpleNamespace(stop=lambda: None)

    with (
        patch("inkflow.cli.commands.serve._acquire_kernel_lifetime_mutex", return_value=object()),
        patch("inkflow.cli.commands.serve._run_server", return_value=12345),
        patch("inkflow.cli.commands.serve._write_kernel_registry"),
        patch("inkflow.infrastructure.kernel.idle_reclaim.resolve_idle_timeout", return_value=1.5),
        patch(
            "inkflow.infrastructure.kernel.idle_reclaim.start_idle_watchdog",
            side_effect=_fake_start_watchdog,
        ),
    ):
        serve_mod._current_server = server
        try:
            result = runner.invoke(
                serve_app, ["--port", "0", "--port-file", str(tmp_path / "kernel.json")]
            )
            assert result.exit_code == 0
            assert captured["timeout"] == 1.5
            on_idle = captured["on_idle"]
            assert callable(on_idle)
            on_idle()
            assert server.should_exit is True
        finally:
            serve_mod._current_server = None


def test_sibling_gui_exe_real_implementation(monkeypatch, tmp_path):
    """`_sibling_gui_exe` 真实实现：同目录无 `InkFlow.exe` → None；有 → 该绝对路径。"""
    fake_python = tmp_path / "python.exe"
    fake_python.write_bytes(b"x")
    monkeypatch.setattr(tray_launch.sys, "executable", str(fake_python))
    assert tray_launch._sibling_gui_exe() is None
    gui = tmp_path / "InkFlow.exe"
    gui.write_bytes(b"x")
    assert tray_launch._sibling_gui_exe() == gui


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
    monkeypatch.setattr(tray_launch, "_registry_gui_exe", lambda: None)  # #1525 新增候选：桩掉
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
    monkeypatch.setattr(tray_launch, "_registry_gui_exe", lambda: None)  # #1525 新增候选：桩掉
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


# ── #1525：探测链两处缺陷（大小写假命中 + 自定义安装路径）─────────────────
# 背景：0.17.0-rc1 产物验证实测——CLI zip 场景托盘 100% 不出现（issue #1525）。
# 1a：`_sibling_gui_exe` 曾用 `is_file()` 的存在性判据，在 Windows 大小写不敏感下
#     假命中同目录的小写内核 `inkflow.exe` → 拉起必然失败（No such option: --tray-only）。
# 1b：探测链缺注册表候选 → 自定义安装路径不可见 → 不拉起。
# 本组测试一律用 tmp_path 造假 exe + winreg 替身，不依赖机器状态/真实注册表。


def test_sibling_gui_exe_ignores_lowercase_kernel_exe(tmp_path, monkeypatch):
    """🔴 1a 回归：同目录只有小写 `inkflow.exe`（CLI zip 内核）→ 不得假命中为 GUI。"""
    kernel = tmp_path / "inkflow.exe"
    kernel.write_bytes(b"k")
    monkeypatch.setattr(tray_launch.sys, "executable", str(kernel))
    assert tray_launch._sibling_gui_exe() is None


def test_sibling_gui_exe_requires_a_regular_file(tmp_path, monkeypatch):
    """精确比对 + 类型判定：同名**目录** `InkFlow.exe` 不算命中。"""
    (tmp_path / "InkFlow.exe").mkdir()
    monkeypatch.setattr(tray_launch.sys, "executable", str(tmp_path / "python.exe"))
    assert tray_launch._sibling_gui_exe() is None


def test_cli_zip_layout_never_launches_kernel_as_gui(tmp_path, monkeypatch):
    """🔴 端到端（1a）：CLI zip 布局（同目录仅内核 `inkflow.exe`，无 GUI / 注册表项 / 标准位置）
    → 不拉起任何进程（杜绝内核被当 GUI 拉起后的 `No such option: --tray-only`）。"""
    cli_dir = tmp_path / "cli-unpacked" / "inkflow"
    cli_dir.mkdir(parents=True)
    kernel = cli_dir / "inkflow.exe"
    kernel.write_bytes(b"k")
    monkeypatch.setattr(tray_launch.sys, "executable", str(kernel))
    monkeypatch.delenv(tray_launch.GUI_EXE_ENV, raising=False)
    monkeypatch.delenv(tray_launch.DISABLE_ENV, raising=False)
    _install_fake_winreg(monkeypatch, {})  # 注册表无 InkFlow 安装项
    monkeypatch.setattr(tray_launch, "_standard_gui_exe", lambda: None)
    with patch("inkflow.cli.tray_launch.subprocess.Popen") as popen:
        assert tray_launch.maybe_launch_tray_gui(reused=False) is None
    popen.assert_not_called()


# ── winreg 替身（最小实现；不触碰真实注册表）────────────────────────────


def _install_fake_winreg(monkeypatch, entries):
    """装 winreg 替身 + 平台置 win32；`entries` = {子键名: {值名: 值}}。"""
    subkeys = {name: _FakeKey(values=values) for name, values in entries.items()}
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinreg(_FakeKey(subkeys=subkeys)))
    monkeypatch.setattr(tray_launch.sys, "platform", "win32")


class _FakeKey:
    """复刻 winreg 句柄（子键枚举 / 子键打开 / 值查询；不存在即抛 OSError）。"""

    def __init__(self, subkeys=None, values=None):
        self._subkeys = dict(subkeys or {})
        self._names = list(self._subkeys)
        self._values = dict(values or {})

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def EnumKey(self, index):  # noqa: N802  # 复刻 winreg API 名（小写化即脱离真实契约）
        if 0 <= index < len(self._names):
            return self._names[index]
        raise OSError("no more subkeys")

    def OpenKey(self, subkey):  # noqa: N802  # 复刻 winreg API 名
        if subkey not in self._subkeys:
            raise FileNotFoundError(subkey)
        return self._subkeys[subkey]

    def QueryValueEx(self, name):  # noqa: N802  # 复刻 winreg API 名
        if name not in self._values:
            raise FileNotFoundError(name)
        return (self._values[name], 1)


class _FakeWinreg:
    """winreg 模块替身：`OpenKey` 同时接受 HKEY 常量与已打开句柄（同真实 winreg）。"""

    HKEY_CURRENT_USER = "HKCU_ROOT"

    def __init__(self, root_key):
        self._root = root_key

    def OpenKey(self, key, sub_key):  # noqa: N802  # 复刻 winreg API 名
        if key == "HKCU_ROOT":
            if sub_key != tray_launch._UNINSTALL_KEY:
                raise FileNotFoundError(sub_key)
            return self._root
        return key.OpenKey(sub_key)

    def EnumKey(self, key, index):  # noqa: N802  # 复刻 winreg API 名（模块级函数）
        return key.EnumKey(index)

    def QueryValueEx(self, key, name):  # noqa: N802  # 复刻 winreg API 名（模块级函数）
        return key.QueryValueEx(name)


def test_registry_gui_exe_finds_custom_install_location(tmp_path, monkeypatch):
    """🔴 1b：注册表 `InstallLocation` 指向自定义安装路径 → 命中该目录的 `InkFlow.exe`。"""
    install_dir = tmp_path / "program" / "InkFlow"
    install_dir.mkdir(parents=True)
    gui = install_dir / "InkFlow.exe"
    gui.write_bytes(b"g")
    _install_fake_winreg(
        monkeypatch,
        {
            "InkFlow_is1": {"InstallLocation": str(install_dir) + os.sep},  # NSIS 常带尾分隔符
            "UnrelatedApp": {"InstallLocation": str(tmp_path / "elsewhere")},
        },
    )
    assert tray_launch._registry_gui_exe() == gui


def test_resolve_gui_exe_falls_through_to_registry(tmp_path, monkeypatch):
    """端到端探测链：env 未设 + 同目录无 GUI → 注册表自定义路径命中。"""
    monkeypatch.delenv(tray_launch.GUI_EXE_ENV, raising=False)
    monkeypatch.setattr(tray_launch, "_sibling_gui_exe", lambda: None)
    install_dir = tmp_path / "custom" / "InkFlow"
    install_dir.mkdir(parents=True)
    gui = install_dir / "InkFlow.exe"
    gui.write_bytes(b"g")
    _install_fake_winreg(monkeypatch, {"InkFlow_is1": {"InstallLocation": str(install_dir)}})
    assert tray_launch.resolve_gui_exe() == gui


def test_registry_gui_exe_skips_when_uninstall_key_missing(monkeypatch):
    """负例：注册表无 Uninstall 键（OpenKey 抛）→ 静默 None，不抛。"""

    class _NoKeyWinreg:
        HKEY_CURRENT_USER = "HKCU_ROOT"

        def OpenKey(self, _hive, path):  # noqa: N802  # 复刻 winreg API 名
            raise FileNotFoundError(path)

    monkeypatch.setitem(sys.modules, "winreg", _NoKeyWinreg())
    monkeypatch.setattr(tray_launch.sys, "platform", "win32")
    assert tray_launch._registry_gui_exe() is None


def test_registry_gui_exe_skips_invalid_values(tmp_path, monkeypatch):
    """负例：子键缺 `InstallLocation` / 值空白 / 值非字符串 / 目录无精确 `InkFlow.exe`
    → 逐项跳过、最终 None，不抛。"""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    _install_fake_winreg(
        monkeypatch,
        {
            "AppNoValue": {},
            "AppBlank": {"InstallLocation": "   "},
            "AppNonStr": {"InstallLocation": 123},
            "AppWrongDir": {"InstallLocation": str(empty_dir)},
        },
    )
    assert tray_launch._registry_gui_exe() is None


def test_registry_gui_exe_skips_unopenable_subkey(tmp_path, monkeypatch):
    """负例：某子键 OpenKey 抛 OSError → 跳过该子键、继续后续候选（命中即止）。"""
    good_dir = tmp_path / "good"
    good_dir.mkdir()
    gui = good_dir / "InkFlow.exe"
    gui.write_bytes(b"g")

    class _Sub:
        def __init__(self, values):
            self._values = values

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def QueryValueEx(self, name):  # noqa: N802  # 复刻 winreg API 名
            if name in self._values:
                return (self._values[name], 1)
            raise FileNotFoundError(name)

    class _Root:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def EnumKey(self, index):  # noqa: N802  # 复刻 winreg API 名
            if index == 0:
                return "Broken"
            if index == 1:
                return "Good"
            raise OSError("end")

        def OpenKey(self, subkey):  # noqa: N802  # 复刻 winreg API 名
            if subkey == "Broken":
                raise OSError("access denied")
            return _Sub({"InstallLocation": str(good_dir)})

    class _Winreg:
        HKEY_CURRENT_USER = "HKCU_ROOT"

        def OpenKey(self, key, sub_key):  # noqa: N802  # 复刻 winreg API 名
            if key == "HKCU_ROOT":
                return _Root()
            return key.OpenKey(sub_key)

        def EnumKey(self, key, index):  # noqa: N802  # 复刻 winreg API 名（模块级函数）
            return key.EnumKey(index)

        def QueryValueEx(self, key, name):  # noqa: N802  # 复刻 winreg API 名（模块级函数）
            return key.QueryValueEx(name)

    monkeypatch.setitem(sys.modules, "winreg", _Winreg())
    monkeypatch.setattr(tray_launch.sys, "platform", "win32")
    assert tray_launch._registry_gui_exe() == gui


def test_registry_gui_exe_noop_on_non_windows(monkeypatch):
    """非 Windows → 跳过注册表探测（不 import winreg、不抛）。"""
    monkeypatch.setattr(tray_launch.sys, "platform", "linux")
    assert tray_launch._registry_gui_exe() is None


def test_registry_gui_exe_survives_missing_winreg(monkeypatch):
    """winreg 不可导入（ImportError）→ 静默 None（`None in sys.modules` 注入 ImportError）。"""
    monkeypatch.setattr(tray_launch.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", None)
    assert tray_launch._registry_gui_exe() is None


def test_standard_gui_exe_returns_none_when_dirs_absent(tmp_path, monkeypatch):
    """标准位置目录不存在 → None（覆盖 scandir 的 OSError 兜底）。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "no-local"))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "no-pf"))
    assert tray_launch._standard_gui_exe() is None


def test_standard_gui_exe_none_without_env(monkeypatch):
    """环境变量缺失 → 无候选 → None。"""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    assert tray_launch._standard_gui_exe() is None
