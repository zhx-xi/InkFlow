"""内核冷启动拉起器 — ensure_kernel（spec §3.2 / §5 冷启动协议）。"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from inkflow.infrastructure.kernel import idle_reclaim, registry, state
from inkflow.infrastructure.kernel.instance_kind import (
    normalize_instance_kind,
    resolve_instance_kind,
)
from inkflow.infrastructure.kernel.kernel_errors import KernelStartupError

# 存活期互斥被占后等待对端落 kernel.json 的窗口 = 调用方 timeout（#1192）：
# 对端可能是正在冷启动的实例，窗口须覆盖其完整启动时长；
# 原 5.0s 硬截断在高负载下误报「既有实例已存在」（诊断文案还引导用户去退出一个正在启动的实例）。


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


def _lifetime_mutex_name(kind: str, state_file: Path) -> str:
    """存活期互斥名（spec §5.6 / ADR-059 ②，#1188）。

    - ``dev``：互斥名含 **data_dir 摘要** → 同 data_dir 单内核，不同 data_dir
      （含各 worktree）互不阻塞。目录经 ``resolve()`` + ``lower()`` 归一
      （Windows 大小写不敏感 + 相对/绝对同指一个目录必须同互斥名）。
    - ``rc`` / ``prod``：data_dir 维度**恒定收敛** → 机器级单内核（全局）。

    🔴 「data_dir 是否参与判定」**只在本函数**分支，调用方不得再判 kind——
    将来 rc/prod 若要按 data_dir 分域，改动面 = 本函数一处。
    """
    if kind == "dev":
        data_dir = str(state_file.parent.resolve()).lower()
        key = hashlib.sha256(data_dir.encode("utf-8")).hexdigest()[:16]
        return f"InkFlowKernelDev-{key}"
    return f"InkFlowKernel{kind.capitalize()}"


def _acquire_lifetime_mutex(kind: str, state_file: Path) -> object | None:
    """获取**存活期**互斥（spec §5.6 / ADR-066 ①）：具名互斥体，三 kind 统一走此路。

    与 ``_acquire_mutex``（拉起动作互斥，finally 释放）不同：本互斥表达
    「同互斥名只允许一个内核**存活**」，故**永不释放**——随**内核进程**退出由
    OS 自动回收（互斥名由 ``_lifetime_mutex_name`` 决定；rc/prod 全局各一个、
    dev 按 data_dir 分域）。

    🔴 **持有者 = 内核进程**（ADR-066 ①，修订 ADR-059 ②）：本函数由 ``serve``
    启动路径调用并持有到进程退出；**客户端不得调用**（修订前由 `ensure_kernel`
    客户端持有 → 客户端退出即释放 → 内核存活不受约束 = #1477 的 76 孤儿根因）。

    成功 → 句柄；已被占用（Windows 错误码 183）→ None；非 Windows 平台返回
    哨兵对象（无互斥语义，测试全 mock）。
    """
    if sys.platform != "win32":
        return object()
    import ctypes

    handle: object | None = ctypes.windll.kernel32.CreateMutexW(
        None, False, _lifetime_mutex_name(kind, state_file)
    )
    if not handle:
        return None
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


# ── 内核侧准入原语（spec §5.6 / ADR-066 ①）───────────────────────────────

#: 内核拿不到存活期互斥时的退出码（拉起方据此分流：报既有实例 / 先停旧起新）
KERNEL_CONFLICT_EXIT_CODE = 3
#: 内核冲突行前缀（stdout：人类可读 + 可解析，spec f30 §7 边界 14）
KERNEL_CONFLICT_LINE = "INKFLOW_KERNEL_CONFLICT"


def hold_lifetime_mutex(kind: str, state_file: Path) -> object | None:
    """**内核侧**获取并持有存活期互斥（ADR-066 ①；``serve`` 启动即调）。

    与 ``_acquire_lifetime_mutex`` 同一实现——本函数是面向内核进程的**公开**入口
    （命名表达「持有」语义，避免调用方误以为可释放）。返回句柄须持有到进程退出。
    """
    return _acquire_lifetime_mutex(kind, state_file)


def _spawn_kernel(cmd: list[str], boot_log: Path) -> subprocess.Popen:
    """拉起内核进程（detach 语义，spec §5.5）：stdout/stderr 追加写**引导日志**。

    ⚠️ 1.4（#1477）：目标从「内核运行日志」改为**引导日志**——内核运行日志由内核自己持有
    句柄、由日志库轮转（`kernel_logging.install_kernel_file_sink`）；若 Popen 仍重定向到同一
    文件，就会有两个持有者 ⇒ 库的 rename 轮转必然失败（实测 `WinError 32`）。

    打开句柄前先做启动期归档（spec §6.3）：spawn 早期输出才会落进空的新文件。

    内核子进程的 stdout/stderr **必须**以 UTF-8 写出（#1388）：引导日志与
    ``_log_kernel_event`` 的事件行若混编（内核走 Windows ANSI 代码页 = 简中 CP936/GBK），
    严格 UTF-8 读会在首个非 ASCII 字节抛 ``UnicodeDecodeError``（实测 918MB 文件在
    211,593 字节处崩）→ 排障面反成故障点。
    故显式传 ``env``（增量注入 ``PYTHONIOENCODING=utf-8``，其余继承 ``os.environ``）。
    """
    _rotate_kernel_log(boot_log)
    log_handle = open(boot_log, "a", encoding="utf-8")  # noqa: SIM115  # 句柄需跨 Popen 生命周期保持打开（子进程继承写入）
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    spawn_env: dict[str, str] = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # ADR-066 ②：由**客户端拉起**的内核注入默认空闲回收阈值（未显式设置时）。
    # 手工 `inkflow serve`（不经本函数）不注入 → 空闲回收关闭，行为同 ADR-030 D2=A。
    spawn_env.setdefault(
        idle_reclaim.IDLE_TIMEOUT_ENV,
        str(int(idle_reclaim.DEFAULT_KERNEL_IDLE_TIMEOUT_SECONDS)),
    )
    return subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=spawn_env,
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


def _read_state_now(path: Path) -> state.KernelState | None:
    """立即读一次状态文件（严格读 + 宽松兜底），不轮询（#1142）。"""
    return state.read_kernel_state(path) or _read_lenient(path)


