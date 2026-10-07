"""内核空闲回收 —— **可重置**倒计时（spec f30 §5.5 / ADR-066 ②）。

语义（用户拍板 3A）：
- 记录「最近一次 HTTP 请求时刻」（`ActivityTracker`，中间件每请求 `touch()`）；
- 空闲超阈值 → 内核**自行优雅退出**（`uvicorn.Server.should_exit = True`）→
  存活期互斥随进程退出由 OS 回收、注册表条目删除；
- **可重置**：期间任何 HTTP 请求刷新倒计时（GUI 的 2s `/health` 轮询因此让常驻内核不被回收）；
- 阈值来自 env ``INKFLOW_KERNEL_IDLE_TIMEOUT``（秒）；**未设置 = 关闭**（手工
  ``inkflow serve`` 作长期服务不受影响）。客户端拉起时由 ``_spawn_kernel`` /
  GUI ``spawnKernel`` 注入默认 1800s。

零新依赖：只用 stdlib ``threading`` / ``time``。
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

#: 阈值环境变量（秒，浮点）
IDLE_TIMEOUT_ENV = "INKFLOW_KERNEL_IDLE_TIMEOUT"
#: 客户端拉起内核时的默认阈值（30 min，spec f30 §5.5）
DEFAULT_KERNEL_IDLE_TIMEOUT_SECONDS = 1800.0
#: 视为「关闭」的取值（strip + lower 后比较）
_DISABLED_VALUES = frozenset({"", "0", "0.0", "off", "false", "no", "none", "disabled"})


def parse_idle_timeout(raw: str | None) -> float | None:
    """env 原始值 → 秒数；未设置 / 关闭值 / 负数 / 非法 → ``None``（= 关闭）。

    宽松语义（对齐 kind env 处理）：非法值**不抛错**，按未设置处理。
    """
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _DISABLED_VALUES:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return seconds


def resolve_idle_timeout() -> float | None:
    """读进程 env 解析阈值（内核进程启动时判定一次）。"""
    return parse_idle_timeout(os.environ.get(IDLE_TIMEOUT_ENV))


class ActivityTracker:
    """线程安全的「最近活动时刻」记录（单调时钟，避免系统时间跳变）。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last = clock()

    def touch(self) -> None:
        """刷新活动时刻（每个 HTTP 请求调用）。"""
        with self._lock:
            self._last = self._clock()

    def idle_seconds(self) -> float:
        """距最近一次活动的秒数（恒 ≥ 0）。"""
        with self._lock:
            return max(0.0, self._clock() - self._last)


_ACTIVITY = ActivityTracker()


def activity_tracker() -> ActivityTracker:
    """进程级单例：HTTP 中间件与看门狗共用（内核进程内唯一）。"""
    return _ACTIVITY


class IdleWatchdog(threading.Thread):
    """空闲看门狗：周期性检查，空闲超阈 → ``on_idle()`` **一次**后自行结束。

    ``stop()`` 可提前结束（测试/优雅关闭用）。daemon 线程：不阻塞进程退出。
    """

    def __init__(
        self,
        tracker: ActivityTracker,
        timeout: float,
        on_idle: Callable[[], None],
        interval: float,
    ) -> None:
        super().__init__(name="inkflow-idle-watchdog", daemon=True)
        self._tracker = tracker
        self._timeout = timeout
        self._on_idle = on_idle
        self._interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """请求结束看门狗（幂等）。"""
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            if self._tracker.idle_seconds() >= self._timeout:
                self._on_idle()
                return


def start_idle_watchdog(
    tracker: ActivityTracker,
    timeout: float,
    *,
    on_idle: Callable[[], None],
    interval: float | None = None,
) -> IdleWatchdog:
    """启动看门狗并返回线程（已 start）。

    默认 interval = ``min(5.0, max(0.2, timeout / 4))``——保证测试里 2s 级阈值也在
    0.5s 内被发现，生产 30 min 阈值下每 5s 检查一次（开销可忽略）。
    """
    effective_interval = interval if interval is not None else min(5.0, max(0.2, timeout / 4))
    watchdog = IdleWatchdog(tracker, timeout, on_idle, effective_interval)
    watchdog.start()
    return watchdog
