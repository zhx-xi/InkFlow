"""ProviderConfig 领域异常.

#106 专属异常类型，继承自 Exception。
依据: specs/f19-gui/spec.md §8.2。

异常映射约定:
- ProviderConfigServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- ProviderConfigNotFoundError = 资源不存在，API 层映射为 404
"""

from __future__ import annotations


class ProviderConfigServiceError(Exception):
    """Provider 服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（中文文案）。
    """


class ProviderConfigNotFoundError(Exception):
    """Provider 不存在 — API 层映射为 404「Provider 不存在」."""

    def __init__(self, message: str = "Provider 不存在") -> None:
        super().__init__(message)


class ProviderConfigNameConflictError(ProviderConfigServiceError):
    """同名 Provider 已存在（provider 名称必须唯一）— 422."""

    def __init__(self, message: str = "同名 Provider 已存在（provider 名称必须唯一）") -> None:
        super().__init__(message)