def _poll_state_file(
    path: Path,
    timeout: float,
    *,
    abort_probe: Callable[[], bool] | None = None,
) -> state.KernelState | None:
    """轮询 kernel.json（~0.2s 间隔）直至出现合法状态；超时 → None。

    容忍 F19 serve --port-file 四字段交付（缺 started_at 时补当前 UTC
    时间，spec §5.2 双保险；QA 2026-08-07：五字段严格读会使真实冷启动
    轮询永远超时）。

    abort_probe（#1142）：每轮间隙回调一次，返回 True 表示调用方放弃等待
    （如 183 分支探测到互斥已可接管 / 持有者已死）→ 立即返回 None。
    ``timeout`` 仍是本次调用的等待秒数，调用方据回调自身状态区分
    「等待超时」与「持有者已退出」。
    """
    import time

    deadline = time.monotonic() + timeout
    while True:
        st = _read_state_now(path)
        if st is not None:
            return st
        if time.monotonic() >= deadline:
            return None
        if abort_probe is not None and abort_probe():
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


# ── 内核日志（#1380 启动期归档；#1477 1.4：三文件 + 运行日志分片）─────────

#: 单文件上限 10MB（#1477 拍板默认值；#1380 原为 50MB）
_KERNEL_LOG_MAX_BYTES = 10 * 1024 * 1024
#: 归档保留份数（#1477 拍板 10 份；#1380 原为 2 份）
_KERNEL_LOG_BACKUPS = 10
#: 客户端事件日志文件名（与内核运行日志分离，spec §6.2）
_KERNEL_EVENT_LOG_NAME = "inkflow-kernel-events.log"
#: 内核日志文件名前缀（分片形态：inkflow-kernel-<kind>-<hash8>）
_KERNEL_LOG_PREFIX = "inkflow-kernel"


