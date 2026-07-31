"""LLM 领域异常类型 — 领域层可用，零框架依赖。"""

from __future__ import annotations


class LLMRequestError(Exception):
    """LLM 调用失败（网络、超时、Provider 错误、Key 无效等）。

    领域层 Service 可捕获此异常做业务决策（如通知用户切换模型）。
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        retries_exhausted: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.retries_exhausted = retries_exhausted


class TemplateNotFoundError(Exception):
    """Prompt 模板不存在。"""

    def __init__(self, template_name: str) -> None:
        super().__init__(f"Prompt template not found: {template_name}")
        self.template_name = template_name


class TemplateRenderError(Exception):
    """模板渲染失败（缺少变量、格式错误等）。"""

    def __init__(
        self,
        message: str,
        *,
        template_name: str = "",
        missing_variables: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.template_name = template_name
        self.missing_variables = missing_variables or []
