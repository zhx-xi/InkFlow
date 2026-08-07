"""F30 内核冷启动基建 — kernel.json 状态文件读写测试契约（RED 阶段）。

本文件只为 ``inkflow.infrastructure.kernel.state`` 模块定义测试契约
（spec §2.1 kernel.json 契约 / §9 测试策略 M1）。测试一律使用 pytest
内置 ``tmp_path`` fixture 做文件操作，绝不触碰真实 ``%APPDATA%``。

GREEN 实现契约
--------------
公开名（均位于 ``backend/src/inkflow/infrastructure/kernel/state.py``）：

- ``KernelState``：``@dataclass(frozen=True)``，字段 ``port: int`` /
  ``token: str`` / ``pid: int`` / ``version: str`` / ``started_at:
  datetime``——``started_at`` 由 ISO8601 UTC 字符串经
  ``datetime.fromisoformat`` 解析而来。
- ``read_kernel_state(path: Path) -> KernelState | None``：文件不存在 /
  JSON 解析失败 / 字段缺失 / 字段类型不符 / ``started_at`` 无法解析 →
  一律返回 ``None``（客户端视角「无内核」，spec §2.1 读取规则）；
  正常 → ``KernelState``（五字段逐项还原）。
- ``write_kernel_state(path: Path, payload: dict) -> None``：原子写——
  先写 ``path.with_suffix(path.suffix + ".tmp")``（即 ``kernel.json.tmp``）
  再 ``os.replace`` 到目标路径（复用 serve.py ``_write_port_file`` 模式，
  spec §2.1 写入规则）；JSON 序列化 ``ensure_ascii=False`` +
  ``encoding="utf-8"``；payload 键 = port / token / pid / version /
  started_at（ISO8601 字符串）。
- ``mark_stale(path: Path) -> Path``：把 kernel.json 重命名为同目录下
  ``kernel.json.stale-<ts>``（ts = 毫秒级时间戳
  ``int(time.time() * 1000)``），返回新路径；文件不存在 → 不抛错，
  no-op 直接返回原 ``path``。
- ``is_process_alive(pid: int) -> bool``：``pid <= 0`` → False（不探测）；
  否则 ``os.kill(pid, 0)`` 成功 → True，抛 ``OSError``（含子类）→ False。

RED 状态说明
------------
``inkflow.infrastructure.kernel.state`` 模块尚未实现，模块级 from-import
在收集期抛 ModuleNotFoundError，属预期 RED 信号；GREEN 实现后本文件即全绿。
"""

import dataclasses
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from inkflow.infrastructure.kernel.state import (
    KernelState,
    is_process_alive,
    mark_stale,
    read_kernel_state,
    write_kernel_state,
)


def _valid_payload() -> dict:
    """合法 kernel.json payload（spec §2.1 五字段全齐，started_at 为 UTC ISO8601）。"""
    return {
        "port": 8765,
        "token": "test-token-abc123",
        "pid": 12345,
        "version": "0.1.0",
        "started_at": "2026-08-07T10:00:00+00:00",
    }


def _write_fixture(path: Path, payload: dict) -> None:
    """把 payload 以 UTF-8 JSON 写入 path（模拟内核进程写好的状态文件）。"""
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_read_kernel_state_missing_file_returns_none(tmp_path):
    """① 无状态文件 → None（视为「无内核」，spec §2.1 / §7 场景 1）。"""
    assert read_kernel_state(tmp_path / "kernel.json") is None


def test_read_kernel_state_valid_file_returns_all_fields(tmp_path):
    """② 合法文件 → KernelState 五字段逐项正确（started_at 解析为 UTC datetime）。"""
    path = tmp_path / "kernel.json"
    _write_fixture(path, _valid_payload())

    state = read_kernel_state(path)

    assert isinstance(state, KernelState)
    assert state.port == 8765
    assert state.token == "test-token-abc123"
    assert state.pid == 12345
    assert state.version == "0.1.0"
    assert state.started_at == datetime(2026, 8, 7, 10, 0, 0, tzinfo=UTC)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.port = 9999  # frozen=True：字段不可变


def test_read_kernel_state_corrupt_json_returns_none(tmp_path):
    """③ 损坏 JSON → None（spec §2.1：JSON 解析失败视为无内核）。"""
    path = tmp_path / "kernel.json"
    path.write_text("{ not valid json", encoding="utf-8")
    assert read_kernel_state(path) is None


def test_read_kernel_state_missing_field_returns_none(tmp_path):
    """④ 字段缺失（pid 缺失）→ None（必填五字段缺一即损坏）。"""
    path = tmp_path / "kernel.json"
    payload = _valid_payload()
    payload.pop("pid")
    _write_fixture(path, payload)
    assert read_kernel_state(path) is None


def test_read_kernel_state_invalid_started_at_returns_none(tmp_path):
    """⑤ started_at 非 ISO8601 → None（fromisoformat 解析失败即损坏）。"""
    path = tmp_path / "kernel.json"
    payload = _valid_payload()
    payload["started_at"] = "not-a-timestamp"
    _write_fixture(path, payload)
    assert read_kernel_state(path) is None


def test_read_kernel_state_type_mismatch_returns_none(tmp_path):
    """类型不符（port 为字符串）→ None（字段类型不符视为损坏）。"""
    path = tmp_path / "kernel.json"
    payload = _valid_payload()
    payload["port"] = "8765"
    _write_fixture(path, payload)
    assert read_kernel_state(path) is None


def test_write_kernel_state_atomic_writes_valid_json_without_tmp_residue(tmp_path):
    """⑥ 原子写：目标文件 JSON 可解析且字段正确、无残留 .tmp 文件。"""
    path = tmp_path / "kernel.json"

    assert write_kernel_state(path, _valid_payload()) is None

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == _valid_payload()  # 字段值与类型逐项一致（ensure_ascii=False + utf-8）
    assert list(tmp_path.glob("*.tmp")) == []  # 无残留临时文件（原子写成立）
    state = read_kernel_state(path)  # 写读闭环：写出的文件可被正常读回
    assert state is not None
    assert state.port == 8765 and state.pid == 12345


def test_mark_stale_renames_file_with_timestamp_suffix(tmp_path):
    """⑦ stale 清理：重命名为 kernel.json.stale-<毫秒ts>，原文件不存在。"""
    path = tmp_path / "kernel.json"
    path.write_text("{}", encoding="utf-8")

    new_path = mark_stale(path)

    assert new_path != path
    assert new_path.parent == path.parent
    assert new_path.name.startswith("kernel.json.stale-")
    ts_part = new_path.name.split(".stale-", 1)[1]
    assert ts_part.isdigit()  # 时间戳为纯数字（毫秒级），不精确断言其值
    assert new_path.exists()
    assert not path.exists()


def test_mark_stale_missing_file_is_noop_returns_original_path(tmp_path):
    """mark_stale 对不存在的文件不抛错，no-op 返回原 path（幂等语义钉死）。"""
    path = tmp_path / "kernel.json"
    assert mark_stale(path) == path
    assert not path.exists()


def test_is_process_alive_current_true_nonexistent_and_nonpositive_false():
    """⑧ 存活判定：当前进程 True；不存在 pid / pid<=0 均 False。"""
    assert is_process_alive(os.getpid()) is True
    assert is_process_alive(2147483647) is False  # 2**31-1：Windows 上不存在的 pid
    assert is_process_alive(0) is False
    assert is_process_alive(-1) is False
