"""#1487 / ADR-066 ② —— 内核侧**可重置空闲回收**的 RED 契约。

- `parse_idle_timeout`：env 值 → 秒数（未设置 / 0 / off / 负数 / 非法 → None = 关闭）
- `resolve_idle_timeout`：读进程 env
- `ActivityTracker`：`touch()` 刷新 → `idle_seconds()` 归零（**可重置**语义）
- `start_idle_watchdog`：空闲超阈 → 回调一次并结束；期间活动刷新 → 不触发
- `activity_tracker()`：进程级单例（HTTP 中间件与看门狗共用同一追踪器）
"""

from __future__ import annotations

import time

import pytest

from inkflow.infrastructure.kernel import idle_reclaim


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("0", None),
        ("0.0", None),
        ("off", None),
        ("OFF", None),
        ("false", None),
        ("-1", None),
        ("abc", None),
        ("1", 1.0),
        ("2", 2.0),
        ("1800", 1800.0),
        (" 1.5 ", 1.5),
        ("30", 30.0),
    ],
)
def test_parse_idle_timeout(raw, expected):
    assert idle_reclaim.parse_idle_timeout(raw) == expected


def test_resolve_idle_timeout_reads_process_env(monkeypatch):
    monkeypatch.delenv(idle_reclaim.IDLE_TIMEOUT_ENV, raising=False)
    assert idle_reclaim.resolve_idle_timeout() is None
    monkeypatch.setenv(idle_reclaim.IDLE_TIMEOUT_ENV, "42")
    assert idle_reclaim.resolve_idle_timeout() == 42.0


def test_activity_tracker_touch_resets_idle():
    """可重置语义：`touch()` 之后 `idle_seconds()` 归零。"""
    now = {"t": 100.0}
    tracker = idle_reclaim.ActivityTracker(clock=lambda: now["t"])
    now["t"] = 130.0
    assert tracker.idle_seconds() == pytest.approx(30.0)
    tracker.touch()
    assert tracker.idle_seconds() == pytest.approx(0.0)
    now["t"] = 131.5
    assert tracker.idle_seconds() == pytest.approx(1.5)


def test_activity_tracker_is_thread_safe_shared_singleton():
    """进程级单例：同一对象（中间件与看门狗共用）。"""
    assert idle_reclaim.activity_tracker() is idle_reclaim.activity_tracker()


def test_watchdog_fires_once_when_idle_exceeds_threshold():
    """空闲超阈 → `on_idle` 恰好一次，线程结束。"""
    calls: list[float] = []
    tracker = idle_reclaim.ActivityTracker()
    thread = idle_reclaim.start_idle_watchdog(
        tracker, timeout=0.15, on_idle=lambda: calls.append(time.monotonic()), interval=0.02
    )
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert len(calls) == 1


def test_watchdog_does_not_fire_while_activity_continues():
    """持续活动（每次 touch 刷新）→ 不触发回收（可重置）。"""
    calls: list[float] = []
    tracker = idle_reclaim.ActivityTracker()
    thread = idle_reclaim.start_idle_watchdog(
        tracker, timeout=0.4, on_idle=lambda: calls.append(time.monotonic()), interval=0.02
    )
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline:
        tracker.touch()
        time.sleep(0.05)
    assert calls == []
    assert thread.is_alive()  # 仍在等待真正空闲 —— 测试收尾
    thread_stop = getattr(thread, "stop", None)
    if callable(thread_stop):  # 实现提供停止原语时用它收尾
        thread_stop()
