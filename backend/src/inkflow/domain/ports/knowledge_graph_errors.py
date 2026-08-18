"""知识图谱领域异常.

F48 专属异常类型，继承自 Exception。
依据: specs/f48-knowledge-graph/spec.md §3.3。

异常映射约定（spec §3.3 异常映射表）:
- KnowledgeGraphServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- KnowledgeRelationNotFoundError = 资源不存在，API 层映射为 404（不继承 422 基类）
- ProjectNotFoundError 复用 F10 world_errors（不重定义通用名错误类）
"""

from __future__ import annotations


class KnowledgeGraphServiceError(Exception):
    """图谱服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §3.3 中文文案）。
    """


class KnowledgeRelationConflictError(KnowledgeGraphServiceError):
    """该关系已存在（同键唯一）— 422."""

    def __init__(self, message: str = "该关系已存在（同键唯一）") -> None:
        super().__init__(message)


class KnowledgeRelationSelfLoopError(KnowledgeGraphServiceError):
    """关系两端不能是同一实体（自环）— 422."""

    def __init__(self, message: str = "关系两端不能是同一实体（自环）") -> None:
        super().__init__(message)


class KnowledgeEntityNotFoundError(KnowledgeGraphServiceError):
    """起点/终点实体不存在或不在同一项目 — 422.

    构造时通过 message 指明 source/target 端 + 实体类型（spec §3.3 detail 要求）。
    """

    def __init__(self, message: str = "起点/终点实体不存在或不在同一项目") -> None:
        super().__init__(message)


class KnowledgeRelationNotFoundError(Exception):
    """关系不存在 — 404（不继承 422 基类）."""

    def __init__(self, message: str = "关系不存在") -> None:
        super().__init__(message)


class KnowledgeRelationValidationError(KnowledgeGraphServiceError):
    """六元组非法（字段校验）— 422."""

    def __init__(self, message: str = "六元组非法（字段校验）") -> None:
        super().__init__(message)