def _log_fragment(kind: str, state_file: Path) -> str:
    """日志分片后缀 `<kind>-<hash8>`（data_dir 摘要**一律参与**）。

    与 `_lifetime_mutex_name` 的 rc/prod 分支不同（那里 data_dir 不参与）：互斥可以不区分
    数据目录，但**日志分片必须区分**——否则跨数据目录并存的内核（#1487）会争抢同一文件，
    使日志库的 rename 轮转必然失败（#1477 实测矩阵）。
    """
    data_dir = str(state_file.parent.resolve()).lower()
    return f"{kind}-{hashlib.sha256(data_dir.encode('utf-8')).hexdigest()[:8]}"


def kernel_event_log_path() -> Path:
    """客户端事件日志（%TEMP%/inkflow-kernel-events.log）；调用时解析 %TEMP%。"""
    return Path(tempfile.gettempdir()) / _KERNEL_EVENT_LOG_NAME


def kernel_runtime_log_path(kind: str, state_file: Path) -> Path:
    """内核运行日志路径 —— 由**内核自己持有句柄**、由日志库轮转（spec §6.2/§6.3）。"""
    name = f"{_KERNEL_LOG_PREFIX}-{_log_fragment(kind, state_file)}.log"
    return Path(tempfile.gettempdir()) / name


def kernel_boot_log_path(kind: str, state_file: Path) -> Path:
    """引导日志路径 —— spawn 到内核接管 stdout 之间的原始输出（冷启动死因）。"""
    name = f"{_KERNEL_LOG_PREFIX}-{_log_fragment(kind, state_file)}.boot.log"
    return Path(tempfile.gettempdir()) / name


def _log_hint(kind: str, state_file: Path) -> str:
    """错误消息里的日志指引（1.4：路径已分片，不再写死单一文件名）。"""
    return (
        f"日志见 {kernel_boot_log_path(kind, state_file)}"
        f"（引导）与 {kernel_runtime_log_path(kind, state_file)}（内核运行）"
    )


def _backup_path(log_file: Path, index: int) -> Path:
    """归档路径 <log>.N（N=1 最新 … N=backups 最旧）。"""
    return log_file.with_name(f"{log_file.name}.{index}")


def _rotate_kernel_log(
    log_file: Path, *, max_bytes: int | None = None, backups: int | None = None
) -> bool:
    """超大则归档为 .1/.2（最旧被删）；返回是否发生轮转。任何失败都不抛。

    阈值 / 份数默认取模块全局，**调用时**读取（module 全局可被调用方覆盖）。
    归档链（spec §6.3）：删最旧 .N → .N-1 → .N → … → .1 → .2 → log → .1；
    未超限（含文件不存在 / stat 失败）→ 不动任何文件并返回 False。

    并发/幂等（#1380 §5.2）：全程吞 OSError——多内核同时启动时先 rename 的一方胜出，
    后到者源文件已不在（FileNotFoundError）→ 跳过本次归档，绝不阻塞启动、绝不截断。
    os.replace 是原子的，故并发下不会产生半截文件。

    「胜出者独占归档链」的实现要点：先 `os.replace` 把超限文件认领到同目录临时名，
    认领成功才动 `.N` 归档链（认领失败即源文件已被他人归档 → 直接跳过）。若先归档链
    再搬源文件，后到者的 `.1 → .2` 推移会把胜出方刚落下的最新归档顶下去（丢最新一代）。
    """
    if max_bytes is None:
        max_bytes = _KERNEL_LOG_MAX_BYTES
    if backups is None:
        backups = _KERNEL_LOG_BACKUPS
    try:
        if log_file.stat().st_size <= max_bytes:
            return False
    except OSError:
        return False  # 不存在 / 不可读 → 无需归档
    try:
        fd, claim_name = tempfile.mkstemp(dir=log_file.parent, prefix=f"{log_file.name}.rotating-")
    except OSError:
        return False  # 拿不到认领名 → 不归档（不阻塞启动）
    os.close(fd)
    claim = Path(claim_name)
    try:
        os.replace(log_file, claim)
    except OSError:
        with suppress(OSError):
            claim.unlink()  # 认领失败：清掉临时名，原文件未动
        return False
    try:
        oldest = _backup_path(log_file, backups)
        if oldest.exists():
            with suppress(OSError):
                oldest.unlink()
            # 归档件可能被运行中的内核持有 → 删除失败不阻塞下推
        for index in range(backups - 1, 0, -1):
            src = _backup_path(log_file, index)
            if not src.exists():
                continue
            with suppress(OSError):
                os.replace(src, _backup_path(log_file, index + 1))
        os.replace(claim, _backup_path(log_file, 1))
    except OSError:
        # 归档链失败：尽力把已认领的内容放回原路径（内容不丢），仍失败则留在临时名
        with suppress(OSError):
            os.replace(claim, log_file)
        return False  # 归档失败不阻塞启动
    return True


