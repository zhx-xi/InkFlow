"""全量实例注册表 — ``<data_dir>/running/<kind>-<pid>.json``（spec §2.4.2 / ADR-059 ③）。

kernel.json 五字段契约**不变**（仍是「默认实例」的发现锚点）；本模块是**增量**
可见性层：每个存活内核一个文件，pid 唯一 + kind 便于人眼排查。

僵尸清理走**惰性 GC**（读取时对条目做 pid 存活探测，死则删文件），**无守护进程**
（ADR-029 已判定 daemon 为伪需求）。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from inkflow.infrastructure.kernel import state
from inkflow.infrastructure.kernel.instance_kind import VALID_KINDS

REGISTRY_DIR_NAME = "running"
#: GUI 自登记文件名（#1537）：内核为「GUI 内置」形态时写下 GUI exe 绝对路径，供 CLI 探测
GUI_RECORD_NAME = "gui.json"


@dataclass(frozen=True)
class InstanceEntry:
    """注册表条目（spec §2.4.2 七字段去 token 后的只读视图）。

    刻意**不含 token**：注册表供人眼/托盘排查，最小暴露面（token 只经
    kernel.json / HTTP 头交付）。
    """

    kind: str
    port: int
    pid: int
    version: str
    started_at: str  # ISO8601 字符串（保持原样，不做 datetime 解析）
    data_dir: str


def registry_dir(state_file: Path) -> Path:
    """注册表目录 = kernel.json 所在 data_dir 下的 running/（spec §2.4.2 dev 分支）。"""
    return state_file.parent / REGISTRY_DIR_NAME


def machine_registry_dir() -> Path:
    """**机器级**注册表目录 = 标准数据目录下的 running/（spec §2.4.2 / ADR-066 ③）。

    不随 ``INKFLOW_DATA_DIR`` 变化——rc/prod 是**机器级单实例**，其可见性锚点必须
    机器级（否则跨 data_dir 的既有实例互相发现不了 = #1487 根因 ③）。
    锚点复用既有 ``core.config.get_instance_env_path().parent``
    （Windows = ``%APPDATA%\\InkFlow``，其他平台 = ``~/InkFlow``）。
    """
    from inkflow.core.config import get_instance_env_path

    return get_instance_env_path().parent / REGISTRY_DIR_NAME


def registry_dir_for(kind: str, state_file: Path) -> Path:
    """按 kind 分域解析注册表目录（ADR-066 ③；与 ``_lifetime_mutex_name`` 同构）。

    ``dev`` → 既有 ``<data_dir>/running/``（同 data_dir 单内核，worktree 互不干扰）；
    ``rc`` / ``prod`` → **机器级** ``machine_registry_dir()``。
    """
    if kind == "dev":
        return registry_dir(state_file)
    return machine_registry_dir()


def gui_record_path() -> Path:
    """GUI 自登记文件路径 = `<标准数据目录>/gui.json`（#1537；机器级，同 `running/`）。"""
    return machine_registry_dir().parent / GUI_RECORD_NAME


def detect_bundled_gui_exe(exe: Path | None = None) -> Path | None:
    """GUI **内置内核**形态 → 反推出 GUI exe；其它形态 → None（#1537）。

    GUI(Electron) spawn 内核用的就是 `<GUI>/resources/kernel/<kernel exe>`（spec §5.2）；
    CLI zip / venv / 手工 serve 的 exe 不在 `resources/kernel` 下 → None。
    **只做路径形态判定、不枚举进程**：内核自己的 exe 路径已编码 GUI 位置，
    便携版与安装版通吃。
    """
    resolved = (exe or Path(sys.executable)).resolve()
    shape = (resolved.parent.name.casefold(), resolved.parent.parent.name.casefold())
    if shape != ("kernel", "resources"):
        return None
    candidate = resolved.parent.parent.parent / "InkFlow.exe"
    return candidate if candidate.is_file() else None


def record_bundled_gui(exe: Path) -> Path:
    """原子写 `gui.json`（`{"exe": "<abs>"}`）；GUI 换安装路径时覆盖。返回目标路径。"""
    target = gui_record_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps({"exe": str(exe)}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def read_gui_exe() -> Path | None:
    """读 `gui.json` 记的 GUI exe；缺失 / 损坏 / 值非法 / 目标不存在 → None（不抛）。"""
    try:
        data = json.loads(gui_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("exe")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_file() else None


def write_instance(entry: dict, dir_path: Path) -> Path:
    """原子写 ``<kind>-<pid>.json``（先写 .tmp 再 os.replace），返回目标路径。

    目录不存在时按需创建（首次写入）；entry 为七字段 dict（含 token）。
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    target = dir_path / f"{entry['kind']}-{entry['pid']}.json"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def read_instances(dir_path: Path) -> list[InstanceEntry]:
    """读全部存活条目：损坏/字段不符/非法 kind 跳过，pid 已死者**顺带删文件**。

    目录缺失 → []（不抛错）；结果按 (started_at, pid) 升序（托盘渲染确定性前提）。
    """
    if not dir_path.is_dir():
        return []
    entries: list[InstanceEntry] = []
    for path in dir_path.glob("*.json"):
        entry = _parse_entry(path)
        if entry is None:
            continue
        if not state.is_process_alive(entry.pid):
            _unlink_quietly(path)
            continue
        entries.append(entry)
    entries.sort(key=lambda e: (e.started_at, e.pid))
    return entries


def prune_dead(dir_path: Path) -> int:
    """删除 pid 已死与损坏的注册文件，返回删除数（目录缺失 → 0）。"""
    if not dir_path.is_dir():
        return 0
    removed = 0
    for path in dir_path.glob("*.json"):
        entry = _parse_entry(path)
        if entry is None or not state.is_process_alive(entry.pid):
            _unlink_quietly(path)
            removed += 1
    return removed


def remove_instance(dir_path: Path, *, kind: str, pid: int) -> None:
    """删除 ``<kind>-<pid>.json``（内核退出时自删）；不存在 → no-op（幂等）。"""
    _unlink_quietly(dir_path / f"{kind}-{pid}.json")


def find_by_kind(dir_path: Path, kind: str) -> list[InstanceEntry]:
    """按 kind 检索存活条目（准入失败时用于提示既有实例）。"""
    return [entry for entry in read_instances(dir_path) if entry.kind == kind]


def _parse_entry(path: Path) -> InstanceEntry | None:
    """解析单个注册文件；不可解析 / 字段缺失或类型不符 / 非法 kind → None。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        kind = data["kind"]
        port = data["port"]
        pid = data["pid"]
        version = data["version"]
        started_at = data["started_at"]
        data_dir = data["data_dir"]
    except (KeyError, TypeError):
        return None
    if not isinstance(kind, str) or kind not in VALID_KINDS:
        return None
    if not isinstance(port, int) or isinstance(port, bool):
        return None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(version, str):
        return None
    if not isinstance(started_at, str):
        return None
    if not isinstance(data_dir, str):
        return None
    return InstanceEntry(
        kind=kind,
        port=port,
        pid=pid,
        version=version,
        started_at=started_at,
        data_dir=data_dir,
    )


def _unlink_quietly(path: Path) -> None:
    """best-effort 删除（并发下他人已删 / 权限不足均不抛错）。"""
    with contextlib.suppress(OSError):
        path.unlink()
