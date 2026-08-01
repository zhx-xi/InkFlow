"""伏笔管理领域异常.

F13 专属异常类型，继承自 Exception。
依据: specs/f13-foreshadowing-service/spec.md §3.4/§8。

异常映射约定（spec §3.4 异常映射表）:
- ForeshadowingServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- ForeshadowingNotFoundError / ProjectNotFoundError = 资源不存在，API 层映射为 404
- 无 LLM 相关错误（F13 无 LLM，伏笔状态追踪为确定性逻辑，见 §5）

与 F9/F10/F11 的差异: 无 LLM 提取/生成错误。
与 F12 的差异: foreshadowings 有 partial unique 约束（(project_id, title)
WHERE is_deleted = 0，「同名 = 同一伏笔」，见 §2.3），故有同名冲突类错误
（ForeshadowingNameConflictError）；且伏笔可挂接 F12 时间线事件（event_id
锚点，见 §2.2），故新增事件校验类错误（EventNotFoundError /
EventNotInProjectError，见 §3.4）。
"""

from __future__ import annotations


class ForeshadowingServiceError(Exception):
    """伏笔服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §3.4 中文文案）。
    """


class ForeshadowingNotFoundError(Exception):
    """伏笔不存在 — API 层映射为 404「伏笔不存在」.

    用于必须返回实体的方法（路径伏笔缺失）；
    其余 CRUD 方法以返回 None 表达不存在（router 层统一转 404）。
    """

    def __init__(self, message: str = "伏笔不存在") -> None:
        super().__init__(message)


class ProjectNotFoundError(Exception):
    """项目不存在 — 各操作入口校验失败，API 层映射为 404「项目不存在」.

    仅模块内定义供服务层使用，不在 ports/__init__.py 导出
    （F9 character_errors 已有同名导出，避免遮蔽）。
    """

    def __init__(self, message: str = "项目不存在") -> None:
        super().__init__(message)


class ForeshadowingNameConflictError(ForeshadowingServiceError):
    """同名伏笔已存在（伏笔名在项目内必须唯一）— 422."""

    def __init__(self, message: str = "同名伏笔已存在（伏笔名在项目内必须唯一）") -> None:
        super().__init__(message)


class EventNotFoundError(ForeshadowingServiceError):
    """event_id 指向不存在的事件（含已软删事件）— 422.

    服务层经 F12 TimelineRepositoryProtocol.get 校验（get 不含软删事件）。
    """

    def __init__(self, message: str = "事件不存在") -> None:
        super().__init__(message)


class EventNotInProjectError(ForeshadowingServiceError):
    """event_id 指向其他项目的事件 — 422.

    服务层校验 event.project_id == 伏笔.project_id。
    """

    def __init__(self, message: str = "事件不属于该项目") -> None:
        super().__init__(message)
