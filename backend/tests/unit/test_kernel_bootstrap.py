"""F30 内核冷启动基建 — ensure_kernel 测试契约（RED 阶段，spec §3.2/§5/§7/§9）。

本文件为 ``inkflow.infrastructure.kernel.bootstrap``（Issue #166，spec §8
文件结构）定义测试契约。测试不依赖真实内核进程 / 真实互斥 / 真实
%APPDATA% / %TEMP%，一律 mock 模块级装配缝与 state.py 读写——轻量、可靠、
零 I/O 副作用。测试文件本身即「契约」：GREEN 阶段按下方 docstring 实现
bootstrap.py / state.py / kernel_errors.py 后，本文件应全绿。

── GREEN 实现契约 ──

模块路径（全部新建，spec §8）：
- ``inkflow/infrastructure/kernel/__init__.py``：导出 ``ensure_kernel`` /
  ``KernelHandle`` / ``KernelStartupError``（本文件直接 from 具体模块，
  不依赖 __init__ 转发）
- ``inkflow/infrastructure/kernel/bootstrap.py``：本文件被测模块
- ``inkflow/infrastructure/kernel/state.py``：kernel.json 读写（跨模块契约）
- ``inkflow/infrastructure/kernel/kernel_errors.py``：``KernelStartupError``

bootstrap.py 公开契约（spec §3.2 + Q1 拍板）：

    @dataclass(frozen=True)
    class KernelHandle:
        port: int
        token: str
        pid: int
        version: str
        started_at: datetime
        reused: bool          # True=复用已有内核；False=本进程拉起

    async def ensure_kernel(
        *,
        spawn_cmd: list[str] | None = None,   # 覆盖 spawn 命令（测试注入）
        timeout: float | None = None,         # 三态：显式 > env > 默认 30.0
        health_timeout: float = 2.0,          # /health 探测超时（秒）
        state_file: Path | None = None,       # None → config.data_dir/'kernel.json'
        version_check: bool = True,           # major 不同 → 拒绝复用
    ) -> KernelHandle

- timeout 三态优先级（Q1，用户拍板 2026-08-07）：显式参数 > 环境变量
  ``INKFLOW_KERNEL_TIMEOUT``（float() 解析失败回退默认）> 默认 30.0。
  env 在**函数体内调用时**读取（非 import 时快照）。
- state_file=None 时，在**函数体内**从 ``inkflow.core.config.config`` 单例
  读取 ``data_dir`` 并拼 ``kernel.json``（调用时读取，非 import 快照）。
- 版本兼容（Q2）：``kernel.json.version`` 与 ``inkflow.__version__`` 的
  major 相同即复用（minor/patch 容忍）；major 不同 → 视为 stale 清理拉起。
  ``inkflow.__version__`` 须**函数体内**属性访问——禁止模块级
  ``from inkflow import __version__`` 固化绑定（测试以 patch
  ``inkflow.__version__`` 注入，模块级绑定会使 patch 失效）。
- 行为状态机（spec §5.1）：
  1. 复用：读状态 → ``state.is_process_alive(pid)`` True + ``_probe_health``
     True + 版本兼容 → 返回 reused=True；**不**调 _spawn_kernel /
     _acquire_mutex / write_kernel_state / mark_stale。
  2. 拉起（无状态/stale）：_acquire_mutex 成功 → _spawn_kernel → 等待
     （_poll_state_file 与 _probe_health 双保险，先到者）→
     write_kernel_state 写入 → 返回 reused=False。
  3. 互斥 183：_acquire_mutex 返回 None → _poll_state_file 轮询（≤ timeout）
     → 读到合法状态 → 复用返回（不 spawn）。
  4. stale 清理：判定 stale（pid 死 / health 失败 / 版本不匹配）后先调
     ``state.mark_stale`` 重命名备份再拉起。
  5. 超时：拉起等待 / 183 轮询超时 → 抛 KernelStartupError，消息须含日志
     指引（"inkflow-kernel.log"）。
  6. 秒退重试：spawn 后 Popen.poll() 非 None（进程立即退出）→ 清理重试
     ≤2 次（总 spawn 尝试 ≤3）→ 仍失败抛 KernelStartupError。
  7. 互斥生命周期：_acquire_mutex 成功后，成功与异常路径均须
     _release_mutex（finally 语义）。

bootstrap.py 模块级装配缝（测试 patch 点，全部**同步**函数——GREEN 不得
声明 async，测试以 MagicMock 注入；bootstrap 内对 state 成员的访问须经
模块属性（``state.is_process_alive(...)`` 形态）或函数体内 import，禁止
模块级 from-import 固化绑定，否则测试 patch 失效）：

    def _default_spawn_cmd(state_file: Path) -> list[str]
        # sys.frozen=False → [sys.executable, '-m', 'inkflow', 'serve',
        #   '--port', '0', '--port-file', str(state_file)]
        # sys.frozen=True  → [sys.executable, 'serve', '--port', '0',
        #   '--port-file', str(state_file)]（可执行文件自身）
    def _acquire_mutex(name: str = "InkFlowKernelBootstrap") -> object | None
        # Windows CreateMutexW：成功返回句柄；错误码 183（已有实例）→ None
    def _release_mutex(handle) -> None
        # 释放 _acquire_mutex 返回的句柄
    def _spawn_kernel(cmd: list[str], log_file: Path) -> subprocess.Popen
        # Popen(stdout=log_file 打开的文件句柄, stderr=STDOUT,
        #   creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)；
        # log_file = %TEMP%/inkflow-kernel.log（spec §6.2，路径钉死）
    def _probe_health(port: int, token: str, timeout: float) -> bool
        # GET http://127.0.0.1:{port}/health 带 X-InkFlow-Token 头；
        # 200 → True；超时/异常/非 200 → False
    def _poll_state_file(path: Path, timeout: float) -> KernelState | None
        # 轮询 kernel.json（内部 ~0.2s 间隔）直至出现合法状态；超时 → None。
        # 调用形态：(path, timeout)（timeout 为剩余等待秒数，首轮 ≈ 生效超时）
    def _log_kernel_event(msg: str) -> None
        # 追加写 %TEMP%/inkflow-kernel.log（带时间戳；启动/复用/stale/失败）

跨模块依赖契约（state.py / kernel_errors.py，同样待实现——本文件 from-import
属预期 RED；GREEN 落地后自动转绿）：

    @dataclass(frozen=True)
    class KernelState:
        port: int
        token: str
        pid: int
        version: str
        started_at: datetime

    def read_kernel_state(path: Path) -> KernelState | None
        # 文件不存在 / JSON 解析失败 → None（视为无内核）
    def write_kernel_state(path: Path, payload: dict) -> None
        # 原子写（临时文件 + os.replace，复用 serve.py _write_port_file 模式）；
        # payload 键 = port/token/pid/version/started_at（ISO8601 字符串）
    def mark_stale(path: Path) -> Path
        # 重命名 kernel.json → kernel.json.stale-<ts>，返回新路径；
        # 文件不存在 → no-op 返回原 path
    def is_process_alive(pid: int) -> bool
        # **模块级函数**（非 KernelState 方法）；进程存活判定

    class KernelStartupError(Exception): ...
    # 冷启动超时 / INKFLOW_READY 解析失败 / 内核秒退 / spawn 命令缺失

设计假设（父侧未定细节，GREEN 以本文件为准）
--------------------------------------------
- ``is_process_alive`` 为 state.py 模块级函数（测试 patch
  ``inkflow.infrastructure.kernel.state.is_process_alive``）。
- ``write_kernel_state`` 双参形态 (path, payload: dict)——bootstrap 调用时
  须把 KernelState 转为 dict（``dataclasses.asdict`` + ``started_at`` 转
  ISO8601 字符串）再写入（父侧裁定 2026-08-07：state.py 序列化层只收 dict，
  与 test_kernel_state.py 契约一致）；``mark_stale(path) -> Path``（返回新
  路径，文件不存在 no-op 返回原 path）。
- 秒退重试：总 spawn 尝试 ≤3（初始 1 + 重试 ≤2），测试断言 2 ≤ 次数 ≤ 3。
- 互斥句柄在成功与异常路径均释放（finally）。
- _poll_state_file / _probe_health / 全部装配缝为同步函数。
- KernelHandle/KernelState 的 started_at 为 aware datetime（UTC）。

RED 状态说明
------------
bootstrap.py / state.py / kernel_errors.py 均未实现，模块级 from-import 在
收集期抛 ModuleNotFoundError（collected 0 items / 1 error），属预期 RED
信号；GREEN 实现落地后本文件即全绿（全部用例经 unittest.mock.patch 隔离，
不触碰真实内核 / 互斥 / 文件系统 / 网络）。
"""

