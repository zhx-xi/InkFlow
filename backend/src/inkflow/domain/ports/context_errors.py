"""上下文管理领域异常.

F6 专属异常类型，继承自 Exception.
依据: specs/f6-context-service/spec.md §8.
"""

from __future__ import annotations


class ContextBudgetExceededError(Exception):
    """上下文预算超限 — Protected 层内容超出预算上限.

    不应被静默捕获，由 F3 捕获后提示用户精简写作要求或换用更大窗口模型.

    Attributes:
        budget: 预算 Token 数.
        required: 需要的 Token 数.
        suggestion: 用户引导建议.
    """

    def __init__(self, budget: int, required: int, suggestion: str = "") -> None:
        self.budget = budget
        self.required = required
        self.suggestion = suggestion
        msg = f"上下文预算超限: protected 层需要 {required} tokens, " f"预算 {budget} tokens"
        if suggestion:
            msg += f"\n建议: {suggestion}"
        super().__init__(msg)


class SummaryGenerationError(Exception):
    """摘要生成失败 — LLM 调用错误.

    不阻断写作流程，由 SummaryService 捕获后记录 WARNING 日志并跳过.
    """

    def __init__(self, chapter_id: str, detail: str = "") -> None:
        self.chapter_id = chapter_id
        self.detail = detail
        msg = f"章节摘要生成失败: chapter_id={chapter_id}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)
