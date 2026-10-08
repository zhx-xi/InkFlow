"""CLI 侧「托盘可见」——检测已安装 GUI 并以 **tray-only** 拉起（spec f30 §5 / ADR-066 ⑤）。

用户需求（#1487 需求 2/3，拍板 2A）：**使用 CLI 后系统托盘出现 InkFlow 托盘**；
点击托盘 → 唤醒 / 创建主窗口（复用 F31 既有托盘逻辑）。

落地要点：
- 只在 CLI 会话**本次真正拉起内核**（`ensure_kernel` 返回 ``reused=False``）时拉起
  GUI —— 复用既有内核时，内核的原始拉起方（GUI 或上一次 CLI）已保证托盘存在；
  每条命令都拉起会多付一次 Electron 启动代价（CLI 热路径目标 ~200ms）。
- 检测不到 GUI → **不拉起**，走内核空闲回收兜底（决策 3A）。
- 拉起失败一律静默降级（不阻塞 CLI，不改变退出码）。
- `INKFLOW_NO_TRAY_GUI` 逃生口（MCP / 无头 / 测试）。
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

#: 显式指定 GUI 可执行文件（操作者 / 测试逃生口，优先级最高）
GUI_EXE_ENV = "INKFLOW_GUI_EXE"
#: 关闭「CLI 拉起托盘 GUI」行为（MCP / 无头场景）
DISABLE_ENV = "INKFLOW_NO_TRAY_GUI"
#: tray-only 启动开关（argv；同时注入同名 env 冗余保障）
TRAY_ONLY_FLAG = "--tray-only"
TRAY_ONLY_ENV = "INKFLOW_TRAY_ONLY"
#: GUI 可执行文件名（electron-builder ``productName: InkFlow``）
GUI_EXE_NAME = "InkFlow.exe"
#: NSIS 安装会把安装目录写进该键的每个实例子键（探测链候选 3，#1525）
_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
#: 上述子键下的安装目录值名
_INSTALL_LOCATION_VALUE = "InstallLocation"

_DISABLE_TRUTHY = frozenset({"1", "true", "on", "yes"})


def _exact_exe_in_dir(directory: Path) -> Path | None:
    """在 `directory` 中按**精确大小写**查找 `InkFlow.exe`，返回磁盘上的真实路径。

    Windows 文件系统大小写不敏感——`Path(dir) / "InkFlow.exe"` + `is_file()` 会把同目录的
    **小写 `inkflow.exe`（内核）**误判为 GUI（#1525 根因 1a）。此处逐 entry 比对
    `entry.name == GUI_EXE_NAME`（`os.scandir` 返回磁盘真实名），杜绝大小写假命中。
    目录不存在 / 不可读 → None（静默）。
    """
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name != GUI_EXE_NAME:
                    continue
                if entry.is_file():
                    return Path(entry.path)
    except OSError:
        return None
    return None


def _sibling_gui_exe() -> Path | None:
    """CLI 可执行文件**同目录**的 `InkFlow.exe`（便携/同发行目录形态）。

    精确大小写比对：CLI zip 布局下同目录只有小写 `inkflow.exe`（内核），
    不得作为 GUI 命中（#1525 根因 1a）。
    """
    return _exact_exe_in_dir(Path(sys.executable).parent)


def _registry_gui_exe() -> Path | None:
    """从 `HKCU\\...\\Uninstall\\*` 的 `InstallLocation` 探测 GUI（#1525 根因 1b）。

    NSIS 安装会写该键，据此覆盖 `%LOCALAPPDATA%\\Programs\\` / `%PROGRAMFILES%\\` 之外的
    **自定义安装路径**。注册表不可用 / 键缺失 / 权限异常 / 值非法 → **静默跳过**（返回 None，
    绝不抛）；非 Windows（`sys.platform != "win32"`）→ 直接跳过（不 import `winreg`）。
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY)
    except OSError:
        return None
    with root:
        index = 0
        while True:
            try:
                subkey = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            location = _query_install_location(winreg, root, subkey)
            if not location:
                continue
            exe = _exact_exe_in_dir(Path(location))
            if exe is not None:
                return exe
    return None


