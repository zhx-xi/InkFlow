"""#1142 内核引导测试隔离缺陷 — 单元契约（缺陷 A/B 可判定的最小锚点）。

背景（issue #1142）：tests/cli/ 真实内核用例出现 15-19 error，双向对照确认与
Python 版本无关（stock origin/main 同样失败）→ 两个独立缺陷：

缺陷 A —— `ensure_kernel(state_file=None)` 取 import 时快照的 config 单例
    `config` 是模块级 `InkFlowConfig()` 实例，首次 import 读取 INKFLOW_DATA_DIR
    并定型 `data_dir`。测试 fixture 在 import 之后改写 env → 对同进程
    `ensure_kernel()` 无效 → 落到进程启动时的 data_dir，破坏隔离。
    本文件锚点：**改 env 后 `ensure_kernel()` 必须解析到新 data_dir**。

缺陷 B —— 183 分支（互斥被占）无区分能力
    拿不到互斥时无条件 `_poll_state_file(timeout)`，无论持有人是否还在拉起。
    持有人已死（无 kernel.json 产出）时 → 空等满 timeout（60s）后抛
    「等待其他进程拉起内核超时」，无法区分「对方正常拉起中（值得等）」与
    「持有人已死（kernel.json 永不会出现）」。
    本文件锚点：**持有人已死 + 无产出 → 快速失败，不空等满 timeout**。

反例（防过度修复）：显式传 `state_file` 的调用行为不回归（契约不变）。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest

from inkflow.infrastructure.kernel import bootstrap
from inkflow.infrastructure.kernel.kernel_errors import KernelStartupError

# ─────────────────────────────────────────────────────────────────────
# 缺陷 A：state_file 默认值必须反映调用时的 env（非 import 时快照）
# ─────────────────────────────────────────────────────────────────────


def _capture_state_file(monkeypatch) -> list[Path]:
    """让 ensure_kernel 在不真 spawn 的前提下暴露它解析出的 state_file。

    伪互斥（拿到即成功，且 `_release_mutex` 一并 no-op 以避开真实句柄校验）
    + 捕获型 `_poll_state_file`（记录路径后短路返回，避免 60s 轮询与真实
    子进程）。
    """
    captured: list[Path] = []

    def _fake_acquire(name: str = "InkFlowKernelBootstrap"):
        return object()

    def _fake_release(handle: object | None) -> None:
        return  # 伪句柄无真实内核对象，释放是 no-op

    def _fake_poll(path: Path, timeout: float, *, abort_probe=None):
        captured.append(path)
        # 返回 None → ensure_kernel 抛 KernelStartupError，
        # 但 state_file 已被捕获（本测试只关心解析结果）。
        return None  # noqa: RET501  # 显式 None 表明「未就绪」契约，非可省略的尾返回

    monkeypatch.setattr(bootstrap, "_acquire_mutex", _fake_acquire)
    monkeypatch.setattr(bootstrap, "_release_mutex", _fake_release)
    monkeypatch.setattr(bootstrap, "_poll_state_file", _fake_poll)
    return captured


def test_default_state_file_follows_env_set_after_import(tmp_path, monkeypatch):
    """🔴 缺陷 A 主锚点：import 后改写 INKFLOW_DATA_DIR → 默认 state_file 跟随。

    当前实现取 config 单例快照 → 落在旧 data_dir → 本断言 FAIL（RED）。
    """
    isolated = tmp_path / "isolated-data"
    isolated.mkdir()
    monkeypatch.setenv("INKFLOW_DATA_DIR", str(isolated))

    captured = _capture_state_file(monkeypatch)
    with pytest.raises(KernelStartupError):
        import asyncio

        asyncio.run(bootstrap.ensure_kernel(timeout=0.1))

    assert captured, "ensure_kernel 未走到 _poll_state_file（装配缝变更？）"
    assert captured[0] == isolated / "kernel.json", (
        f"默认 state_file 未跟随隔离 env：得到 {captured[0]}，"
        f"期望 {isolated / 'kernel.json'}（config 单例 import 快照未被重解析）"
    )


def test_default_state_file_not_stale_across_two_env_changes(tmp_path, monkeypatch):
    """缺陷 A 变体：连续两次改 env，每次都跟随（排除「只解析一次」的假修复）。"""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    import asyncio

    results: list[Path] = []
    for target in (first, second):
        monkeypatch.setenv("INKFLOW_DATA_DIR", str(target))
        captured = _capture_state_file(monkeypatch)
        with pytest.raises(KernelStartupError):
            asyncio.run(bootstrap.ensure_kernel(timeout=0.1))
        results.append(captured[0])

    assert results == [
        first / "kernel.json",
        second / "kernel.json",
    ], f"默认 state_file 未逐次重解析 env：得到 {results}"


# ─────────────────────────────────────────────────────────────────────
# 反例（防过度修复）：显式传 state_file 的调用契约不变
# ─────────────────────────────────────────────────────────────────────


def test_explicit_state_file_still_honored(tmp_path, monkeypatch):
    """反例：显式传 state_file 时**必须**原样使用（正例调用点零回归）。

    env 指向别处也不得覆盖显式参数。
    """
    explicit = tmp_path / "explicit" / "kernel.json"
    other = tmp_path / "other-env"
    other.mkdir()
    monkeypatch.setenv("INKFLOW_DATA_DIR", str(other))

    captured = _capture_state_file(monkeypatch)
    with pytest.raises(KernelStartupError):
        import asyncio

        asyncio.run(bootstrap.ensure_kernel(state_file=explicit, timeout=0.1))

    assert captured[0] == explicit, f"显式 state_file 被 env 覆盖：{captured[0]}"


# ─────────────────────────────────────────────────────────────────────
# 缺陷 B：183 分支必须与互斥状态联动（持有者释放 → 立即接管）
# ─────────────────────────────────────────────────────────────────────


def test_takes_over_immediately_when_mutex_becomes_available(tmp_path, monkeypatch):
    """🔴 缺陷 B 主锚点：183 期间互斥一可获取就立即接管，不等满 timeout。

    场景：另一实例拿互斥拉起失败（内核秒退、未写 kernel.json）后**释放了互斥**。
    旧实现无条件 `_poll_state_file(timeout)` 空等满 timeout 才报错——明明互斥
    已空闲可以自己拉起，却白等。

    契约：`_acquire_mutex` 在第 N 次调用开始返回句柄 → ensure_kernel 应立刻
    接管互斥走「自行拉起」路径（spawn 被调用），而不是等满 timeout。

    ⚠️ **不得**改用时间窗口推断「持有者已死」：互斥是机器级、真实冷启动约 4.7s，
    持锁 >1s 完全正常（#1142：1.5s grace 曾把正常拉起误判为死亡，3 例回归）。
    唯一可靠信号 = 真的拿到互斥。
    """
    state_file = tmp_path / "kernel.json"
    assert not state_file.exists()

    calls = {"n": 0}
    handle = object()

    def _acquire(name="x"):
        calls["n"] += 1
        # 首次（第 5 步入场）：183 被占；第 2 次起（轮询间隙重探）：可取
        return None if calls["n"] == 1 else handle

    spawned: list[list[str]] = []

    def _spawn(cmd, log_file):
        spawned.append(cmd)
        import subprocess
        import sys as _sys

        return subprocess.Popen([_sys.executable, "-c", "import time; time.sleep(30)"])

    monkeypatch.setattr(bootstrap, "_acquire_mutex", _acquire)
    monkeypatch.setattr(bootstrap, "_release_mutex", lambda h: None)
    monkeypatch.setattr(bootstrap, "_spawn_kernel", _spawn)

    import asyncio

    timeout = 6.0
    start = time.monotonic()
    with contextlib.suppress(KernelStartupError):
        asyncio.run(bootstrap.ensure_kernel(state_file=state_file, timeout=timeout))
    elapsed = time.monotonic() - start

    assert calls["n"] >= 2, "轮询间隙未重探互斥（未与互斥状态联动）"
    assert spawned, (
        f"互斥已可接管却未自行拉起（spawn 未被调用）；耗时 {elapsed:.2f}s / timeout={timeout}s"
    )


def test_waits_while_mutex_holder_produces_state(tmp_path, monkeypatch):
    """反例（防过度修复）：持有人**确实**在拉起（稍后产出 kernel.json）→ 正常等待复用。

    这是 spec §5.1 分支 2 的正例：183 → 轮询等待 → 复用。修复不得把
    此路径一并砍成快速失败。
    """
    state_file = tmp_path / "kernel.json"

    monkeypatch.setattr(bootstrap, "_acquire_mutex", lambda name="x": None)

    # 另一个「进程」（线程）在 0.5s 后写入合法 kernel.json
    import json
    import threading

    def _writer() -> None:
        time.sleep(0.5)
        payload = {
            "port": 39999,
            "token": "tok",
            "pid": 424242,
            "version": "0.14.0",
            "started_at": "2026-09-13T00:00:00+00:00",
        }
        state_file.write_text(json.dumps(payload), encoding="utf-8")

    t = threading.Thread(target=_writer, daemon=True)
    t.start()

    import asyncio

    handle = asyncio.run(bootstrap.ensure_kernel(state_file=state_file, timeout=10.0))
    t.join(timeout=5)

    assert handle.reused is True
    assert handle.port == 39999
