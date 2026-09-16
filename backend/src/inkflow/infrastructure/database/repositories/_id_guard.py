"""repo 层主键入参归一 + int64 范围守卫（#1230 全同族统一入口）。

调用方传 UUID（domain 层天然形态）或 int（内部/迁移路径）均需正确归一；
比较型守卫对 UUID 会抛 TypeError（UUID < int），故必须先归一类型再比较。
"""

from __future__ import annotations

import uuid

INT64_MIN = -(2**63)
INT64_MAX = 2**63


def normalize_pk(value: int | uuid.UUID) -> int:
    """UUID → .int；int 原样透传。"""
    return value.int if isinstance(value, uuid.UUID) else int(value)


def out_of_int64(value: int) -> bool:
    """是否超出 SQLite 64 位 INTEGER 范围（随机 uuid4 的 .int 必然超出）。"""
    return value < INT64_MIN or value >= INT64_MAX


def uuid_to_pk_or_none(value: int | uuid.UUID | None) -> int | None:
    """归一 + 越界检查；None 透传。越界 → None（调用方返「不存在」语义）。"""
    if value is None:
        return None
    pk = normalize_pk(value)
    return None if out_of_int64(pk) else pk
