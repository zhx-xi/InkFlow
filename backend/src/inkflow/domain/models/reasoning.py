"""F59 思考档位领域枚举（spec §2.1）—— 与上游 LLM 网关官方七档签名对齐。

语义表（GUI 文案由 i18n 映射，领域层不感知语言）：
- none:    显式关闭思考。
- minimal: 最低档。
- low / medium / high: 低 / 中 / 高。
- xhigh:   极高。
- default: 不发送任何思考参数，跟随模型/供应商默认行为。

依赖方向约束（spec §5.6）：本模块为纯 Literal 枚举，domain 层零第三方
LLM 网关 import——调用链上的能力探测全部收敛在 infrastructure 层。
"""

from __future__ import annotations

from typing import Literal

#: 七档思考强度（对齐上游 LLM 网关官方签名，英文枚举不进 i18n 值域）。
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "default"]

#: 常量元组形式（校验/遍历复用，顺序即枚举声明顺序）。
REASONING_EFFORTS: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "default",
)
