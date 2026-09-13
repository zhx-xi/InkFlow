"""F30 1.2 实例注册表契约（#1153 / ADR-059 ③，spec §2.4.2）。

被测：``inkflow.infrastructure.kernel.registry``

- ``registry_dir(state_file) -> Path``：由 kernel.json 所在 data_dir 推出 ``running/``
- ``write_instance(entry, dir) -> Path``：原子写 ``<kind>-<pid>.json``（七字段）
- ``read_instances(dir) -> list[InstanceEntry]``：读全部条目 + 过滤 pid 死条目
- ``prune_dead(dir) -> int``：删除 pid 死条目，返回删除数（惰性 GC）
- ``remove_instance(dir, kind=, pid=)``：内核退出时删自己的文件（幂等）
- ``find_by_kind(dir, kind)``：按 kind 检索（rc/release 准入失败时提示既有实例）

设计约束（ADR-059 ③）：
- ``kernel.json`` 五字段契约不变——注册表是**增量**目录
- 僵尸清理走惰性 GC（读取时清理），**无守护进程**（ADR-029 daemon 已判定为伪需求）

⚠️ 存活样本必须用**真 pid**：read_instances/prune_dead 会做存活探测并 GC 死条目，
用字面量假 pid 会让「合法条目被解析」与「死条目被清理」两条断言互相矛盾
（Codex 实测指出，2026-09-14；此处用 os.getpid()）。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from inkflow.infrastructure.kernel import registry

STARTED = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)

# 存活样本：本进程 pid（is_process_alive 必真）
ALIVE_PID = os.getpid()
# 一个几乎不可能存在的 pid（Windows 未分配 → is_process_alive False）
DEAD_PID = 0x7FFFFFF0


@pytest.fixture(autouse=True)
def _liveness(monkeypatch):
    """默认存活判据：ALIVE_PID 及其合成邻域（+1000/+2000/+3000）视为存活。

    用「邻域」而非单值，是为了让 cross-kind 用例能用不同 pid 表达多实例，
    同时仍然让 DEAD_PID 被判定为死亡。
    个别用例（test_read_instances_filters_dead_pids / test_prune_dead_*）用自身
    patch 覆盖，测「同一目录内活/死混合」的精确行为。
    """
    alive_set = {ALIVE_PID, ALIVE_PID + 1000, ALIVE_PID + 2000, ALIVE_PID + 3000}
    monkeypatch.setattr(
        "inkflow.infrastructure.kernel.registry.state.is_process_alive",
        lambda pid: pid in alive_set,
    )


def _entry(
    pid: int | None = None,
    kind: str = "dev",
    port: int = 51234,
    data_dir: str = "C:/d",
    started_at: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "port": port,
        "token": "tok-x",
        "pid": ALIVE_PID if pid is None else pid,
        "version": "1.2.0",
        "started_at": STARTED.isoformat() if started_at is None else started_at,
        "data_dir": data_dir,
    }


# ── registry_dir ───────────────────────────────────────────────────────────


def test_registry_dir_is_running_subdir_of_state_file_parent(tmp_path):
    """注册表目录 = kernel.json 所在目录下的 running/（spec §2.4.2）。"""
    state_file = tmp_path / "kernel.json"
    assert registry.registry_dir(state_file) == tmp_path / "running"


# ── write_instance ─────────────────────────────────────────────────────────


def test_write_instance_creates_kind_pid_filename(tmp_path):
    """文件名为 <kind>-<pid>.json（pid 唯一 + kind 便于人眼排查）。"""
    target = registry.write_instance(_entry(pid=777, kind="rc"), tmp_path / "running")
    assert target.name == "rc-777.json"
    assert target.parent.name == "running"


def test_write_instance_creates_directory_when_absent(tmp_path):
    """目录不存在时自动创建（首次写入）。"""
    dir_ = tmp_path / "running"
    assert not dir_.exists()
    registry.write_instance(_entry(), dir_)
    assert dir_.is_dir()


def test_write_instance_payload_has_seven_fields(tmp_path):
    """写盘 payload 七字段齐全（spec §2.4.2 表）。"""
    target = registry.write_instance(_entry(pid=555), tmp_path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert set(payload) == {
        "kind",
        "port",
        "token",
        "pid",
        "version",
        "started_at",
        "data_dir",
    }
    assert payload["kind"] == "dev"
    assert payload["pid"] == 555
    assert payload["data_dir"] == "C:/d"


def test_write_instance_is_atomic_no_tmp_residue(tmp_path):
    """原子写：完成后目录内只有目标文件，无 .tmp 残留。"""
    registry.write_instance(_entry(pid=1), tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["dev-1.json"]


# ── read_instances ─────────────────────────────────────────────────────────


def test_read_instances_returns_empty_for_missing_dir(tmp_path):
    """目录不存在 → []（不抛错）。"""
    assert registry.read_instances(tmp_path / "nope") == []


def test_read_instances_parses_valid_entries(tmp_path):
    """合法条目被解析为 InstanceEntry，字段完整（started_at 保持 ISO 字符串）。"""
    registry.write_instance(_entry(kind="dev"), tmp_path)
    registry.write_instance(_entry(kind="rc", port=60001), tmp_path)

    got = registry.read_instances(tmp_path)
    assert len(got) == 2
    assert all(e.pid == ALIVE_PID for e in got)
    kinds = sorted(e.kind for e in got)
    assert kinds == ["dev", "rc"]
    ports = sorted(e.port for e in got)
    assert ports == [51234, 60001]
    assert got[0].started_at == STARTED.isoformat()


def test_read_instances_skips_malformed_json(tmp_path):
    """损坏 JSON 文件被跳过（不抛错）。"""
    (tmp_path / "dev-9.json").write_text("{ not json", encoding="utf-8")
    registry.write_instance(_entry(), tmp_path)
    assert [e.pid for e in registry.read_instances(tmp_path)] == [ALIVE_PID]


def test_read_instances_skips_missing_fields(tmp_path):
    """缺字段条目被跳过。"""
    (tmp_path / "dev-9.json").write_text(json.dumps({"kind": "dev"}), encoding="utf-8")
    registry.write_instance(_entry(), tmp_path)
    assert [e.pid for e in registry.read_instances(tmp_path)] == [ALIVE_PID]


def test_read_instances_skips_invalid_kind(tmp_path):
    """kind 不在三值集合内 → 跳过（防手工/旧版脏数据）。"""
    bad = _entry(pid=9)
    bad["kind"] = "prod"
    (tmp_path / "prod-9.json").write_text(json.dumps(bad), encoding="utf-8")
    registry.write_instance(_entry(), tmp_path)
    assert [e.pid for e in registry.read_instances(tmp_path)] == [ALIVE_PID]


def test_read_instances_filters_dead_pids(tmp_path):
    """pid 已死的条目不出现在结果中（存活过滤）。"""
    registry.write_instance(_entry(pid=ALIVE_PID), tmp_path)
    registry.write_instance(_entry(pid=DEAD_PID), tmp_path)

    got = registry.read_instances(tmp_path)
    assert [e.pid for e in got] == [ALIVE_PID]


def test_read_instances_does_not_expose_token(tmp_path):
    """InstanceEntry 不含 token（最小暴露面；spec §2.4 "token 不外传"）。"""
    registry.write_instance(_entry(), tmp_path)
    got = registry.read_instances(tmp_path)
    assert not hasattr(got[0], "token")


def test_read_instances_sorted_by_started_at_then_pid(tmp_path):
    """结果顺序稳定（started_at 升序）——托盘渲染确定性前提。"""
    older = _entry(started_at=(STARTED - timedelta(minutes=5)).isoformat())
    newer = _entry(started_at=STARTED.isoformat())
    (tmp_path / "dev-a.json").write_text(json.dumps(older), encoding="utf-8")
    (tmp_path / "dev-b.json").write_text(json.dumps(newer), encoding="utf-8")

    got = registry.read_instances(tmp_path)
    assert got[0].started_at == older["started_at"]
    assert got[1].started_at == newer["started_at"]


# ── prune_dead（惰性 GC）────────────────────────────────────────────────────


def test_prune_dead_removes_dead_and_keeps_alive(tmp_path):
    """删除 pid 死条目，保留存活条目；返回删除数。"""
    registry.write_instance(_entry(pid=ALIVE_PID), tmp_path)
    registry.write_instance(_entry(pid=DEAD_PID), tmp_path)

    removed = registry.prune_dead(tmp_path)

    assert removed == 1
    assert [p.name for p in tmp_path.iterdir()] == [f"dev-{ALIVE_PID}.json"]


def test_prune_dead_also_removes_malformed(tmp_path):
    """损坏文件同样清理（无法判定归属 = 垃圾）。"""
    (tmp_path / "dev-9.json").write_text("{ not json", encoding="utf-8")
    removed = registry.prune_dead(tmp_path)
    assert removed == 1
    assert list(tmp_path.iterdir()) == []


def test_prune_dead_missing_dir_returns_zero(tmp_path):
    """目录不存在 → 0（不抛错）。"""
    assert registry.prune_dead(tmp_path / "nope") == 0


# ── remove_instance ────────────────────────────────────────────────────────


def test_remove_instance_deletes_own_file(tmp_path):
    """内核退出时删除自己的注册文件；重复调用 no-op。"""
    target = registry.write_instance(_entry(), tmp_path)
    assert target.exists()

    registry.remove_instance(tmp_path, kind="dev", pid=ALIVE_PID)
    assert not target.exists()
    registry.remove_instance(tmp_path, kind="dev", pid=ALIVE_PID)  # 幂等


# ── 跨 kind 并存 ───────────────────────────────────────────────────────────


def test_cross_kind_entries_coexist(tmp_path):
    """不同 kind 条目并存互不干扰（rc 与 release 可各 1 个，dev 不限）。

    注：文件名含 pid，故同一 pid 的同 kind 条目会互相覆盖（生产语义正确——
    pid 唯一标识一个进程）。此处用不同 pid 表达「同一 kind 多实例」。
    """
    registry.write_instance(_entry(pid=ALIVE_PID, kind="dev"), tmp_path)
    registry.write_instance(_entry(pid=ALIVE_PID + 1000, kind="dev"), tmp_path)
    registry.write_instance(_entry(pid=ALIVE_PID + 2000, kind="rc"), tmp_path)
    registry.write_instance(_entry(pid=ALIVE_PID + 3000, kind="release"), tmp_path)

    got = registry.read_instances(tmp_path)
    assert len(got) == 4
    kinds = sorted(e.kind for e in got)
    assert kinds == ["dev", "dev", "rc", "release"]


def test_same_pid_same_kind_overwrites(tmp_path):
    """同一 (kind, pid) 重复注册 → 覆盖（文件名单键语义，不产生重复条目）。"""
    registry.write_instance(_entry(pid=ALIVE_PID, kind="dev", port=1111), tmp_path)
    registry.write_instance(_entry(pid=ALIVE_PID, kind="dev", port=2222), tmp_path)

    got = registry.read_instances(tmp_path)
    assert len(got) == 1
    assert got[0].port == 2222


def test_find_by_kind_returns_matching_entries(tmp_path):
    """按 kind 检索（rc/release 准入失败时用于提示既有实例）。"""
    registry.write_instance(_entry(kind="rc", port=60001), tmp_path)
    registry.write_instance(_entry(kind="dev"), tmp_path)

    found = registry.find_by_kind(tmp_path, "rc")
    assert [e.pid for e in found] == [ALIVE_PID]
    assert found[0].port == 60001
    assert registry.find_by_kind(tmp_path, "release") == []
