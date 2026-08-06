"""AgentTemplate 领域异常.

#107 专属异常类型，继承自 Exception。
依据: specs/f19-gui/spec.md §9.2。

异常映射约定:
- AgentTemplateServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- AgentTemplateNotFoundError = 资源不存在，API 层映射为 404
- AgentTemplateBuiltinError = 默认/内置模板保护，API 层映射为 409
  （「默认模板不可删除」，spec §9.7「内置模板不可删」实体化等价实现）
"""

from __future__ import annotations


class AgentTemplateServiceError(Exception):
    """模板服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（中文文案）。
    """


class AgentTemplateNotFoundError(Exception):
    """模板不存在 — API 层映射为 404「模板不存在」."""

    def __init__(self, message: str = "模板不存在") -> None:
        super().__init__(message)


class AgentTemplateNameConflictError(AgentTemplateServiceError):
    """同名模板已存在（模板名称必须唯一）— 422."""

    def __init__(self, message: str = "同名模板已存在（模板名称必须唯一）") -> None:
        super().__init__(message)


class AgentTemplateBuiltinError(AgentTemplateServiceError):
    """内置模板不可删除 — API 层映射为 409「默认模板不可删除」."""

    def __init__(self, message: str = "内置模板不可删除") -> None:
        super().__init__(message)
