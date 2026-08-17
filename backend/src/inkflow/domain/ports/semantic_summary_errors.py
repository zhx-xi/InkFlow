"""F45 M2 语义总结领域异常.

依据: specs/f45-memory-evolution/spec.md §3.3 异常映射表——LLM 调用失败 /
LLM 输出不可解析（重试 2 次仍失败）→ API 502（上游 LLM 故障语义）。
镜像 F16 `domain/ports/style_errors.py` 的 StyleLLMAnalysisError 形态
（F16 500 语义变体为 M2 502，镜像时仅调整错误面语义）。
"""

from __future__ import annotations


class SemanticSummaryError(Exception):
    """LLM 语义总结失败（解析重试耗尽/LLM 输出不可解析）→ API 502.

    LLM 输出无法解析/校验为合法总结 JSON（spec §3.3/§5.3 步骤⑤）时抛出——
    同 F14 TimelineExtractionError / F16 StyleLLMAnalysisError 形态，由
    API/CLI 层透传映射为 502。
    """

    def __init__(self, message: str = "语义总结失败") -> None:
        super().__init__(message)
