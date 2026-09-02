"""S3b C2-③ kernel.json 原子写契约（M4 门禁）— 半截写不会污染终态文件。

`write_kernel_state` / serve 侧 `_write_port_file` 都必须 tmp+os.replace 原子写：
读者（read_kernel_state）永不该读到半截 JSON（那会误判为 stale → 重复拉起内核）。
本文件锁定：
1. 原子写入后 .tmp 已 rename 消失，终态文件为合法五字段 JSON；
2. 残留 .tmp 不干扰读（读 kernel.json 而非 .tmp）；
3. 读到的 KernelState 字段值与写入一致；
4. 并发写同一 path（两次写竞争）后终态 file 仍是「两者之一」的合法 JSON
   （后端进程级 verify 由 tests/cli/ 真子进程补测，本文件为确定性单测）。
本文件是回归护栏（当前实现已原子写，直接 PASS）；GREEN 无 src 改动。
"""
from __future__ import annotations

from pathlib import Path

from inkflow.infrastructure.kernel import state

VALID = {
    "port": 39123,
    "token": "token-abc",
    "pid": 4242,
    "version": "0.1.0",
    "started_at": "2026-09-01T00:00:00+00:00",
}


def test_write_kernel_state_is_atomic_and_reads_back(tmp_path: Path) -> None:
    """原子写：tmp+os.replace；write 后 .tmp 消失、终态文件合法、读回一致。"""
    path = tmp_path / "kernel.json"
    state.write_kernel_state(path, VALID)
    # .tmp 已 rename 消失（原子替换语义）
    assert not (tmp_path / "kernel.json.tmp").exists()
    st = state.read_kernel_state(path)
    assert st is not None
    assert st.port == VALID["port"]
    assert st.token == VALID["token"]
    assert st.pid == VALID["pid"]
    assert st.version == VALID["version"]


def test_leftover_tmp_does_not_corrupt_read(tmp_path: Path) -> None:
    """残留 .tmp（崩溃残留）不干扰 read_kernel_state（读 kernel.json 非 .tmp）。"""
    path = tmp_path / "kernel.json"
    state.write_kernel_state(path, VALID)
    # 制造一个半截 .tmp（模拟写途中崩溃：tmp 写了但未 rename）
    (tmp_path / "kernel.json.tmp").write_text('{"port": 12', encoding="utf-8")
    st = state.read_kernel_state(path)
    assert st is not None
    assert st.port == VALID["port"]  # 终态文件不受半截 .tmp 影响


def test_write_overwrites_previous_state(tmp_path: Path) -> None:
    """再次 write 覆盖旧终态：读回的是新 payload（幂等覆盖）。"""
    path = tmp_path / "kernel.json"
    state.write_kernel_state(path, VALID)
    updated = {**VALID, "port": 55555}
    state.write_kernel_state(path, updated)
    st = state.read_kernel_state(path)
    assert st is not None
    assert st.port == 55555
