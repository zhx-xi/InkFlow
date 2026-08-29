"""伏笔管理领域异常.

F13 专属异常类型，继承自 Exception。
依据: specs/f13-foreshadowing/spec.md §3.4/§8。

异常映射约定（spec §3.4 异常映射表）:
- ForeshadowingServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- ForeshadowingNotFoundError / ProjectNotFoundError = 资源不存在，API 层映射为 404
- 无 LLM 相关错误（F13 无 LLM，伏笔状态追踪为确定性逻辑，见 §5）

与 F9/F10/F11 的差异: 无 LLM 提取/生成错误。
与 F12 的差异: foreshadowings 有全唯一约束（(project_id, title)，
「同名 = 同一伏笔」，见 §2.3），故有同名冲突类错误
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


class ForeshadowingExtractionError(Exception):
    """伏笔提取失败 — LLM 输出无法解析为合法伏笔 JSON（F14 §5.4）— 500.

    修复重试耗尽后抛出，由调用方（API/CLI/门面）映射为 500。
    依据: specs/f14-extraction/spec.md §5.4 + §7 异常映射表。

    Attributes:
        raw_output: LLM 原始输出片段（诊断用，可能被截断 ≤ 500 字符）.
        detail: 失败原因描述.
    """

    def __init__(self, raw_output: str = "", detail: str = "") -> None:
        self.raw_output = raw_output
        self.detail = detail
        msg = "伏笔提取失败: LLM 输出无法解析为合法 JSON"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)
