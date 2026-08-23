"""F49 ② (#618) 偏好取代判定领域异常.

依据: .hermes/plans/task-618-contract.md §2（LLM 冲突判定管线）——LLM 输出
无法解析/校验为合法 supersede JSON（修复式重试 ≤2 仍失败）→ 判定失败，由
MemoryService 捕获降级审计（不 502，该候选不创建，宁少勿误）。镜像 F45
`semantic_summary_errors.py` 的 SemanticSummaryError 形态。
"""

from __future__ import annotations


class SupersedeDeterminationError(Exception):
    """LLM 偏好取代判定失败（解析重试耗尽/LLM 输出不可解析）.

    LLM 输出无法解析/校验为合法 supersede JSON（contract §2，修复式重试 ≤2
    后仍失败）时抛出——由 MemoryService 捕获降级审计（degraded=True,
    actor="memory", note="LLM 判定失败"），该候选不创建（不 502）。
    """

    def __init__(self, message: str = "仍无法解析为合法 supersede JSON") -> None:
        super().__init__(message)