import asyncio
import dataclasses
import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import inkflow
from inkflow import __version__ as inkflow_version
from inkflow.core.config import config
from inkflow.infrastructure.kernel.bootstrap import (
    KernelHandle,
    _default_spawn_cmd,
    ensure_kernel,
)
from inkflow.infrastructure.kernel.kernel_errors import KernelStartupError
from inkflow.infrastructure.kernel.state import KernelState

SPAWN_CMD = ["inkflow-dev.exe", "serve", "--port", "0"]


def _state() -> KernelState:
    """构造合法 KernelState（默认版本与客户端一致 → 版本校验天然通过）。"""
    return KernelState(
        port=8123,
        token="tok-test-123",
        pid=os.getpid(),
        version=inkflow_version,
        started_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
    )


def _running_popen() -> MagicMock:
    """运行中的内核进程 mock（poll() → None = 未退出）。"""
    popen = MagicMock()
    popen.poll.return_value = None
    return popen


def _exited_popen(*_args, **_kwargs) -> MagicMock:
    """秒退内核进程 mock（poll() → 1 = 已退出），作 side_effect 工厂。

    *args/**kwargs 透传忽略：unittest.mock 会把 spawn 调用实参
    (cmd, log_file) 原样传给 side_effect（父侧 2026-08-07 修复，测试
    自身缺陷——零参签名与 2 参调用矛盾，断言语义不变）。
    """
    popen = MagicMock()
    popen.poll.return_value = 1
    return popen


