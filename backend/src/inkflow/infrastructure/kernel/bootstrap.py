"""内核冷启动拉起器 — ensure_kernel（spec §3.2 / §5 冷启动协议）。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from inkflow.infrastructure.kernel import state
from inkflow.infrastructure.kernel.kernel_errors import KernelStartupError


@dataclass(frozen=True)
class KernelHandle:
    """内核访问句柄（spec §2.2）。"""

    port: int
    token: str
    pid: int
    version: str
    started_at: datetime
    reused: bool  # True=复用已有内核；False=本进程拉起


# ── 装配缝（测试 patch 点；全部同步函数）─────────────────────────────


def _locate_kernel_exe() -> Path | None:
    """定位同发行结构的 inkflow.exe（MCP 打包形态：#424 v3 冷启动修复）。

    仅 frozen 且当前可执行文件名为 inkflow-mcp 前缀时生效；候选按顺序，找到即用：
    1. 同目录 inkflow.exe（onedir 未来形态）
    2. 父目录/inkflow/inkflow.exe（CLI zip：inkflow-mcp/ 与 inkflow/ 兄弟目录）
    3. 父目录/inkflow.exe（便携：kernel/mcp/ 的父目录 kernel/inkflow.exe）
    未命中 → None（回退旧行为）。
    """
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable)
    if not exe.name.startswith("inkflow-mcp"):
        return None
    candidates = [
        exe.with_name("inkflow.exe"),
        exe.parent.parent / "inkflow" / "inkflow.exe",
        exe.parent.parent / "inkflow.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _default_spawn_cmd(state_file: Path) -> list[str]:
    """默认 spawn 命令（spec §5.2 多形态）。

    sys.frozen=False → [sys.executable, '-m', 'inkflow', 'serve',
        '--port', '0', '--port-file', str(state_file)]
    sys.frozen=True  → [sys.executable, 'serve', '--port', '0',
        '--port-file', str(state_file)]（可执行文件自身）
    sys.frozen=True + inkflow-mcp（#424 v3）：定位同发行结构兄弟 inkflow.exe；
        未命中回退旧行为并日志告警（兼容异常部署）。
    """
    kernel_exe = _locate_kernel_exe()
    if kernel_exe is not None:
        return [str(kernel_exe), "serve", "--port", "0", "--port-file", str(state_file)]
    if getattr(sys, "frozen", False):
        if Path(sys.executable).name.startswith("inkflow-mcp"):
            _log_kernel_event(
                f"MCP 打包形态未定位到兄弟 inkflow.exe（executable={sys.executable}），"
                "回退 spawn 自身，内核冷启动可能失败"
            )
        return [sys.executable, "serve", "--port", "0", "--port-file", str(state_file)]
    return [sys.executable, "-m", "inkflow", "serve", "--port", "0", "--port-file", str(state_file)]


def _acquire_mutex(name: str = "InkFlowKernelBootstrap") -> object | None:
    """获取单实例互斥：成功 → 句柄；已有实例（Windows 错误码 183）→ None。

    非 Windows 平台返回哨兵对象（无互斥语义，测试全 mock）。
    """
    if sys.platform != "win32":
        return object()
    import ctypes

    handle: object | None = ctypes.windll.kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


def _release_mutex(handle: object | None) -> None:
    """释放互斥句柄（成功与异常路径 finally 调用）。"""
    if handle is None:
        return
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.ReleaseMutex(handle)
        ctypes.windll.kernel32.CloseHandle(handle)


def _spawn_kernel(cmd: list[str], log_file: Path) -> subprocess.Popen:
    """拉起内核进程（detach 语义，spec §5.5）：stdout/stderr 追加写日志文件。"""
    log_handle = open(log_file, "a", encoding="utf-8")  # noqa: SIM115  # 句柄需跨 Popen 生命周期保持打开（子进程继承写入）
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )


def _probe_health(port: int, token: str, timeout: float) -> bool:
    """GET http://127.0.0.1:{port}/health 带 X-InkFlow-Token 头；200 → True。"""
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/health",
        headers={"X-InkFlow-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return bool(resp.status == 200)
    except Exception:
        return False


def _poll_state_file(path: Path, timeout: float) -> state.KernelState | None:
    """轮询 kernel.json（~0.2s 间隔）直至出现合法状态；超时 → None。

    容忍 F19 serve --port-file 四字段交付（缺 started_at 时补当前 UTC
    时间，spec §5.2 双保险；QA 2026-08-07：五字段严格读会使真实冷启动
    轮询永远超时）。
    """
    import time

    deadline = time.monotonic() + timeout
    while True:
        st = state.read_kernel_state(path)
        if st is None:
            st = _read_lenient(path)
        if st is not None:
            return st
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


def _read_lenient(path: Path) -> state.KernelState | None:
    """宽松读：容忍四字段 port-file（F19 交付契约），started_at 补当前 UTC。

    五字段完整文件由 read_kernel_state 优先处理（严格语义），本函数仅在
    严格读失败时兜底——四字段（port/token/pid/version）必须齐全。
    """
    import json as _json

    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        port = data["port"]
        token = data["token"]
        pid = data["pid"]
        version = data["version"]
    except (KeyError, TypeError):
        return None
    if not isinstance(port, int) or isinstance(port, bool):
        return None
    if not isinstance(token, str):
        return None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(version, str):
        return None
    started_at = datetime.now(UTC)
    raw_started = data.get("started_at")
    if isinstance(raw_started, str):
        try:
            started_at = datetime.fromisoformat(raw_started)
        except ValueError:
            started_at = datetime.now(UTC)
    return state.KernelState(
        port=port,
        token=token,
        pid=pid,
        version=version,
        started_at=started_at,
    )


def _log_kernel_event(msg: str) -> None:
    """追加写 %TEMP%/inkflow-kernel.log（带时间戳，spec §6.2）。"""
    log_file = Path(tempfile.gettempdir()) / "inkflow-kernel.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except OSError:
        pass


# ── ensure_kernel（spec §3.2）────────────────────────────────────────


async def ensure_kernel(
    *,
    spawn_cmd: list[str] | None = None,
    timeout: float | None = None,
    health_timeout: float = 2.0,
    state_file: Path | None = None,
    version_check: bool = True,
) -> KernelHandle:
    """确保内核运行并返回访问句柄（spec §5.1 状态机）。

    复用 → KernelHandle(reused=True)；互斥拉起 → KernelHandle(reused=False)。
    失败 → KernelStartupError（消息含 %TEMP%\\inkflow-kernel.log 指引）。
    """
    # 1. timeout 三态（Q1 拍板）：显式参数 > env INKFLOW_KERNEL_TIMEOUT
    #    （float 解析失败回退）> 默认 30.0
    if timeout is None:
        raw = os.environ.get("INKFLOW_KERNEL_TIMEOUT")
        if raw is not None:
            try:
                timeout = float(raw)
            except ValueError:
                timeout = 30.0
        else:
            timeout = 30.0

    # 2. 状态文件路径（函数体内读取 config 单例，非 import 快照）
    if state_file is None:
        from inkflow.core.config import config

        state_file = config.data_dir / "kernel.json"

    # 3. 客户端版本（函数体内属性访问，禁止模块级绑定——测试 patch inkflow.__version__）
    import inkflow

    client_version = inkflow.__version__

    # 4. 复用判定（spec §5.1 分支 1）
    st = state.read_kernel_state(state_file)
    if st is not None:
        alive = state.is_process_alive(st.pid)
        healthy = _probe_health(st.port, st.token, health_timeout)
        compatible = True
        if version_check:
            compatible = state.is_version_compatible(st.version, client_version)
        if alive and healthy and compatible:
            _log_kernel_event(f"复用内核 pid={st.pid} port={st.port} version={st.version}")
            return KernelHandle(
                port=st.port,
                token=st.token,
                pid=st.pid,
                version=st.version,
                started_at=st.started_at,
                reused=True,
            )
        # stale：先备份再拉起（spec §5.1 分支 4）
        state.mark_stale(state_file)
        _log_kernel_event(f"stale 清理 {state_file.name}（pid 死/health 失败/版本不匹配）")

    # 5. 互斥（spec §5.1 分支 2/3）
    mutex_handle = _acquire_mutex("InkFlowKernelBootstrap")
    if mutex_handle is None:
        # 183：其他实例在拉起 → 轮询等待复用
        _log_kernel_event("检测到其他实例拉起中，轮询等待")
        st = _poll_state_file(state_file, timeout)
        if st is None:
            raise KernelStartupError(
                f"等待其他进程拉起内核超时（{timeout:.1f}s）；日志见 %TEMP%\\inkflow-kernel.log"
            )
        _log_kernel_event(f"复用其他实例内核 pid={st.pid} port={st.port}")
        return KernelHandle(
            port=st.port,
            token=st.token,
            pid=st.pid,
            version=st.version,
            started_at=st.started_at,
            reused=True,
        )

    # 6. 拉起（互斥在手；秒退重试 ≤2 次，总尝试 ≤3；finally 释放互斥）
    try:
        attempts = 0
        while True:
            attempts += 1
            cmd = spawn_cmd if spawn_cmd is not None else _default_spawn_cmd(state_file)
            log_file = Path(tempfile.gettempdir()) / "inkflow-kernel.log"
            proc = _spawn_kernel(cmd, log_file)
            _log_kernel_event(f"拉起内核（第 {attempts} 次）pid={proc.pid} cmd={' '.join(cmd)}")
            st = _poll_state_file(state_file, timeout)
            if st is not None:
                # 就绪：把 KernelState 转 dict 写回状态文件（父侧裁定：序列化层收 dict）
                write_payload = {
                    "port": st.port,
                    "token": st.token,
                    "pid": st.pid,
                    "version": st.version,
                    "started_at": st.started_at.isoformat(),
                }
                state.write_kernel_state(state_file, write_payload)
                _log_kernel_event(f"内核就绪 pid={st.pid} port={st.port}")
                return KernelHandle(
                    port=st.port,
                    token=st.token,
                    pid=st.pid,
                    version=st.version,
                    started_at=st.started_at,
                    reused=False,
                )
            if proc.poll() is not None:
                if attempts >= 3:
                    raise KernelStartupError(
                        f"内核启动后立即退出（已尝试 {attempts} 次）；日志见 %TEMP%\\"
                        "inkflow-kernel.log"
                    )
                _log_kernel_event(f"内核秒退（第 {attempts} 次），清理重试")
                continue
            raise KernelStartupError(
                f"内核启动超时（{timeout:.1f}s）；日志见 %TEMP%\\inkflow-kernel.log"
            )
    finally:
        _release_mutex(mutex_handle)
