"""F12 跨纪元流速换算（0.17.0 W3c / #1411 / ADR-065 §2.1）.

纯领域模块：无 I/O、无框架依赖、确定性（同输入同输出）。

语义（spec §2.8 E11）:
- ``era_scale`` = 该纪元相对项目时基的**流速比**（``1.0`` = 同速；越大越快）；
- ``to_global(era, era_value, scale) = era_value / scale`` —— 把**轴内值**换算为
  **全局标量**（跨轴唯一可比口径，§5.3 跨桶比较用）；
- ``era`` 为空（默认轴）或 ``era_value`` 为 None → **None**（无全局标量）；
- ``scale <= 0`` → 按 ``1.0`` 处置（防御：流速比非正无意义；请求面另有校验）。

**唯一实现点**：service / 写入路径 / 视图不得各写一份（spec §2.8 E11）。换算只做
**判定层只读投影**，不回写 ``time_value``（spec §12「判定层归一 vs 数据层重锚分离」）。

依据: specs/f12-timeline/spec.md §2.8 E11 / §5.3 · adr/database/ADR-065.md §2.1。
"""

from __future__ import annotations

__all__ = ["to_global"]


def to_global(era: str, era_value: float | None, scale: float) -> float | None:
    """把纪元**轴内值**换算为**全局标量**（spec §2.8 E11，唯一实现点）.

    Args:
        era: 纪元轴名；``""`` = 默认轴（无纪元 → 无全局标量）.
        era_value: 轴内值；None = 轴内值未知 → 无全局标量.
        scale: 流速比（``1.0`` = 与项目时基同速；``<= 0`` 按 ``1.0`` 处置）.

    Returns:
        换算后的全局标量；``era`` 为空或 ``era_value`` 为 None → None.
    """
    if not era or era_value is None:
        return None
    effective_scale = scale if scale > 0 else 1.0
    return era_value / effective_scale