def _log_kernel_event(msg: str) -> None:
    """追加写**客户端事件日志**（带时间戳，spec §6.2；写前归档 §6.3）。

    1.4（#1477）：目标从内核运行日志改为**独立事件日志**——客户端不长期持有句柄，
    `_rotate_kernel_log` 的「认领 + 归档链」对它依然有效（内核运行日志已改为
    内核自持句柄 + 库轮转）。
    """
    log_file = kernel_event_log_path()
    _rotate_kernel_log(log_file)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except OSError:
        pass


def _default_state_file() -> Path:
    """默认状态文件路径：调用时解析 env，非 import 快照（#1142 缺陷 A）。

    优先级等效于新建 ``InkFlowConfig``：进程 env ``INKFLOW_DATA_DIR`` >
    config 单例 ``data_dir``（后者已含 instance.env / 默认目录口径）。
    ``inkflow.core.config.config`` 是 import 时定型的模块级单例，import 之后
    改 env 对它无效——需要隔离的调用方（测试 fixture / 同机多会话）必须让
    默认值在这里重新读一次 env 才生效。
    """
    env_data_dir = os.environ.get("INKFLOW_DATA_DIR")
    if env_data_dir:
        return Path(env_data_dir) / "kernel.json"
    from inkflow.core.config import config

    return config.data_dir / "kernel.json"


def _await_mutex_holder(
    state_file: Path, timeout: float
) -> tuple[state.KernelState | None, object | None]:
    """183 分支（互斥被占）等待他人拉起；持有者释放时接管（#1142 缺陷 B）。

    轮询 kernel.json 等待复用（spec §5.1 分支 2），轮询间隙重试互斥：
    - **拿到互斥** → 前持有者确已释放/退出 → 复检一次状态（可能刚好落盘）：
      就绪则复用，否则把互斥交回调用方自行拉起（复用判定不可省，防两侧都 spawn）；
    - 始终拿不到 → 继续等 state_file 至 timeout（spec §5.3：对方仍在拉起，
      即使超过其正常冷启动耗时也不得误判为「已死」——等待超时是安全失败模式）。

    修复点：旧实现在此无条件等满 timeout，不与互斥状态联动——持有者拉起失败
    （内核秒退、未写 kernel.json）时另一侧空等满 timeout 却拿不到互斥，白白浪费
    时间。现在一旦互斥可接管就立即行动。

    ⚠️ **不得**用时间窗口推断「持有者已死」：互斥名是**机器级**（非按 data_dir
    隔离），且真实冷启动约 4.7s——持锁 >1.5s 完全正常。按计时判定会把正常拉起
    误判为死亡（#1142 实测：引入 1.5s grace 后 test_kernel_concurrency 与
    test_mcp_book_surface_933 共 3 例回归）。唯一可靠信号 = **真的拿到互斥**。
    """
    takeover_handle: object | None = None

    def _probe() -> bool:
        nonlocal takeover_handle
        handle = _acquire_mutex("InkFlowKernelBootstrap")
        if handle is not None:
            takeover_handle = handle
            return True
        return False

    st = _poll_state_file(state_file, timeout=timeout, abort_probe=_probe)
    if st is not None:
        return st, None
    if takeover_handle is not None:
        st = _read_state_now(state_file)
        if st is not None:
            _release_mutex(takeover_handle)
            return st, None
        return None, takeover_handle
    return None, None


