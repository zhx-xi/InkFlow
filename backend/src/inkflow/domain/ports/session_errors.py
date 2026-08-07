"""会话管理领域异常.

F24 专属异常类型，继承自 Exception。
依据: specs/f24-session-service/spec.md §8.1。

异常映射约定（spec §8.1 异常映射表）:
- SessionServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- SessionNotFoundError = 会话不存在，API 层映射为 404（不继承基类——同 F12/F13 惯例）
- 无 LLM 相关错误（F24 无 LLM，状态机与履历为确定性逻辑，见 spec §1.1）

与 F9/F12/F13 的差异: 不定义 ProjectNotFoundError——创建会话的项目存在性
校验复用 F9 character_errors.ProjectNotFoundError（陷阱 16：不导出同名类到
ports/__init__.py，避免遮蔽破坏既有 router 的 except 链）。
"""

from __future__ import annotations


class SessionServiceError(Exception):
    """会话服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §8.1 中文文案）。
    """


class SessionNotFoundError(Exception):
    """会话不存在 — API 层映射为 404「会话不存在」.

    用于必须返回实体的方法（路径会话缺失）；其余 CRUD 方法以返回 None
    表达不存在（router 层统一转 404）。
    """

    def __init__(self, message: str = "会话不存在") -> None:
        super().__init__(message)


class SessionTransitionError(SessionServiceError):
    """非法状态迁移（422）."""