@pytest.fixture
def kernel_mocks():
    """bootstrap/state 装配缝全量 mock（spec §9：mock Popen + mock 状态文件）。

    默认形态：无内核状态（read→None）、互斥获取成功（handle）、spawn 运行中、
    轮询不就绪（poll→None）、health 200（probe→True）、日志记录。用例按需
    覆盖单个 mock 的 return_value / side_effect。
    """
    handle = object()
    with (
        patch(
            "inkflow.infrastructure.kernel.state.read_kernel_state",
            return_value=None,
        ) as read,
        patch(
            "inkflow.infrastructure.kernel.state.is_process_alive",
            return_value=True,
        ) as alive,
        patch("inkflow.infrastructure.kernel.state.mark_stale") as stale,
        patch("inkflow.infrastructure.kernel.state.write_kernel_state") as write,
        patch(
            "inkflow.infrastructure.kernel.bootstrap._acquire_mutex",
            return_value=handle,
        ) as mutex,
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex") as release,
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel",
            return_value=_running_popen(),
        ) as spawn,
        patch(
            "inkflow.infrastructure.kernel.bootstrap._poll_state_file",
            return_value=None,
        ) as poll,
        patch(
            "inkflow.infrastructure.kernel.bootstrap._probe_health",
            return_value=True,
        ) as probe,
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event") as log,
    ):
        yield SimpleNamespace(
            handle=handle,
            read=read,
            alive=alive,
            stale=stale,
            write=write,
            mutex=mutex,
            release=release,
            spawn=spawn,
            poll=poll,
            probe=probe,
            log=log,
        )


# ── KernelHandle / 装配缝形态 ──────────────────────────────────────────────


