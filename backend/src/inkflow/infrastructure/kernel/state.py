"""内核状态文件读写 — kernel.json 契约（spec §2.1）。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from packaging.version import InvalidVersion, Version


@dataclass(frozen=True)
class KernelState:
    """kernel.json 解析结果（spec §2.1 五字段）。"""

    port: int
    token: str
    pid: int
    version: str
    started_at: datetime  # aware datetime（ISO8601 UTC 解析）


def read_kernel_state(path: Path) -> KernelState | None:
    """读状态文件。

    文件不存在 / JSON 解析失败 / 五字段缺失或类型不符 / started_at 无法解析
    → 一律返回 None（客户端视角「无内核」）；正常 → KernelState。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        port = data["port"]
        token = data["token"]
        pid = data["pid"]
        version = data["version"]
        started_at_str = data["started_at"]
    except (KeyError, TypeError):
        return None
    if not isinstance(port, int) or isinstance(port, bool):
        return None
    if not isinstance(token, str):
        return None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(version, str):
        return None
    if not isinstance(started_at_str, str):
        return None
    try:
        started_at = datetime.fromisoformat(started_at_str)
    except ValueError:
        return None
    return KernelState(
        port=port,
        token=token,
        pid=pid,
        version=version,
        started_at=started_at,
    )


def write_kernel_state(path: Path, payload: dict) -> None:
    """原子写状态文件（spec §2.1 写入规则）。

    先写 path.with_suffix(path.suffix + ".tmp")（即 kernel.json.tmp）再 os.replace；
    JSON 序列化 ensure_ascii=False + encoding="utf-8"；payload 键 =
    port/token/pid/version/started_at（started_at 为 ISO8601 字符串）。
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def mark_stale(path: Path) -> Path:
    """把 kernel.json 重命名为同目录 kernel.json.stale-<ts>（ts = 毫秒时间戳）。

    文件不存在 → 不抛错，no-op 返回原 path；存在 → os.rename 并返回新路径。
    """
    if not path.exists():
        return path
    ts = int(time.time() * 1000)
    new_path = path.with_name(f"{path.name}.stale-{ts}")
    os.rename(path, new_path)
    return new_path


def is_process_alive(pid: int) -> bool:
    """进程存活判定：pid <= 0 → False；os.kill(pid, 0) 成功 → True；OSError → False。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_version_compatible(kernel_version: str, client_version: str) -> bool:
    """版本兼容校验（spec §5.4 / Q2 拍板：major 相同即复用）。

    两端均经 packaging.version.Version 解析；major 相同 → True；major 不同 → False；
    任一解析失败（InvalidVersion，含空串）→ False。方向无关（纯函数，无副作用）。
    """
    try:
        kernel = Version(kernel_version)
        client = Version(client_version)
    except InvalidVersion:
        return False
    return kernel.major == client.major