# ── 准入冲突（ADR-066 ①）───────────────────────────────────────────────


def _kernel_conflict_error(kind: str, state_file: Path) -> KernelStartupError:
    """内核自持互斥被占 → 可感知的错误（spec f30 §5.6 1.6 修订 / §7 边界 14）。

    消息含既有实例的 `kind` / `port` / `pid` / `data_dir`（注册表查得时）——
    「不得静默并存、也不得只报错」（用户拍板 1B）。注册表按 kind 分域：
    rc/prod 查**机器级**目录（跨 data_dir 的阻塞实例因此可见，修 #1487 根因 ③）。
    """
    existing = registry.find_by_kind(registry.registry_dir_for(kind, state_file), kind)
    detail = (
        f"pid={existing[0].pid} port={existing[0].port} data_dir={existing[0].data_dir}"
        if existing
        else "注册表未记录存活实例（可能刚退出，请稍后重试）"
    )
    return KernelStartupError(
        f"{kind} 内核实例已存在（内核自持存活期互斥 "
        f"{_lifetime_mutex_name(kind, state_file)} 已被占用）：{detail}；"
        "请先退出既有实例再拉起（GUI 换数据目录走「先停旧、起新」）"
    )


# ── ensure_kernel（spec §3.2）────────────────────────────────────────


