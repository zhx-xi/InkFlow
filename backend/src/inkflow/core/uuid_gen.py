"""统一 UUID 身份键生成（#1134 / ADR-060）。

单一实体身份入口 ``new_uuid()``：RFC 9562 UUIDv7（时间有序）+ 机器标识，
确保跨实例/跨进程不重复。取代散落的 ``uuid.uuid4()`` 实体构造。

⚠️ 非实体用途（``thread_id`` / ``correlation_id`` / ``task_id``）继续用
``uuid.uuid4()``——那是进程内/trace 标识，不是身份键（ADR-060 D6）。
"""

from __future__ import annotations

import hashlib
import socket
import uuid
from pathlib import Path

import uuid_utils

MACHINE_ID_FILENAME = ".instance_id"
_INT64_MAX = 2**63 - 1


def load_or_create_machine_id(data_dir: Path | None = None) -> str:
    """读取或创建本实例机器标识（32 hex）。

    优先 ``<data_dir>/.instance_id``（持久化 → 换路径/拷贝数据目录时 id 跟随）；
    目录不可写时回退 ``sha256(hostname)`` 前 32 hex（同机稳定，不抛异常）。

    Args:
        data_dir: 数据目录；None 时用全局配置的 data_dir。

    Returns:
        32 位十六进制标识串。
    """
    if data_dir is None:
        # 延迟导入：config 顶层引 pydantic-settings，避免 core 包内循环
        from inkflow.core.config import InkFlowConfig

        data_dir = InkFlowConfig().data_dir
    path = data_dir / MACHINE_ID_FILENAME
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        data_dir.mkdir(parents=True, exist_ok=True)
        generated = uuid.uuid4().hex
        path.write_text(generated, encoding="utf-8")
    except OSError:
        return hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()[:32]
    else:
        return generated


def new_uuid(machine_id: str | None = None) -> uuid.UUID:
    """生成全局唯一实体身份键（UUIDv7，时间有序）。

    时间戳（48b 毫秒）保证时间有序；随机段掺入机器标识保证跨实例不重复。

    Args:
        machine_id: 显式机器标识（测试用）；None 时用本实例持久化标识。

    Returns:
        标准 ``uuid.UUID``（version 7）。
    """
    raw = uuid_utils.uuid7()
    if machine_id is None:
        return uuid.UUID(bytes=raw.bytes)
    # 机器标识掺入随机段最后 4 字节（保持 v7 时间前缀不受影响）
    digest = hashlib.blake2b(machine_id.encode("utf-8"), digest_size=4).digest()
    mixed = bytearray(raw.bytes)
    mixed[12:16] = bytes(a ^ b for a, b in zip(mixed[12:16], digest, strict=True))
    return uuid.UUID(bytes=bytes(mixed))


def uuid_from_local_id(local_id: int) -> uuid.UUID:
    """旧 int 主键 → 可逆 UUID（``.int`` 即原值）。

    仅供批 3 改造前的过渡期使用；新代码应直接用 ``new_uuid()``。
    越界/负数 → ValueError（根除 #1106 类溢出）。
    """
    if local_id < 0 or local_id > _INT64_MAX:
        raise ValueError(f"local_id {local_id} outside int64 range")
    return uuid.UUID(int=local_id)
