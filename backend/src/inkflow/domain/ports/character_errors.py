"""角色管理领域异常.

F9 专属异常类型，继承自 Exception.
依据: specs/f9-character-service/spec.md §5/§8.

异常映射约定（spec §3.5 异常映射表）:
- CharacterServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- CharacterNotFoundError / ProjectNotFoundError = 资源不存在，API 层映射为 404
- CharacterExtractionError = LLM 输出解析失败，API 层映射为 500
"""

from __future__ import annotations


class CharacterExtractionError(Exception):
    """角色提取失败 — LLM 输出无法解析为合法角色/关系 JSON.

    修复重试耗尽后抛出，由调用方（API/CLI）映射为 LLM_ERROR 错误信封。

    Attributes:
        raw_output: LLM 原始输出片段（诊断用，可能被截断）.
        detail: 失败原因描述.
    """

    def __init__(self, raw_output: str = "", detail: str = "") -> None:
        self.raw_output = raw_output
        self.detail = detail
        msg = "角色提取失败: LLM 输出无法解析为合法 JSON"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class CharacterServiceError(Exception):
    """角色服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §3.5 中文文案）。
    """


class CharacterNotFoundError(Exception):
    """角色不存在 — API 层映射为 404「角色不存在」.

    用于 create_relation 等返回非 Optional 的方法（路径角色 / 目标角色缺失）；
    其余 CRUD 方法以返回 None 表达不存在（router 层统一转 404）。
    """

    def __init__(self, message: str = "角色不存在") -> None:
        super().__init__(message)


class ProjectNotFoundError(Exception):
    """项目不存在 — extract 入口校验失败，API 层映射为 404「项目不存在」."""

    def __init__(self, message: str = "项目不存在") -> None:
        super().__init__(message)


class CharacterNameConflictError(CharacterServiceError):
    """同名角色已存在（角色名在项目内必须唯一）— 422."""

    def __init__(self, message: str = "同名角色已存在（角色名在项目内必须唯一）") -> None:
        super().__init__(message)


class GroupNameConflictError(CharacterServiceError):
    """同名分组已存在（分组名在项目内必须唯一）— 422."""

    def __init__(self, message: str = "同名分组已存在（分组名在项目内必须唯一）") -> None:
        super().__init__(message)


class GroupNotInProjectError(CharacterServiceError):
    """分组不存在于该项目（分组缺失或属于其他项目）— 422."""

    def __init__(self, message: str = "分组不存在于该项目") -> None:
        super().__init__(message)


class SelfRelationError(CharacterServiceError):
    """关系两端不能是同一角色（自环）— 422."""

    def __init__(self, message: str = "关系两端不能是同一角色") -> None:
        super().__init__(message)


class CrossProjectRelationError(CharacterServiceError):
    """角色与目标角色不属于同一项目 — 422."""

    def __init__(self, message: str = "角色与目标角色不属于同一项目") -> None:
        super().__init__(message)


class RelationConflictError(CharacterServiceError):
    """该关系已存在（(from, to, relation_type) 活动关系唯一）— 422."""

    def __init__(self, message: str = "该关系已存在") -> None:
        super().__init__(message)
