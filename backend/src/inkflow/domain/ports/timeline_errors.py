"""时间线管理领域异常.

F12 专属异常类型，继承自 Exception。
依据: specs/f12-timeline/spec.md §3.4/§8。

异常映射约定（spec §3.4 异常映射表）:
- TimelineServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- TimelineNotFoundError / ProjectNotFoundError = 资源不存在，API 层映射为 404
- 无 LLM 相关错误（F12 无 LLM，一致性检查为确定性算法，见 §5）

与 F9/F10/F11 的差异: timeline_events 不设任何唯一约束
（title / narrative_position / time_value 均允许重复，事件是实例而非档案，
见 §2.4），服务层无同名冲突检查，故无冲突类错误。
"""

from __future__ import annotations


class TimelineServiceError(Exception):
    """时间线服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §3.4 中文文案）。
    """


class TimelineExtractionError(Exception):
    """时间线提取失败 — LLM 输出无法解析为合法时间线事件 JSON.

    F14 §5.5 修复重试耗尽后抛出，由调用方（API/CLI）映射为 500（同 F9
    CharacterExtractionError 语义）。

    Attributes:
        raw_output: LLM 原始输出片段（诊断用，可能被截断）.
        detail: 失败原因描述.
    """

    def __init__(self, raw_output: str = "", detail: str = "") -> None:
        self.raw_output = raw_output
        self.detail = detail
        msg = "时间线提取失败: LLM 输出无法解析为合法 JSON"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class TimelineNotFoundError(Exception):
    """事件不存在 — API 层映射为 404「事件不存在」.

    用于必须返回实体的方法（路径事件缺失）；
    其余 CRUD 方法以返回 None 表达不存在（router 层统一转 404）。
    """

    def __init__(self, message: str = "事件不存在") -> None:
        super().__init__(message)


class ProjectNotFoundError(Exception):
    """项目不存在 — 各操作入口校验失败，API 层映射为 404「项目不存在」."""

    def __init__(self, message: str = "项目不存在") -> None:
        super().__init__(message)