async def ensure_kernel(
    *,
    spawn_cmd: list[str] | None = None,
    timeout: float | None = None,
    health_timeout: float = 2.0,
    state_file: Path | None = None,
    version_check: bool = True,
    instance_kind: str | None = None,
) -> KernelHandle:
    """确保内核运行并返回访问句柄（spec §5.1 状态机）。

    复用 → KernelHandle(reused=True)；互斥拉起 → KernelHandle(reused=False)。
    失败 → KernelStartupError（消息含**分片后**的日志路径指引，见 `_log_hint`）。
    instance_kind=None → resolve_instance_kind() 自判（spec §2.4.1）；非 dev
    须先取得同 kind 存活期互斥（spec §5.6），被占则抛 KernelStartupError。
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

    # 2. 状态文件路径（调用时解析 env，非 import 快照；#1142 缺陷 A）
    if state_file is None:
        state_file = _default_state_file()

    # 3. 客户端版本（函数体内属性访问，禁止模块级绑定——测试 patch inkflow.__version__）
    import inkflow

    client_version = inkflow.__version__

    # 4. 复用判定（spec §5.1 分支 1，**存活期互斥之前**）：
    #    必须先在，否则同进程/并发的第二个调用方永远复用不到既有内核——
    #    它会撞上本进程已持有且永不释放的存活期互斥 → 被拒（#1171 报错形态）。
    def _try_reuse() -> KernelHandle | None:
        """读状态文件 + pid 存活 + /health + 版本兼容 → 复用句柄；否则 None。"""
        st0 = state.read_kernel_state(state_file)
        if st0 is None:
            return None
        alive = state.is_process_alive(st0.pid)
        healthy = _probe_health(st0.port, st0.token, health_timeout)
        compatible = True
        if version_check:
            compatible = state.is_version_compatible(st0.version, client_version)
        if not (alive and healthy and compatible):
            # stale：先备份再拉起（spec §5.1 分支 4）
            state.mark_stale(state_file)
            _log_kernel_event(f"stale 清理 {state_file.name}（pid 死/health 失败/版本不匹配）")
            return None
        _log_kernel_event(f"复用内核 pid={st0.pid} port={st0.port} version={st0.version}")
        return KernelHandle(
            port=st0.port,
            token=st0.token,
            pid=st0.pid,
            version=st0.version,
            started_at=st0.started_at,
            reused=True,
        )

    reused = _try_reuse()
    if reused is not None:
        return reused

    # 5. 实例类型判定（spec §5.6 / ADR-066 ①，**修订 ADR-059 ②**）：
    #    **客户端不再取存活期互斥**——互斥由**内核进程自持**（`serve` 启动即取、
    #    持锁至自身退出；拿不到 → 退出码 3）。此处仅解析 kind：用于判定注册表
    #    分域目录（rc/prod 机器级 / dev 按 data_dir）与冲突错误消息。
    #    显式传入 → 归一（``release`` 别名 / 大小写 / 空白）；非法显式值回落自判
    #    （宽松语义，与 resolve_instance_kind 对非法 env 的处理一致）。
    kind = normalize_instance_kind(instance_kind) or resolve_instance_kind()

    # 6. 拉起动作互斥（spec §5.1 分支 2/3；**只防双 spawn**，finally 释放）
    mutex_handle = _acquire_mutex("InkFlowKernelBootstrap")
    if mutex_handle is None:
        # 183：其他实例在拉起 → 轮询等待复用（#1142：并区分持有者是否已死）
        _log_kernel_event("检测到其他实例拉起中，轮询等待")
        st, mutex_handle = _await_mutex_holder(state_file, timeout)
        if st is not None:
            _log_kernel_event(f"复用其他实例内核 pid={st.pid} port={st.port}")
            return KernelHandle(
                port=st.port,
                token=st.token,
                pid=st.pid,
                version=st.version,
                started_at=st.started_at,
                reused=True,
            )
        if mutex_handle is None:
            raise KernelStartupError(
                f"等待其他进程拉起内核超时（{timeout:.1f}s）；{_log_hint(kind, state_file)}"
            )
        # 前持有者已退出且未产出状态：接管互斥，继续走第 6 步自行拉起
        _log_kernel_event("前持有者已退出，接管互斥自行拉起内核")

    # 7. 拉起（互斥在手；秒退重试 ≤2 次，总尝试 ≤3；finally 释放互斥）
    try:
        attempts = 0
        while True:
            attempts += 1
            cmd = spawn_cmd if spawn_cmd is not None else _default_spawn_cmd(state_file)
            boot_log = kernel_boot_log_path(kind, state_file)
            proc = _spawn_kernel(cmd, boot_log)
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
                # 全量注册表（spec §2.4.2 / ADR-066 ③）：**由内核自身写**（`serve` 就绪后
                # 自注册、退出时自删）——客户端不再写，确保 GUI 自己 spawn 的内核也可见。
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
                if getattr(proc, "returncode", None) == KERNEL_CONFLICT_EXIT_CODE:
                    # 内核自持互斥被占（ADR-066 ①）：**不重试**——复检复用（对端可能刚
                    # 就绪落盘），否则报既有实例（可感知，含注册表明细）。
                    _log_kernel_event(
                        f"内核拒绝准入（{KERNEL_CONFLICT_LINE} / "
                        f"退出码 {KERNEL_CONFLICT_EXIT_CODE}）"
                    )
                    reused = _try_reuse()
                    if reused is not None:
                        return reused
                    raise _kernel_conflict_error(kind, state_file)
                if attempts >= 3:
                    raise KernelStartupError(
                        f"内核启动后立即退出（已尝试 {attempts} 次）；{_log_hint(kind, state_file)}"
                    )
                _log_kernel_event(f"内核秒退（第 {attempts} 次），清理重试")
                continue
            raise KernelStartupError(
                f"内核启动超时（{timeout:.1f}s）；{_log_hint(kind, state_file)}"
            )
    finally:
        _release_mutex(mutex_handle)
