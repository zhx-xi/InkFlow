"""F30 1.2 按实例类型的并发准入契约（#1153 / ADR-059 ②，spec §5.6）。

核心语义（ADR-059 ②，**修订 ADR-030 ②**）：

| kind      | 策略                          | 互斥名                     |
|-----------|-------------------------------|----------------------------|
| rc        | 机器级**存活期**互斥（限 1）   | InkFlowKernelRc            |
| release   | 机器级**存活期**互斥（限 1）   | InkFlowKernelRelease       |
| dev       | 允许多开（仅防双 spawn）       | InkFlowKernelBootstrap（既有）|

「存活期」= 持锁到进程退出，**不在 ensure_kernel 返回前释放**
（修订前缺陷：finally 释放 → 只防双 spawn，不阻止多内核存活）。

RED 契约（实现须满足）：
- 新装配缝 ``bootstrap._acquire_lifetime_mutex(kind) -> object | None``
  （kind ∈ {rc, release}；成功 → 句柄，失败 → None）
- ``ensure_kernel`` 接受 ``instance_kind: str | None = None``（None → resolve_instance_kind()）
- rc/release 准入失败 → 抛 KernelStartupError，消息含既有实例的 port/pid/data_dir
- dev → **不调用** _acquire_lifetime_mutex（多开）
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import inkflow
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
        started_at=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
    )


def _running_popen() -> MagicMock:
    popen = MagicMock()
    popen.poll.return_value = None
    return popen


@pytest.fixture
def mocks():
    """bootstrap/state 装配缝 mock + 新增存活期互斥缝（默认：获取成功）。"""
    handle = object()
    with (
        patch("inkflow.infrastructure.kernel.state.read_kernel_state", return_value=None) as read,
        patch("inkflow.infrastructure.kernel.state.is_process_alive", return_value=True),
        patch("inkflow.infrastructure.kernel.state.mark_stale"),
        patch("inkflow.infrastructure.kernel.state.write_kernel_state"),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._acquire_mutex",
            return_value=handle,
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex"),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel",
            return_value=_running_popen(),
        ),
        patch(
            "inkflow.infrastructure.kernel.bootstrap._poll_state_file",
            return_value=_state(),
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._probe_health", return_value=True),
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event"),
        patch(
            "inkflow.infrastructure.kernel.registry.write_instance",
            return_value=None,
        ) as write_instance,
        patch(
            "inkflow.infrastructure.kernel.bootstrap._acquire_lifetime_mutex",
            return_value=handle,
        ) as lifetime,
        patch("inkflow.infrastructure.kernel.registry.find_by_kind", return_value=[]) as find_kind,
    ):
        yield SimpleNamespace(
            handle=handle,
            read=read,
            lifetime=lifetime,
            write_instance=write_instance,
            find_kind=find_kind,
        )


# ── dev：允许多开 ──────────────────────────────────────────────────────────


async def test_dev_does_not_acquire_lifetime_mutex(tmp_path, mocks):
    """🔴 dev → 不获取存活期互斥（多个 dev 内核可同时存活）。"""
    await ensure_kernel(
        state_file=tmp_path / "kernel.json",
        spawn_cmd=SPAWN_CMD,
        instance_kind="dev",
    )
    mocks.lifetime.assert_not_called()


async def test_two_dev_instances_both_spawn(tmp_path, mocks):
    """🔴 两个 dev 实例均成功拉起（多开放行）——用户拍板核心行为。"""
    h1 = await ensure_kernel(
        state_file=tmp_path / "a" / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
    )
    h2 = await ensure_kernel(
        state_file=tmp_path / "b" / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
    )

    assert h1.reused is False
    assert h2.reused is False


# ── rc / release：存活期互斥 ───────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["rc", "release"])
async def test_rc_release_acquire_lifetime_mutex(kind, tmp_path, mocks):
    """rc/release → 获取存活期互斥（成功路径正常拉起）。"""
    await ensure_kernel(
        state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind=kind
    )
    mocks.lifetime.assert_called_once_with(kind)


@pytest.mark.parametrize("kind", ["rc", "release"])
async def test_second_same_kind_instance_rejected(kind, tmp_path, mocks):
    """🔴 同 kind 第二个实例被拒（互斥已被占用）→ KernelStartupError。"""
    mocks.lifetime.return_value = None  # 互斥被占
    existing = SimpleNamespace(pid=4242, port=60001, data_dir="C:/existing", kind=kind)
    mocks.find_kind.return_value = [existing]

    with pytest.raises(KernelStartupError):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind=kind
        )


@pytest.mark.parametrize("kind", ["rc", "release"])
async def test_rejection_message_names_existing_instance(kind, tmp_path, mocks):
    """拒绝消息须含既有实例的 port / pid / data_dir（可感知，不静默）。"""
    mocks.lifetime.return_value = None
    mocks.find_kind.return_value = [
        SimpleNamespace(pid=4242, port=60001, data_dir="C:/existing", kind=kind)
    ]

    with pytest.raises(KernelStartupError) as exc:
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind=kind
        )

    msg = str(exc.value)
    assert "60001" in msg
    assert "4242" in msg
    assert "C:/existing" in msg


@pytest.mark.parametrize("kind", ["rc", "release"])
async def test_rejection_does_not_spawn(kind, tmp_path, mocks):
    """被拒时绝不 spawn（不进拉起分支）。"""
    mocks.lifetime.return_value = None
    with (
        patch("inkflow.infrastructure.kernel.bootstrap._spawn_kernel") as spawn,
        pytest.raises(KernelStartupError),
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind=kind
        )
    spawn.assert_not_called()


async def test_rc_and_release_do_not_block_each_other(tmp_path, mocks):
    """跨 kind 互不阻塞（rc 与 release 各允许 1 个）——互斥名按 kind 区分。"""
    await ensure_kernel(state_file=tmp_path / "r.json", spawn_cmd=SPAWN_CMD, instance_kind="rc")
    await ensure_kernel(
        state_file=tmp_path / "v.json", spawn_cmd=SPAWN_CMD, instance_kind="release"
    )

    called = [c.args[0] for c in mocks.lifetime.call_args_list]
    assert called == ["rc", "release"]


async def test_lifetime_mutex_not_released_before_return(tmp_path, mocks):
    """🔴 存活期语义：rc 拉起成功后，**只有**拉起动作互斥被释放，
    存活期互斥句柄保持打开（持锁至进程退出，spec §5.6 / ADR-059 ②）。

    判据（可失败的真实信号）：`_release_mutex` 恰被调用一次（拉起动作互斥，
    InkFlowKernelBootstrap），而 `_acquire_lifetime_mutex` 返回的句柄**从未**
    进入任何释放调用——bootstrap 模块内不存在存活期释放函数（若未来有人加上
    并在成功路径调用，本用例通过 `_acquire_lifetime_mutex` 返回值的复用次数
    与 `_release_mutex` 的实参比对捕获）。

    语义澄清：`_release_mutex(x)` 若被传入存活期句柄即为缺陷（会把准入退化成
    「只防双 spawn」）——故断言其实参永远是拉起动作互斥的句柄。
    """
    lifetime_handle = object()
    bootstrap_handle = object()
    mocks.lifetime.return_value = lifetime_handle
    with (
        patch(
            "inkflow.infrastructure.kernel.bootstrap._acquire_mutex",
            return_value=bootstrap_handle,
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex") as release,
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="rc"
        )

    # 拉起动作互斥被释放一次；存活期互斥从未被释放（实参不是它的句柄）
    release.assert_called_once_with(bootstrap_handle)
    assert lifetime_handle not in [c.args[0] for c in release.call_args_list]


async def test_dev_still_uses_bootstrap_mutex(tmp_path, mocks):
    """dev 仍走既有拉起动作互斥（防双 spawn 语义保留）。"""
    with patch(
        "inkflow.infrastructure.kernel.bootstrap._acquire_mutex", return_value=object()
    ) as bootstrap_mutex:
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
        )
    bootstrap_mutex.assert_called_once_with("InkFlowKernelBootstrap")


# ── kind 缺省解析 ──────────────────────────────────────────────────────────


async def test_instance_kind_defaults_to_resolved_value(tmp_path, mocks, monkeypatch):
    """instance_kind=None → resolve_instance_kind() 的结果（dev 环境 → dev）。"""
    monkeypatch.setenv("INKFLOW_INSTANCE_KIND", "dev")
    await ensure_kernel(state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD)
    mocks.lifetime.assert_not_called()  # dev 分支


async def test_resolved_rc_kind_triggers_lifetime_mutex(tmp_path, mocks, monkeypatch):
    """instance_kind=None 但 env 解析为 rc → 走存活期互斥分支。"""
    monkeypatch.setenv("INKFLOW_INSTANCE_KIND", "rc")
    await ensure_kernel(state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD)
    mocks.lifetime.assert_called_once_with("rc")


# ── 注册表联动 ─────────────────────────────────────────────────────────────


async def test_successful_launch_registers_instance(tmp_path, mocks):
    """拉起成功后写入实例注册表（托盘全量可见的数据源）。"""
    await ensure_kernel(
        state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
    )
    mocks.write_instance.assert_called_once()
    payload = mocks.write_instance.call_args.args[0]
    assert payload["kind"] == "dev"
    assert payload["port"] == 8123
    assert set(payload) == {
        "kind",
        "port",
        "token",
        "pid",
        "version",
        "started_at",
        "data_dir",
    }


async def test_reuse_does_not_register_duplicate(tmp_path, mocks):
    """复用既有内核 → 不重复注册（条目已由原拉起方写入）。"""
    mocks.read.return_value = _state()
    await ensure_kernel(
        state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
    )
    mocks.write_instance.assert_not_called()