def test_kernel_handle_is_frozen_dataclass():
    """KernelHandle 为 frozen dataclass，字段与 spec §2.2 完全一致。"""
    h = KernelHandle(
        port=8123,
        token="tok",
        pid=42,
        version="1.0.0",
        started_at=datetime(2026, 8, 7, tzinfo=UTC),
        reused=False,
    )
    assert {f.name for f in dataclasses.fields(KernelHandle)} == {
        "port",
        "token",
        "pid",
        "version",
        "started_at",
        "reused",
    }
    assert h.reused is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.port = 9999


def test_default_spawn_cmd_source_mode(tmp_path):
    """sys.frozen=False：python -m inkflow serve --port 0 --port-file <sf>。

    spec §5.2 源码/venv 开发形态；本测试运行于普通解释器（无 sys.frozen），
    天然命中 False 分支。
    """
    sf = tmp_path / "kernel.json"
    cmd = _default_spawn_cmd(sf)
    assert cmd == [
        sys.executable,
        "-m",
        "inkflow",
        "serve",
        "--port",
        "0",
        "--port-file",
        str(sf),
    ]


def test_default_spawn_cmd_frozen_mode(tmp_path, monkeypatch):
    """sys.frozen=True：可执行文件自身 + serve 参数（spec §5.2 CLI 打包形态）。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    sf = tmp_path / "kernel.json"
    cmd = _default_spawn_cmd(sf)
    assert cmd == [
        sys.executable,
        "serve",
        "--port",
        "0",
        "--port-file",
        str(sf),
    ]


# ── 复用路径 ───────────────────────────────────────────────────────────────


async def test_ensure_kernel_reuses_running_kernel(tmp_path, kernel_mocks):
    """复用：pid 活 + health 200 + 版本兼容 → reused=True，不 spawn。

    spec §5.1 复用分支：读状态 → pid 存活（state.is_process_alive）+
    _probe_health 200 → 返回 KernelHandle(reused=True)；不触碰互斥 / Popen /
    状态写入（spec §9 场景 1）。
    """
    m = kernel_mocks
    st = _state()
    sf = tmp_path / "kernel.json"
    m.read.return_value = st

    h = await ensure_kernel(state_file=sf)

    assert h.reused is True
    assert h.port == st.port and h.token == st.token and h.pid == st.pid
    assert h.version == st.version and h.started_at == st.started_at
    m.spawn.assert_not_called()
    m.mutex.assert_not_called()
    m.release.assert_not_called()
    m.write.assert_not_called()
    m.stale.assert_not_called()
    m.probe.assert_called_once_with(st.port, st.token, 2.0)
    m.alive.assert_called_once_with(st.pid)
    m.log.assert_called()  # spec §6.2：复用也记日志


async def test_ensure_kernel_health_failure_triggers_stale_relaunch(
    tmp_path, kernel_mocks
):
    """复用失败：pid 活但 /health 非 200 → stale 清理 → 拉起。

    spec §7 行 4：pid 存在但 /health 超时/非 200 → stale → 清理 → 拉起。
    断言 mark_stale 以状态文件路径被调用、spawn 发生、返回 reused=False。
    """
    m = kernel_mocks
    st = _state()
    sf = tmp_path / "kernel.json"
    m.read.return_value = st
    m.probe.return_value = False
    m.poll.return_value = st

    h = await ensure_kernel(state_file=sf)

    m.stale.assert_called_once_with(sf)
    m.spawn.assert_called_once()
    m.release.assert_called_once_with(m.handle)
    assert h.reused is False
    m.log.assert_called()


async def test_ensure_kernel_dead_pid_triggers_stale_relaunch(
    tmp_path, kernel_mocks
):
    """复用失败：pid 不存在（崩溃残留）→ stale 清理 → 拉起。

    spec §7 行 3：kernel.json 存在但 pid 不存在 → stale → 清理 → 拉起。
    """
    m = kernel_mocks
    st = _state()
    sf = tmp_path / "kernel.json"
    m.read.return_value = st
    m.alive.return_value = False
    m.poll.return_value = st

    h = await ensure_kernel(state_file=sf)

    m.stale.assert_called_once_with(sf)
    m.spawn.assert_called_once()
    assert h.reused is False


# ── 拉起路径 ───────────────────────────────────────────────────────────────


async def test_ensure_kernel_spawns_new_kernel_when_no_state(
    tmp_path, kernel_mocks
):
    """拉起：无状态 → 互斥成功 → spawn → 轮询就绪 → 写状态 → reused=False。

    spec §5.1 拉起分支 + §9 场景 2：断言 spawn 收到显式 spawn_cmd 覆盖
    （spec §5.2 GUI 形态）、日志文件名为 inkflow-kernel.log（§6.2 路径钉死）、
    write_kernel_state 收到 (state_file, KernelState)、互斥默认名与释放、
    KernelHandle 字段与就绪状态一致且 reused=False。
    """
    m = kernel_mocks
    st = _state()
    sf = tmp_path / "kernel.json"
    m.poll.return_value = st

    h = await ensure_kernel(state_file=sf, spawn_cmd=SPAWN_CMD)

    m.spawn.assert_called_once()
    assert m.spawn.call_args.args[0] == SPAWN_CMD
    assert m.spawn.call_args.args[1].name == "inkflow-kernel.log"
    assert m.read.call_args.args[0] == sf
    # 父侧裁定（2026-08-07）：write_kernel_state 收 dict（state.py 序列化层契约，
    # 与 test_kernel_state.py 一致）——bootstrap 把 KernelState 转 dict 再写入
    m.write.assert_called_once_with(
        sf,
        {
            "port": st.port,
            "token": st.token,
            "pid": st.pid,
            "version": st.version,
            "started_at": st.started_at.isoformat(),
        },
    )
    assert h.reused is False
    assert h.port == st.port and h.token == st.token and h.pid == st.pid
    assert h.version == st.version and h.started_at == st.started_at
    m.mutex.assert_called_once_with("InkFlowKernelBootstrap")
    m.release.assert_called_once_with(m.handle)
    m.stale.assert_not_called()
    m.log.assert_called()


async def test_ensure_kernel_default_state_file_from_config(
    tmp_path, kernel_mocks, monkeypatch
):
    """state_file=None → config.data_dir/'kernel.json'（调用时读取）。

    契约：默认状态文件路径 = ``inkflow.core.config.config.data_dir / 'kernel.json'``
    （spec §6.1）；spawn 的 --port-file 指向同一路径。
    """
    monkeypatch.setattr(config, "data_dir", tmp_path)
    m = kernel_mocks
    m.poll.return_value = _state()

    h = await ensure_kernel()

    assert m.read.call_args.args[0] == tmp_path / "kernel.json"
    cmd = m.spawn.call_args.args[0]
    assert cmd[cmd.index("--port-file") + 1] == str(tmp_path / "kernel.json")
    assert h.reused is False


# ── 互斥 183 路径 ──────────────────────────────────────────────────────────


async def test_ensure_kernel_mutex_183_polls_and_reuses(tmp_path, kernel_mocks):
    """互斥 183：已有实例在拉起 → 轮询 kernel.json → 复用返回（不 spawn）。

    spec §5.3 竞态防护 + §9 场景 3：_acquire_mutex 返回 None（183）→
    _poll_state_file 轮询 → 读到合法状态 → KernelHandle(reused=True)。
    """
    m = kernel_mocks
    st = _state()
    sf = tmp_path / "kernel.json"
    m.mutex.return_value = None
    m.poll.return_value = st

    h = await ensure_kernel(state_file=sf)

    m.spawn.assert_not_called()
    m.write.assert_not_called()
    m.release.assert_not_called()
    assert h.reused is True
    assert h.port == st.port and h.token == st.token and h.pid == st.pid
    assert m.poll.call_args.args[0] == sf
    m.log.assert_called()


async def test_ensure_kernel_mutex_183_timeout_raises(tmp_path, kernel_mocks):
    """互斥 183 且轮询超时 → KernelStartupError（含日志指引）。

    spec §5.1 183 分支「轮询 ≤ timeout」+ §7 行 6：轮询一直无合法状态 →
    抛 KernelStartupError，消息含 %TEMP%/inkflow-kernel.log 指引。
    """
    m = kernel_mocks
    m.mutex.return_value = None
    m.poll.return_value = None

    with pytest.raises(KernelStartupError) as exc:
        await ensure_kernel(state_file=tmp_path / "kernel.json", timeout=0.3)

    assert "inkflow-kernel.log" in str(exc.value)
    assert m.spawn.call_count == 0
    assert m.poll.call_count >= 1
    m.log.assert_called()


# ── 超时 / 秒退重试 ────────────────────────────────────────────────────────


async def test_ensure_kernel_spawn_wait_timeout_raises(tmp_path, kernel_mocks):
    """拉起等待超时（状态文件与 health 双保险都未就绪）→ KernelStartupError。

    spec §7 行 8：INKFLOW_READY 与端口文件都未到达 → 超时抛错；异常路径
    互斥仍须释放（finally 语义），日志记录失败。
    """
    m = kernel_mocks
    m.poll.return_value = None
    m.probe.return_value = False

    with pytest.raises(KernelStartupError) as exc:
        await ensure_kernel(state_file=tmp_path / "kernel.json", timeout=0.3)

    assert "inkflow-kernel.log" in str(exc.value)
    assert m.release.call_count >= 1
    m.log.assert_called()


async def test_ensure_kernel_immediate_exit_retries_then_raises(
    tmp_path, kernel_mocks
):
    """秒退：spawn 后进程立即退出 → 清理重试 ≤2 → 仍失败抛 KernelStartupError。

    spec §7 行 7：捕获进程退出（Popen.poll() 非 None）→ 清理 → 重试 ≤2 次
    （总 spawn 尝试 ≤3，测试断言 2 ≤ 次数 ≤ 3）→ 失败抛错（含日志指引）。
    """
    m = kernel_mocks
    m.spawn.side_effect = _exited_popen

    with pytest.raises(KernelStartupError) as exc:
        await ensure_kernel(state_file=tmp_path / "kernel.json", timeout=0.5)

    assert 2 <= m.spawn.call_count <= 3
    assert "inkflow-kernel.log" in str(exc.value)
    assert m.release.call_count >= 1
    m.log.assert_called()


# ── 版本校验 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "state_version,client_version",
    [
        ("1.2.0", "2.0.0"),  # 内核旧于客户端
        ("3.1.0", "2.0.0"),  # 内核新于客户端
    ],
)
async def test_ensure_kernel_version_mismatch_refuses_reuse(
    tmp_path, kernel_mocks, monkeypatch, state_version, client_version
):
    """版本 major 不匹配（旧/新于客户端）→ 拒绝复用 → stale 清理拉起。

    spec §5.4 + §7 行 9：kernel.json.version 与 inkflow.__version__ 的 major
    不同 → 视为 stale → 清理 → 拉起匹配版本（仅当客户端能 spawn 自己版本）。
    """
    m = kernel_mocks
    st = dataclasses.replace(_state(), version=state_version)
    sf = tmp_path / "kernel.json"
    m.read.return_value = st
    m.poll.return_value = st
    monkeypatch.setattr(inkflow, "__version__", client_version)

    h = await ensure_kernel(state_file=sf)

    assert h.reused is False
    m.stale.assert_called_once_with(sf)
    m.spawn.assert_called_once()


async def test_ensure_kernel_same_major_different_minor_reuses(
    tmp_path, kernel_mocks, monkeypatch
):
    """major 相同、minor/patch 不同 → 直接复用（Q2：minor/patch 容忍）。"""
    m = kernel_mocks
    m.read.return_value = dataclasses.replace(_state(), version="2.99.0")
    monkeypatch.setattr(inkflow, "__version__", "2.0.0")

    h = await ensure_kernel(state_file=tmp_path / "kernel.json")

    assert h.reused is True
    m.stale.assert_not_called()
    m.spawn.assert_not_called()


async def test_ensure_kernel_version_check_disabled_reuses(
    tmp_path, kernel_mocks, monkeypatch
):
    """version_check=False → 跳过版本校验直接复用（health 仍须通过）。"""
    m = kernel_mocks
    st = dataclasses.replace(_state(), version="1.2.0")
    m.read.return_value = st
    monkeypatch.setattr(inkflow, "__version__", "2.0.0")

    h = await ensure_kernel(
        state_file=tmp_path / "kernel.json",
        version_check=False,
        health_timeout=1.5,
    )

    assert h.reused is True
    m.stale.assert_not_called()
    m.spawn.assert_not_called()
    m.probe.assert_called_once_with(st.port, st.token, 1.5)


# ── timeout 三态优先级（Q1） ───────────────────────────────────────────────


async def test_ensure_kernel_timeout_explicit_param_wins_over_env(
    tmp_path, kernel_mocks, monkeypatch
):
    """timeout 三态①：显式参数 > env INKFLOW_KERNEL_TIMEOUT。"""
    monkeypatch.setenv("INKFLOW_KERNEL_TIMEOUT", "1.0")
    m = kernel_mocks
    m.mutex.return_value = None  # 183 路径，经 _poll_state_file 观测生效超时
    m.poll.return_value = _state()

    h = await ensure_kernel(state_file=tmp_path / "kernel.json", timeout=5.0)

    call = m.poll.call_args
    effective = call.kwargs.get("timeout") if call.kwargs else call.args[1]
    assert effective == pytest.approx(5.0, abs=0.5)
    assert h.reused is True


async def test_ensure_kernel_timeout_env_fallback(tmp_path, kernel_mocks, monkeypatch):
    """timeout 三态②：无显式参数 → env INKFLOW_KERNEL_TIMEOUT 生效。"""
    monkeypatch.setenv("INKFLOW_KERNEL_TIMEOUT", "7.5")
    m = kernel_mocks
    m.mutex.return_value = None
    m.poll.return_value = _state()

    await ensure_kernel(state_file=tmp_path / "kernel.json")

    call = m.poll.call_args
    effective = call.kwargs.get("timeout") if call.kwargs else call.args[1]
    assert effective == pytest.approx(7.5, abs=0.5)


async def test_ensure_kernel_timeout_default_when_env_unset(
    tmp_path, kernel_mocks, monkeypatch
):
    """timeout 三态③：env 未设置 → 默认 30.0（monkeypatch.delenv 确保干净）。"""
    monkeypatch.delenv("INKFLOW_KERNEL_TIMEOUT", raising=False)
    m = kernel_mocks
    m.mutex.return_value = None
    m.poll.return_value = _state()

    await ensure_kernel(state_file=tmp_path / "kernel.json")

    call = m.poll.call_args
    effective = call.kwargs.get("timeout") if call.kwargs else call.args[1]
    assert effective == pytest.approx(30.0, abs=0.5)


async def test_ensure_kernel_timeout_invalid_env_uses_default(
    tmp_path, kernel_mocks, monkeypatch
):
    """timeout 三态④：env 非 float（解析失败）→ 回退默认 30.0。"""
    monkeypatch.setenv("INKFLOW_KERNEL_TIMEOUT", "not-a-float")
    m = kernel_mocks
    m.mutex.return_value = None
    m.poll.return_value = _state()

    await ensure_kernel(state_file=tmp_path / "kernel.json")

    call = m.poll.call_args
    effective = call.kwargs.get("timeout") if call.kwargs else call.args[1]
    assert effective == pytest.approx(30.0, abs=0.5)


# ── 并发竞态 ───────────────────────────────────────────────────────────────


async def test_ensure_kernel_concurrent_calls_spawn_once(tmp_path, kernel_mocks):
    """并发：asyncio.gather 两个 ensure_kernel → 只 spawn 一次。

    spec §5.3 双客户端同时冷调用：互斥 side_effect [handle, None] 模拟单实例
    ——一个获取互斥拉起（reused=False），另一个 183 轮询复用（reused=True）。
    """
    m = kernel_mocks
    m.mutex.side_effect = [m.handle, None]
    m.poll.return_value = _state()
    sf = tmp_path / "kernel.json"

    results = await asyncio.gather(
        ensure_kernel(state_file=sf),
        ensure_kernel(state_file=sf),
    )

    m.spawn.assert_called_once()
    m.write.assert_called_once()
    assert sorted(h.reused for h in results) == [False, True]
