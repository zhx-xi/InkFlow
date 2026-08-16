"""Agent 领域异常.

F39 专属异常类型，继承自 Exception。
依据: specs/f39-multi-agent/spec.md §3.3（异常映射表）+ §7（边界与错误）。

异常映射约定:
- AgentServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- AgentNotFoundError = 资源不存在，API 层映射为 404（独立于 ServiceError，
  镜像 agent_template_errors.py）
- AgentBuiltinError = 内置 Agent 只读保护，API 层映射为 409
- ToolReferenceError / SkillReferenceError = 白名单引用校验失败，422
"""

from __future__ import annotations


class AgentServiceError(Exception):
    """Agent 服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（中文文案）。
    """


class AgentNotFoundError(Exception):
    """Agent 不存在 — API 层映射为 404「Agent 不存在」."""

    def __init__(self, message: str = "Agent 不存在") -> None:
        super().__init__(message)


class AgentNameConflictError(AgentServiceError):
    """同名 Agent 已存在（Agent 名称必须唯一）— 422."""

    def __init__(self, message: str = "同名 Agent 已存在（Agent 名称必须唯一）") -> None:
        super().__init__(message)


class AgentBuiltinError(AgentServiceError):
    """内置 Agent 不可修改或删除 — 409."""

    def __init__(self, message: str = "内置 Agent 不可修改或删除") -> None:
        super().__init__(message)


class ToolReferenceError(AgentServiceError):
    """tool_ids 含目录外工具名 — 422."""

    def __init__(self, message: str = "tool_ids 含目录外工具名") -> None:
        super().__init__(message)


class SkillReferenceError(AgentServiceError):
    """skill_ids 含不存在的 Skill — 422."""

    def __init__(self, message: str = "skill_ids 含不存在的 Skill") -> None:
        super().__init__(message)
