"""repo 层主键入参归一 + int64 范围守卫（#1134 批 4 收窄终态）。

调用方传 ``uuid.UUID``（domain 层天然形态）——**唯一**合法入参形态。
裸 int 兼容面（#1230 ⑤）已随 #1291 退役。

比较型守卫对 UUID 会抛 TypeError（UUID < int），故必须先归一为 int 再比较。
"""

from __future__ import annotations

import uuid

INT64_MIN = -(2**63)
INT64_MAX = 2**63


def require_uuid_pk(value: uuid.UUID | str | None) -> int | None:
    """#1134/ADR-060 D9：**收窄契约**入口 —— 只接受 UUID 形态。

    调用方（domain/API）应传 ``uuid.UUID`` 或合法 uuid 字符串，**不应自行
    ``.int``**——转换由本函数负责，避免调用点各自持有 int 语义
    （ADR-060 D2 描述的「每个写入点都持有过一个溢出值」同族）。

    Args:
        value: ``uuid.UUID`` / 36 字符 uuid 字符串 / None。

    Returns:
        归一后的 int PK；越界（真 uuid）或 None → None（调用方返 404/不存在）。

    Raises:
        TypeError: 入参不是 UUID/合法 uuid 字符串（含裸 int）——契约违规。
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise TypeError(f"require_uuid_pk: 非法 uuid 字符串 {value!r}") from exc
    else:
        raise TypeError(
            f"require_uuid_pk: 入参必须是 uuid.UUID 或 uuid 字符串，"
            f"得到 {type(value).__name__}（调用方不应自行 .int，见 ADR-060 D9）"
        )
    return None if _out_of_int64(parsed.int) else parsed.int


def _out_of_int64(value: int) -> bool:
    """是否超出 SQLite 64 位 INTEGER 范围（随机 uuid4 的 .int 必然超出）。

    内部实现细节 —— 原 ``out_of_int64`` 公开符号已随 #1291 退役（零消费者）。
    """
    return value < INT64_MIN or value >= INT64_MAX
