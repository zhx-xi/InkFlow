"""F30 按实例类型的并发准入契约（ADR-059 ② → **ADR-066 ① 修订**，#1487）。

🔴 **本文件随 ADR-066 改写**：ADR-059 ② 的「存活期互斥由**客户端进程**持有」被
ADR-066 ① 推翻——持有者改为**内核进程自持**（`serve` 启动即取、持锁至自身退出）。
故原「客户端取互斥并持锁」「183 分支」类断言不再成立（它们是**被推翻的契约**，
不是实现缺陷），改为断言新语义：

| 断言 | 语义 |
|------|------|
| 客户端**不**取存活期互斥 | `bootstrap._acquire_lifetime_mutex` 恒不被 `ensure_kernel` 调用 |
| 互斥名不变 | rc/prod 机器级；dev 含 data_dir 摘要（不同 data_dir 互不阻塞） |
| 内核拒绝准入 | 子进程退出码 3 → `KernelStartupError`（含既有实例 kind/port/pid/data_dir） |
| 秒退仍重试 | 非 3 的秒退维持「重试 ≤2 次」（既有语义不回归） |

新语义的**真实双进程**证据见 `test_kernel_self_mutex_1487.py::test_real_second_kernel...`。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import inkflow
from inkflow.infrastructure.kernel.bootstrap import (
    _lifetime_mutex_name,
    ensure_kernel,
)
from inkflow.infrastructure.kernel.kernel_errors import KernelStartupError
from inkflow.infrastructure.kernel.state import KernelState

SPAWN_CMD = ["inkflow-dev.exe", "serve", "--port", "0"]


def _state() -> KernelState:
    return KernelState(
        port=8123,
        token="tok-test-123",
        pid=os.getpid(),
        version=inkflow.__version__,
        started_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    )


def _popen(returncode: int | None) -> MagicMock:
    popen = MagicMock()
    popen.poll.return_value = returncode
    popen.returncode = returncode
    return popen


@pytest.fixture
def mocks():
    """bootstrap/state 装配缝 mock（默认：秒退 0 = 正常拉起 + 状态文件就绪）。"""
    handle = object()
    with (
        patch("inkflow.infrastructure.kernel.state.read_kernel_state", return_value=None),
        patch("inkflow.infrastructure.kernel.state.is_process_alive", return_value=True),
        patch("inkflow.infrastructure.kernel.state.mark_stale"),
        patch("inkflow.infrastructure.kernel.state.write_kernel_state"),
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_mutex", return_value=handle),
        patch("inkflow.infrastructure.kernel.bootstrap._release_mutex"),
        patch("inkflow.infrastructure.kernel.bootstrap._spawn_kernel", return_value=_popen(0)),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=_state()),
        patch("inkflow.infrastructure.kernel.bootstrap._probe_health", return_value=True),
        patch("inkflow.infrastructure.kernel.bootstrap._log_kernel_event"),
        patch("inkflow.infrastructure.kernel.registry.write_instance") as write_instance,
        patch("inkflow.infrastructure.kernel.bootstrap._acquire_lifetime_mutex") as lifetime,
        patch("inkflow.infrastructure.kernel.registry.find_by_kind", return_value=[]) as find_kind,
    ):
        yield SimpleNamespace(
            handle=handle,
            lifetime=lifetime,
            write_instance=write_instance,
            find_kind=find_kind,
        )


# ── 互斥名：rc/prod 机器级；dev 按 data_dir（**名字一字不变**，ADR-066 ① 明确）──


def test_lifetime_mutex_name_unchanged_by_kind(tmp_path):
    """互斥名契约不变（ADR-066 只改持有者，不改名）——rc/prod 机器级、dev 带 data_dir。"""
    a = tmp_path / "a" / "kernel.json"
    b = tmp_path / "b" / "kernel.json"
    assert _lifetime_mutex_name("rc", a) == "InkFlowKernelRc"
    assert _lifetime_mutex_name("prod", a) == "InkFlowKernelProd"
    assert _lifetime_mutex_name("rc", b) == "InkFlowKernelRc"  # 机器级：data_dir 不参与
    assert _lifetime_mutex_name("prod", b) == "InkFlowKernelProd"
    dev_a, dev_b = _lifetime_mutex_name("dev", a), _lifetime_mutex_name("dev", b)
    assert dev_a.startswith("InkFlowKernelDev-")
    assert dev_a != dev_b  # 不同 data_dir 互不阻塞（worktree 并行）
    assert _lifetime_mutex_name("dev", a) == dev_a  # 稳定（同目录同名）


# ── 客户端不再持有存活期互斥（ADR-066 ① 核心断言）──────────────────────────


@pytest.mark.parametrize("kind", ["dev", "rc", "prod"])
async def test_client_never_acquires_lifetime_mutex(kind, tmp_path, mocks):
    """🔴 三 kind 一致：`ensure_kernel` **不**获取存活期互斥（持有者 = 内核进程）。

    可证伪性：恢复客户端 `_acquire_lifetime_mutex(kind, state_file)` → 本用例 FAIL。
    """
    handle = await ensure_kernel(
        state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind=kind
    )
    assert handle.reused is False
    mocks.lifetime.assert_not_called()


async def test_two_dev_instances_different_data_dir_both_spawn(tmp_path, mocks):
    """不同 data_dir 的两个 dev 实例均成功拉起（worktree 并行不受阻）——互斥名分域。"""
    h1 = await ensure_kernel(
        state_file=tmp_path / "a" / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
    )
    h2 = await ensure_kernel(
        state_file=tmp_path / "b" / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
    )
    assert h1.reused is False
    assert h2.reused is False


async def test_rc_and_prod_do_not_block_each_other(tmp_path, mocks):
    """跨 kind 互不阻塞（互斥名按 kind 区分）——两 kind 各自成功拉起。"""
    h1 = await ensure_kernel(
        state_file=tmp_path / "r.json", spawn_cmd=SPAWN_CMD, instance_kind="rc"
    )
    h2 = await ensure_kernel(
        state_file=tmp_path / "v.json", spawn_cmd=SPAWN_CMD, instance_kind="prod"
    )
    assert (h1.reused, h2.reused) == (False, False)


# ── 内核拒绝准入（退出码 3）→ 明确报错（含既有实例明细）──────────────────


@pytest.mark.parametrize("kind", ["dev", "rc", "prod"])
async def test_conflict_exit_code_rejected_for_every_kind(kind, tmp_path, mocks):
    """🔴 任一 kind：内核退出码 3 → `KernelStartupError`，消息含既有实例明细。"""
    mocks.find_kind.return_value = [
        SimpleNamespace(pid=4242, port=60001, data_dir="C:/existing", kind=kind)
    ]
    with (
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel",
            return_value=_popen(3),
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=None),
        pytest.raises(KernelStartupError) as exc,
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind=kind
        )

    msg = str(exc.value)
    assert "60001" in msg and "4242" in msg and "C:/existing" in msg


async def test_conflict_error_looks_up_kind_scoped_registry(tmp_path, mocks):
    """注册表查询走**按 kind 分域**的目录（ADR-066 ③：rc/prod 机器级 / dev 按 data_dir）。"""
    mocks.find_kind.return_value = []
    with (
        patch(
            "inkflow.infrastructure.kernel.bootstrap._spawn_kernel",
            return_value=_popen(3),
        ),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=None),
        patch("inkflow.infrastructure.kernel.registry.registry_dir_for") as dir_for,
        pytest.raises(KernelStartupError),
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="prod"
        )
    dir_for.assert_called_once_with("prod", tmp_path / "kernel.json")


# ── 秒退（非冲突）仍重试 ≤2 次（既有语义不回归）──────────────────────────


async def test_generic_crash_still_retries_then_raises(tmp_path, mocks):
    """非冲突秒退（退出码 1）→ 重试至 3 次后抛错（既有语义保留）。"""
    spawn = MagicMock(return_value=_popen(1))
    with (
        patch("inkflow.infrastructure.kernel.bootstrap._spawn_kernel", spawn),
        patch("inkflow.infrastructure.kernel.bootstrap._poll_state_file", return_value=None),
        pytest.raises(KernelStartupError) as exc,
    ):
        await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
        )
    assert spawn.call_count == 3
    assert "立即退出" in str(exc.value)


# ── 复用优先（任何 kind 都不 spawn）───────────────────────────────────────


async def test_reuse_does_not_spawn_or_touch_mutex(tmp_path, mocks):
    """复用既有内核 → 不 spawn、不取任何互斥、不写注册表。"""
    with (
        patch(
            "inkflow.infrastructure.kernel.state.read_kernel_state", return_value=_state()
        ) as _read,
        patch("inkflow.infrastructure.kernel.bootstrap._spawn_kernel") as spawn,
    ):
        handle = await ensure_kernel(
            state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="prod"
        )
    assert handle.reused is True
    spawn.assert_not_called()
    mocks.lifetime.assert_not_called()
    mocks.write_instance.assert_not_called()


# ── kind 缺省解析 ──────────────────────────────────────────────────────────


async def test_instance_kind_defaults_to_resolved_value(tmp_path, mocks, monkeypatch):
    """instance_kind=None → resolve_instance_kind()（env dev → dev）；仍不取互斥。"""
    monkeypatch.setenv("INKFLOW_INSTANCE_KIND", "dev")
    await ensure_kernel(state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD)
    mocks.lifetime.assert_not_called()


async def test_invalid_explicit_kind_falls_back(tmp_path, mocks):
    """非法显式 kind → 回落自判（宽松语义），仍不取互斥。"""
    await ensure_kernel(
        state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="bogus"
    )
    mocks.lifetime.assert_not_called()


# ── 注册表：客户端不写（内核自写，ADR-066 ③）─────────────────────────────


async def test_successful_launch_does_not_write_registry(tmp_path, mocks):
    """拉起成功也**不**由客户端写注册表（改由内核自身在 `serve` 就绪后写）。"""
    await ensure_kernel(
        state_file=tmp_path / "kernel.json", spawn_cmd=SPAWN_CMD, instance_kind="dev"
    )
    mocks.write_instance.assert_not_called()