def _query_install_location(winreg_mod: Any, root: Any, subkey: str) -> str | None:
    """读子键的 `InstallLocation` 字符串值；打开失败 / 值缺失 / 空 / 非字符串 → None（不抛）。"""
    try:
        sub = winreg_mod.OpenKey(root, subkey)
    except OSError:
        return None
    with sub:
        try:
            value, _ = winreg_mod.QueryValueEx(sub, _INSTALL_LOCATION_VALUE)
        except OSError:
            return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def _standard_gui_exe() -> Path | None:
    """标准安装位置候选（Windows NSIS 默认：%LOCALAPPDATA%\\Programs\\InkFlow\\）。

    同样**精确大小写比对**（`_exact_exe_in_dir`）。
    """
    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "InkFlow")
    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(Path(program_files) / "InkFlow")
    for directory in candidates:
        exe = _exact_exe_in_dir(directory)
        if exe is not None:
            return exe
    return None


def resolve_gui_exe() -> Path | None:
    """检测已安装 GUI（按序命中即用）：

    env `INKFLOW_GUI_EXE` → CLI 同目录（**精确比对**）→ 注册表 `InstallLocation`
    （**精确比对**，#1525 新增）→ 标准安装位置（**精确比对**）。
    """
    override = os.environ.get(GUI_EXE_ENV)
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
    return _sibling_gui_exe() or _registry_gui_exe() or _standard_gui_exe()


def _tray_gui_disabled() -> bool:
    return (os.environ.get(DISABLE_ENV) or "").strip().lower() in _DISABLE_TRUTHY


def maybe_launch_tray_gui(*, reused: bool) -> int | None:
    """本次**真正拉起内核**且检测到 GUI → 以 tray-only detach 拉起；返回 pid 或 None。

    任何失败（GUI 不可执行 / 权限 / 平台限制）→ 静默 None（兜底走内核空闲回收）。
    """
    if reused or _tray_gui_disabled():
        return None
    exe = resolve_gui_exe()
    if exe is None:
        return None
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(
            [str(exe), TRAY_ONLY_FLAG],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, TRAY_ONLY_ENV: "1"},
            creationflags=creationflags,
        )
    except OSError:
        return None
    return proc.pid


def _wrap_ensure_kernel(original: Any) -> Any:
    """包装命令模块的 `ensure_kernel`：成功且**本次拉起** → 触发托盘 GUI 拉起。"""

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        handle = await original(*args, **kwargs)
        if not getattr(handle, "reused", True):
            with contextlib.suppress(Exception):
                maybe_launch_tray_gui(reused=False)
        return handle

    return wrapped


@contextlib.contextmanager
def tray_gui_sink() -> Iterator[None]:
    """CLI 会话内包装已加载命令模块的 `ensure_kernel`（退出还原）。

    与 `cli_log_sink`（#942）同款「包装模块属性」手法：命令函数按模块全局查找
    `ensure_kernel`，包装即生效；**绝不新增调用**（零额外冷启动副作用）。
    子 app 直接经 CliRunner 调用（测试）不经过 CLI 根入口 → 零 patch。
    """
    patched: list[tuple[Any, Any]] = []
    for name, loaded in list(sys.modules.items()):
        if not name.startswith("inkflow.cli.commands"):
            continue
        mod: Any = loaded  # mypy：模块属性赋值需 Any（同 log_bridge 手法）
        original = getattr(mod, "ensure_kernel", None)
        if original is None or not callable(original):
            continue
        mod.ensure_kernel = _wrap_ensure_kernel(original)
        patched.append((mod, original))
    try:
        yield
    finally:
        for module, original in patched:
            module.ensure_kernel = original
