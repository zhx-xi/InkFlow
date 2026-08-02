"""一致性审计服务领域异常.

F15 专属异常类型。
依据: specs/f15-audit-service/spec.md §3.3/§8。

异常映射约定（spec §3.3 异常映射表）:
- AuditServiceError 子类 = 审计领域错误基类（消息即响应 detail 中文文案）
- ProjectNotFoundError = 项目不存在，API 层映射为 404「项目不存在」
- 无 LLM 相关错误（F15 无 LLM，审计为确定性只读计算，见 §1/§5）
- 无 422 业务校验错误（F15 唯一输入是路径 project_id，无请求体/查询参数，
  错误面只有 404 与 500，见 spec §3.3 注）
"""

from __future__ import annotations


class AuditServiceError(Exception):
    """审计服务领域错误基类 — 审计语义失败.

    子类消息即响应 detail（spec §3.3 中文文案）。
    """


class ProjectNotFoundError(AuditServiceError):
    """项目不存在 — 审计入口校验失败，API 层映射为 404「项目不存在」.

    Attributes:
        message: 默认中文消息「项目不存在」.
    """

    def __init__(self, message: str = "项目不存在") -> None:
        super().__init__(message)
